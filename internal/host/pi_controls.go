package host

// The browser gets a small, typed Pi capability adapter, never an RPC tunnel.
import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"regexp"
	"strings"
	"sync"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
	"github.com/atongrun/agent-workflow/internal/pi"
)

type piBinding struct {
	Role      string `json:"role"`
	SessionID string `json:"sessionId"`
	ProcessID string `json:"processId"`
}
type piModel struct {
	Provider string `json:"provider"`
	ID       string `json:"id"`
	Name     string `json:"name"`
}
type piCommand struct {
	Name        string `json:"name"`
	Description string `json:"description,omitempty"`
	Source      string `json:"source"`
}
type piControlInput struct {
	RequestID         string `json:"requestId"`
	Role              string `json:"role,omitempty"`
	ExpectedSessionID string `json:"expectedSessionId,omitempty"`
	ExpectedProcessID string `json:"expectedProcessId,omitempty"`
	Provider          string `json:"provider,omitempty"`
	ModelID           string `json:"modelId,omitempty"`
}

func (in piControlInput) binding() piBinding {
	return piBinding{in.Role, in.ExpectedSessionID, in.ExpectedProcessID}
}

var commandNamePattern = regexp.MustCompile(`^[^\s/\x00-\x1f\x7f]{1,200}$`)

// Dispatch locks cover only validation and the synchronous JSONL write, never
// waiting for a native reply. In particular abort must interrupt compact.
func (s *Server) piDispatchLock(taskID, role string) *sync.Mutex {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.dispatches == nil {
		s.dispatches = map[string]*sync.Mutex{}
	}
	key := taskID + ":" + role
	if s.dispatches[key] == nil {
		s.dispatches[key] = &sync.Mutex{}
	}
	return s.dispatches[key]
}
func bindingMatches(ref *core.Session, binding piBinding) bool {
	return ref != nil && ref.ID == binding.SessionID && ref.ProcessID == binding.ProcessID
}
func validPiRole(role string) bool { return role == "architect" || role == "reviewer" }
func piControlOperation(op string) bool {
	return op == "pi/model" || op == "pi/compact" || op == "pi/abort"
}
func pendingPiControl(st *core.State, ref *core.Session) bool {
	for _, id := range ref.PendingCommands {
		if req := st.Requests[id]; req != nil && piControlOperation(req.Operation) {
			return true
		}
	}
	return false
}

// Caller holds the dispatch lock. This never starts or replaces a process.
func (s *Server) boundPiClient(taskID string, binding piBinding) (*pi.Client, error) {
	task, err := s.task(taskID)
	if err != nil {
		return nil, err
	}
	ref := task.Sessions[binding.Role]
	if !bindingMatches(ref, binding) {
		return nil, fail("stale_pi_session", "Pi session changed; refresh before choosing this action again", 409)
	}
	if !ref.Available {
		return nil, fail("session_unavailable", "Pi is not running; refresh the conversation first", 409)
	}
	s.mu.Lock()
	client := s.clients[taskID+":"+binding.Role]
	closing := s.closing
	s.mu.Unlock()
	if closing || client == nil || !client.Alive() {
		return nil, fail("session_unavailable", "Pi is not running; refresh the conversation first", 409)
	}
	return client, nil
}
func (s *Server) piReadCall(ctx context.Context, taskID string, binding piBinding, method string) (json.RawMessage, error) {
	lock := s.piDispatchLock(taskID, binding.Role)
	lock.Lock()
	client, err := s.boundPiClient(taskID, binding)
	var call *pi.PendingCall
	if err == nil {
		call, err = client.BeginCall(method, nil)
	}
	lock.Unlock()
	if err != nil {
		return nil, err
	}
	data, err := call.Wait(ctx)
	if err != nil {
		return nil, fail("pi_unavailable", "Pi did not return this read; refresh and retry", 503)
	}
	lock.Lock()
	current, checkErr := s.boundPiClient(taskID, binding)
	lock.Unlock()
	if checkErr != nil {
		return nil, checkErr
	}
	if current != client {
		return nil, fail("stale_pi_session", "Pi process changed during this read", 409)
	}
	return data, nil
}
func (s *Server) piRead(w http.ResponseWriter, r *http.Request) {
	role := r.URL.Query().Get("role")
	if !validPiRole(role) || len(r.URL.Query()) != 1 || len(r.URL.Query()["role"]) != 1 {
		writeError(w, fail("invalid_query", "exactly one architect or reviewer role is required", 400))
		return
	}
	taskID := r.PathValue("id")
	task, err := s.task(taskID)
	if err != nil {
		writeError(w, err)
		return
	}
	ref := task.Sessions[role]
	if ref == nil || ref.ProcessID == "" || !ref.Available {
		writeError(w, fail("session_unavailable", "Pi is not running; refresh the conversation first", 409))
		return
	}
	binding := piBinding{role, ref.ID, ref.ProcessID}
	ctx, cancel := context.WithTimeout(r.Context(), 15*time.Second)
	defer cancel()
	result := map[string]any{"binding": binding}
	switch strings.TrimPrefix(r.URL.Path, "/v1/tasks/"+taskID+"/pi/") {
	case "commands":
		var native struct {
			Commands []piCommand `json:"commands"`
		}
		var data json.RawMessage
		data, err = s.piReadCall(ctx, taskID, binding, "get_commands")
		if err == nil {
			err = json.Unmarshal(data, &native)
		}
		commands := []piCommand{}
		for _, command := range native.Commands {
			if !commandNamePattern.MatchString(command.Name) || (command.Source != "extension" && command.Source != "prompt" && command.Source != "skill") {
				continue
			}
			command.Description = bounded(command.Description, 1000)
			commands = append(commands, command)
			if len(commands) >= 500 {
				break
			}
		}
		result["commands"] = commands
		result["controls"] = []string{"stats", "model", "compact", "stop"}
	case "models":
		var native struct {
			Models []piModel `json:"models"`
		}
		var data json.RawMessage
		data, err = s.piReadCall(ctx, taskID, binding, "get_available_models")
		if err == nil {
			err = json.Unmarshal(data, &native)
		}
		models := []piModel{}
		for _, model := range native.Models {
			if validModel(model) {
				models = append(models, model)
			}
			if len(models) >= 2000 {
				break
			}
		}
		result["models"] = models
		if err == nil {
			result["current"], err = s.piCurrentModel(ctx, taskID, binding)
		}
	case "stats":
		var data json.RawMessage
		data, err = s.piReadCall(ctx, taskID, binding, "get_session_stats")
		if err == nil {
			var stats struct {
				UserMessages      int64 `json:"userMessages"`
				AssistantMessages int64 `json:"assistantMessages"`
				ToolCalls         int64 `json:"toolCalls"`
				ToolResults       int64 `json:"toolResults"`
				TotalMessages     int64 `json:"totalMessages"`
				Tokens            struct {
					Input      int64 `json:"input"`
					Output     int64 `json:"output"`
					CacheRead  int64 `json:"cacheRead"`
					CacheWrite int64 `json:"cacheWrite"`
					Total      int64 `json:"total"`
				} `json:"tokens"`
				Cost         float64 `json:"cost"`
				ContextUsage *struct {
					Tokens        *int64   `json:"tokens"`
					ContextWindow int64    `json:"contextWindow"`
					Percent       *float64 `json:"percent"`
				} `json:"contextUsage,omitempty"`
			}
			err = json.Unmarshal(data, &stats)
			result["stats"] = stats
		}
		if err == nil {
			result["current"], err = s.piCurrentModel(ctx, taskID, binding)
		}
	default:
		writeError(w, fail("not_found", "unknown Pi read", 404))
		return
	}
	if err != nil {
		var api *apiError
		if !errors.As(err, &api) {
			err = fail("invalid_pi_response", "Pi returned an unsupported response", 502)
		}
		writeError(w, err)
		return
	}
	writeJSON(w, 200, result)
}
func validModel(model piModel) bool {
	return model.Provider != "" && model.ID != "" && len(model.Provider) <= 200 && len(model.ID) <= 300 && len(model.Name) <= 500
}
func (s *Server) piCurrentModel(ctx context.Context, taskID string, binding piBinding) (*piModel, error) {
	data, err := s.piReadCall(ctx, taskID, binding, "get_state")
	if err != nil {
		return nil, err
	}
	var state struct {
		Model *piModel `json:"model"`
	}
	if err = json.Unmarshal(data, &state); err != nil {
		return nil, err
	}
	if state.Model != nil && !validModel(*state.Model) {
		return nil, errors.New("invalid model")
	}
	return state.Model, nil
}
func (s *Server) piControl(w http.ResponseWriter, r *http.Request) {
	var in piControlInput
	if err := decode(w, r, &in); err != nil {
		writeError(w, err)
		return
	}
	if in.Role == "" {
		in.Role = "architect"
	}
	if !validPiRole(in.Role) {
		writeError(w, fail("invalid_role", "role must be architect or reviewer", 400))
		return
	}
	if len(r.URL.Query()) != 0 {
		writeError(w, fail("invalid_query", "Pi controls do not accept query parameters", 400))
		return
	}
	taskID := r.PathValue("id")
	op := strings.TrimPrefix(r.URL.Path, "/v1/tasks/"+taskID+"/")
	if !piControlOperation(op) {
		writeError(w, fail("not_found", "unknown Pi control", 404))
		return
	}
	lock := s.piDispatchLock(taskID, in.Role)
	lock.Lock()
	duplicate, err := s.reserveRequest(in.RequestID, taskID, op, in, func(st *core.State, req *core.Request) error {
		task := st.Tasks[taskID]
		if task == nil {
			return fail("not_found", "task not found", 404)
		}
		ref := task.Sessions[in.Role]
		if in.ExpectedSessionID == "" || in.ExpectedProcessID == "" || !bindingMatches(ref, in.binding()) {
			return fail("stale_pi_session", "the intended Pi session and process are required; refresh before retrying", 409)
		}
		if !ref.Available {
			return fail("session_unavailable", "the intended Pi session is not running", 409)
		}
		if op == "pi/model" {
			if !validModel(piModel{Provider: in.Provider, ID: in.ModelID}) {
				return fail("invalid_model", "select a returned provider and model ID", 400)
			}
		} else if in.Provider != "" || in.ModelID != "" {
			return fail("invalid_control", "model fields are only accepted for model selection", 400)
		}
		if op != "pi/abort" {
			if !taskPiIdle(task) {
				return fail("pi_busy", "wait for all task Pi roles, queued messages and dialogs to settle", 409)
			}
			if op == "pi/compact" && remainingSeconds(task) <= 0 {
				return fail("budget_exhausted", "task budget exhausted", 409)
			}
		} else {
			for _, pendingID := range append([]string(nil), ref.PendingCommands...) {
				pending := st.Requests[pendingID]
				if pending == nil {
					continue
				}
				if pending.Operation == "pi/model" && pending.Dispatched {
					return fail("pi_busy", "wait for the model selection receipt before stopping Pi", 409)
				}
				if pending.Operation == "pi/abort" {
					return fail("pi_busy", "a Pi stop already needs its receipt", 409)
				}
				if !pending.Dispatched && pending.Status == "accepted" {
					pending.Status = "cancelled"
					settleCommand(ref, pendingID)
				}
			}
		}
		req.Role = in.Role
		req.SessionID = ref.ID
		req.ProcessID = ref.ProcessID
		ref.PendingCommands = append(ref.PendingCommands, in.RequestID)
		refreshPending(ref)
		core.Changed(st, task)
		return nil
	})
	lock.Unlock()
	if err != nil {
		writeError(w, err)
		return
	}
	if !duplicate {
		if !s.launch(func() { s.runPiControl(taskID, op, in) }) {
			s.finishPiControl(in.RequestID, "failed", "Host is closing; the control was not sent", nil)
		}
	}
	s.response(w, in.RequestID)
}
func (s *Server) runPiControl(taskID, op string, in piControlInput) {
	binding := in.binding()
	method := map[string]string{"pi/model": "set_model", "pi/compact": "compact", "pi/abort": "clear_queue"}[op]
	fields := map[string]any{}
	if op == "pi/model" {
		fields["provider"] = in.Provider
		fields["modelId"] = in.ModelID
	}
	lock := s.piDispatchLock(taskID, in.Role)
	lock.Lock()
	client, err := s.boundPiClient(taskID, binding)
	// Host snapshots can lag a native event. Recheck native readiness before
	// compact (which otherwise aborts a run), and validate actual model choices.
	if err == nil && op != "pi/abort" {
		ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
		var data json.RawMessage
		data, err = client.Call(ctx, "get_state", nil)
		var native struct {
			Model               *piModel `json:"model"`
			SessionID           string   `json:"sessionId"`
			IsStreaming         bool     `json:"isStreaming"`
			IsCompacting        bool     `json:"isCompacting"`
			PendingMessageCount int      `json:"pendingMessageCount"`
		}
		if err == nil {
			err = json.Unmarshal(data, &native)
		}
		if err == nil && (native.SessionID != binding.SessionID || native.IsStreaming || native.IsCompacting || native.PendingMessageCount != 0) {
			err = errors.New("native Pi is no longer idle")
		}
		if err == nil && op == "pi/model" {
			data, err = client.Call(ctx, "get_available_models", nil)
			var available struct {
				Models []piModel `json:"models"`
			}
			if err == nil {
				err = json.Unmarshal(data, &available)
			}
			found := false
			for _, model := range available.Models {
				if model.Provider == in.Provider && model.ID == in.ModelID {
					found = true
					break
				}
			}
			if err == nil && !found {
				err = errors.New("selected model is no longer available")
			}
		}
		cancel()
	}
	var pending *pi.PendingCall
	if err == nil {
		err = s.store.Update(func(st *core.State) error {
			req := st.Requests[in.RequestID]
			if req == nil || req.Status != "accepted" {
				return fail("control_cancelled", "Pi control is no longer pending", 409)
			}
			if !bindingMatches(st.Tasks[taskID].Sessions[in.Role], binding) {
				return fail("stale_pi_session", "Pi process changed before dispatch", 409)
			}
			req.Dispatched = true
			return nil
		})
	}
	if err == nil {
		pending, err = client.BeginCall(method, fields)
	}
	lock.Unlock()
	if err != nil {
		request := s.store.Snapshot().Requests[in.RequestID]
		if request != nil && request.Status == "cancelled" {
			return
		}
		status := "failed"
		if request != nil && request.Dispatched {
			status = "needs_verification"
		}
		s.finishPiControl(in.RequestID, status, "Pi control was not confirmed; refresh its receipt before continuing", nil)
		return
	}
	timeout := 30 * time.Second
	if op == "pi/compact" {
		timeout = 5 * time.Minute
		s.launch(func() { s.watchPiBudget(taskID, in.Role, client) })
	}
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	data, err := pending.Wait(ctx)
	var result any
	if err == nil && op == "pi/abort" {
		s.emitClearedQueue(taskID, binding, data)
		_, err = client.Call(ctx, "abort", nil)
	}
	if err == nil && op == "pi/model" {
		var model piModel
		err = json.Unmarshal(data, &model)
		if !validModel(model) || model.Provider != in.Provider || model.ID != in.ModelID {
			err = errors.New("model response did not match the selected model")
		}
		result = map[string]any{"model": model}
	}
	if err == nil && op == "pi/compact" {
		var compact struct {
			TokensBefore         int64 `json:"tokensBefore"`
			EstimatedTokensAfter int64 `json:"estimatedTokensAfter"`
		}
		err = json.Unmarshal(data, &compact)
		result = compact
	}
	if err != nil {
		s.finishPiControl(in.RequestID, "needs_verification", "Pi did not confirm this control. It will not be sent again; inspect the native session and receipt", nil)
		return
	}
	// Reconcile only this process. Late replies never overwrite its replacement.
	state, stateErr := client.Call(ctx, "get_state", nil)
	if stateErr != nil {
		s.finishPiControl(in.RequestID, "needs_verification", "Pi responded but its final state could not be verified", nil)
		return
	}
	err = s.store.Update(func(st *core.State) error {
		task := st.Tasks[taskID]
		ref := task.Sessions[in.Role]
		if !bindingMatches(ref, binding) || !ref.Available {
			return fail("stale_pi_session", "Pi process changed before its final receipt", 409)
		}
		var native struct {
			Model               *piModel `json:"model"`
			SessionID           string   `json:"sessionId"`
			IsStreaming         bool     `json:"isStreaming"`
			IsCompacting        bool     `json:"isCompacting"`
			PendingMessageCount int      `json:"pendingMessageCount"`
		}
		if json.Unmarshal(state, &native) != nil || native.SessionID != binding.SessionID {
			return errors.New("invalid Pi final state")
		}
		if op == "pi/model" && (native.Model == nil || native.Model.Provider != in.Provider || native.Model.ID != in.ModelID) {
			return errors.New("current model did not match the selected model")
		}
		if op == "pi/abort" && (native.IsStreaming || native.IsCompacting || native.PendingMessageCount != 0) {
			return errors.New("Pi stop has not reached idle state")
		}
		ref.Streaming = native.IsStreaming
		ref.Compacting = native.IsCompacting
		ref.Busy = native.IsStreaming || native.IsCompacting
		ref.NativeQueued = native.PendingMessageCount
		if op == "pi/abort" {
			ref.PendingUI = nil
			ref.DialogDeadlines = nil
			ref.AwaitingStart = false
		}
		refreshPending(ref)
		core.Changed(st, task)
		return nil
	})
	if err != nil {
		s.finishPiControl(in.RequestID, "needs_verification", "Pi session changed before the control could be verified", nil)
		return
	}
	s.finishPiControl(in.RequestID, "completed", "", result)
}
func (s *Server) finishPiControl(requestID, status, message string, result any) {
	_ = s.store.Update(func(st *core.State) error {
		req := st.Requests[requestID]
		if req == nil || req.Status == "cancelled" {
			return nil
		}
		req.Status = status
		req.Error = message
		if result != nil {
			req.Result, _ = json.Marshal(result)
		}
		task := st.Tasks[req.TaskID]
		if task == nil {
			return nil
		}
		ref := task.Sessions[req.Role]
		if bindingMatches(ref, piBinding{req.Role, req.SessionID, req.ProcessID}) {
			// Unknown controls remain a gate until the native process is reconciled.
			if status != "needs_verification" {
				settleCommand(ref, requestID)
			}
			active := false
			for _, session := range task.Sessions {
				active = active || session.Busy || session.Streaming || session.Compacting
			}
			if !active {
				s.chargePi(task)
			}
			core.Changed(st, task)
		}
		core.Emit(st, req.TaskID, "pi.control", map[string]any{"requestId": requestID, "status": status, "role": req.Role})
		return nil
	})
}
func (s *Server) emitClearedQueue(taskID string, binding piBinding, data json.RawMessage) {
	var queue struct {
		Steering []string `json:"steering"`
		FollowUp []string `json:"followUp"`
	}
	if json.Unmarshal(data, &queue) != nil {
		return
	}
	s.piEvent(taskID, binding.Role, binding.ProcessID, mustJSON(map[string]any{"type": "awf_queue_cleared", "steering": queue.Steering, "followUp": queue.FollowUp}))
}
func (s *Server) piRequest(w http.ResponseWriter, r *http.Request) {
	if len(r.URL.Query()) != 0 {
		writeError(w, fail("invalid_query", "request receipts do not accept query parameters", 400))
		return
	}
	st := s.store.Snapshot()
	req := st.Requests[r.PathValue("requestId")]
	if req == nil || req.TaskID != r.PathValue("id") {
		writeError(w, fail("not_found", "request receipt not found for this task", 404))
		return
	}
	writeJSON(w, 200, map[string]any{"request": req, "task": st.Tasks[req.TaskID]})
}

// Stop cancels requests that have not crossed the JSONL write fence. Their text
// is supplied by the existing prompt goroutine, not stored as a second history.
func (s *Server) restoreCancelledPrompt(requestID, taskID, role, text string) bool {
	cancelled := false
	_ = s.store.Update(func(st *core.State) error {
		req := st.Requests[requestID]
		if req == nil || req.Status != "cancelled" {
			return nil
		}
		cancelled = true
		if len(req.Result) == 0 {
			req.Result = json.RawMessage(`{"draftRestored":true}`)
			core.Emit(st, taskID, "pi.event", map[string]any{"role": role, "event": map[string]any{"type": "awf_queue_cleared", "steering": []string{}, "followUp": []string{text}}})
		}
		return nil
	})
	return cancelled
}
