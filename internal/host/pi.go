package host

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
	"github.com/atongrun/agent-workflow/internal/pi"
)

func (s *Server) client(taskID, role string) (*pi.Client, error) {
	return s.clientWithStartFence(taskID, role, nil)
}

func (s *Server) clientWithStartFence(taskID, role string, beforeStart func(string) error) (*pi.Client, error) {
	s.piLifecycle.Lock()
	defer s.piLifecycle.Unlock()
	t, err := s.task(taskID)
	if err != nil {
		return nil, err
	}
	if t.DeletedAt != nil {
		return nil, fail("task_deleted", "restore this task before opening its native conversation", 409)
	}
	key := taskID + ":" + role
	s.mu.Lock()
	c := s.clients[key]
	s.mu.Unlock()
	if c != nil && c.Alive() {
		return c, nil
	}
	directory, err := s.planningDirectory(t)
	if err != nil {
		return nil, err
	}
	ref := t.Sessions[role]
	if ref == nil {
		return nil, fail("session_unavailable", "native role session does not exist", 409)
	}
	sessionFile := ref.File
	if sessionFile != "" {
		if _, statErr := os.Stat(sessionFile); statErr != nil {
			if !os.IsNotExist(statErr) || ref.Persisted {
				return nil, fail("session_missing", "previously persisted native session is unavailable; restore it before continuing", 409)
			}
			sessionFile = ""
		}
	}
	// A native history file also marks a resume in the crash window before
	// Persisted/File was confirmed. Never apply a new global default to it.
	sessionDirectory := filepath.Join(s.cfg.DataDir, "sessions", taskID, role)
	resuming := sessionFile != "" || ref.Persisted
	if entries, readErr := os.ReadDir(sessionDirectory); readErr == nil {
		for _, entry := range entries {
			if !strings.HasSuffix(entry.Name(), ".jsonl") || sessionFile != "" {
				continue
			}
			path := filepath.Join(sessionDirectory, entry.Name())
			file, err := os.Open(path)
			if err != nil {
				return nil, fail("session_missing", "native session history is unreadable", 409)
			}
			scanner := bufio.NewScanner(file)
			var header struct {
				Type string `json:"type"`
				ID   string `json:"id"`
			}
			valid := scanner.Scan() && json.Unmarshal(scanner.Bytes(), &header) == nil && header.Type == "session" && header.ID == ref.ID
			file.Close()
			if !valid {
				return nil, fail("session_missing", "native history cannot be matched to the original session", 409)
			}
			sessionFile, resuming = path, true
		}
	} else if !os.IsNotExist(readErr) {
		return nil, fail("session_unavailable", "native session directory is unreadable", 409)
	}
	if ref.Persisted && sessionFile == "" {
		return nil, fail("session_missing", "persisted native history is unavailable; restore it before continuing", 409)
	}
	catalog, err := s.modelCatalog()
	if err != nil {
		return nil, err
	}
	var requestedModel *core.PiModel
	var evict *pi.Client
	var evictKey string
	capacityErr := s.store.Update(func(st *core.State) error {
		if err := maintenanceEffect(st); err != nil {
			return err
		}
		s.mu.Lock()
		defer s.mu.Unlock()
		if s.closing {
			return fmt.Errorf("Host is closing")
		}
		live := s.starting
		for _, client := range s.clients {
			if client.Alive() {
				live++
			}
		}
		if live >= s.cfg.MaxPiProcesses {
			for candidate, client := range s.clients {
				if !client.Alive() {
					continue
				}
				parts := strings.SplitN(candidate, ":", 2)
				if len(parts) != 2 {
					continue
				}
				task := st.Tasks[parts[0]]
				if task == nil {
					continue
				}
				session := task.Sessions[parts[1]]
				if session == nil || !piReclaimable(st, task.ID, parts[1]) {
					continue
				}
				evict = client
				evictKey = candidate
				session.Available = false
				break
			}
			if evict == nil {
				return fail("pi_capacity", "all native Pi slots are active or need recovery; wait for a session to settle", 409)
			}
		}
		s.starting++
		return nil
	})
	if capacityErr != nil {
		return nil, capacityErr
	}
	defer func() { s.mu.Lock(); s.starting--; s.mu.Unlock() }()
	if evict != nil {
		if err := evict.Close(); err != nil {
			return nil, fail("pi_capacity", "native process exit was not confirmed; wait for recovery", 409)
		}
		s.mu.Lock()
		if s.clients[evictKey] == evict {
			delete(s.clients, evictKey)
		}
		s.mu.Unlock()
	}
	processID := core.ID()
	if err = s.store.Update(func(st *core.State) error {
		current := st.Tasks[taskID]
		// A legacy cwd was selected before acquiring the durable lock. Fence
		// target changes both before and after this first process reservation.
		if t.PlanningProfile == "" && (current.ProjectID != t.ProjectID || current.TargetRevision != t.TargetRevision) {
			return fail("target_changed", "legacy target changed while Pi was starting; retry the session read", 409)
		}
		current.Sessions[role].ProcessID = processID
		if !resuming {
			if current.Sessions[role].ModelStatus != "starting" {
				requestedModel = current.Sessions[role].Model
			}
			if requestedModel == nil {
				copy := st.Settings.PiDefaultModel
				requestedModel = &copy
			}
			if !catalogContains(catalog, *requestedModel) {
				return fail("needs_model_selection", "the default Pi model is unavailable; select an allowed default before creating a session", 409)
			}
			copy := *requestedModel
			current.Sessions[role].Model = &copy
			if current.Sessions[role].ModelStatus == "" || current.Sessions[role].ModelStatus == "starting" {
				current.Sessions[role].ModelStatus = "starting"
			}
		}
		return nil
	}); err != nil {
		return nil, err
	}
	provider, modelID := "", ""
	if requestedModel != nil {
		provider, modelID = requestedModel.Provider, requestedModel.ID
	}
	if beforeStart != nil {
		if err := beforeStart(processID); err != nil {
			return nil, err
		}
	}
	c, err = pi.Start(pi.Config{AgentDirectory: s.cfg.PiAgentDir, Provider: provider, ModelID: modelID, LifecycleRevision: t.LifecycleRevision, Binary: s.cfg.PiBinary, Directory: directory, Restricted: t.PlanningProfile == core.RestrictedPlanning, SessionDirectory: sessionDirectory, SessionID: ref.ID, SessionFile: sessionFile, Extension: s.cfg.PiExtension, HostURL: s.cfg.InternalURL, Token: s.scopedToken(taskID, role), TaskID: taskID, Role: role, ExcludeEnv: s.controlEnv(), OnEvent: func(raw json.RawMessage) { s.piEvent(taskID, role, processID, raw) }})
	if err != nil {
		return nil, err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	data, err := c.Call(ctx, "get_state", nil)
	if err != nil {
		_ = c.Close()
		return nil, err
	}
	var native struct {
		SessionID    string   `json:"sessionId"`
		SessionFile  string   `json:"sessionFile"`
		IsStreaming  bool     `json:"isStreaming"`
		IsCompacting bool     `json:"isCompacting"`
		Model        *piModel `json:"model"`
	}
	if err = json.Unmarshal(data, &native); err != nil {
		_ = c.Close()
		return nil, err
	}
	if native.SessionID == "" || native.SessionID != ref.ID {
		_ = c.Close()
		return nil, fmt.Errorf("Pi get_state missing native sessionId")
	}
	confirmed := nativeModelRef(native.Model)
	if requestedModel != nil && !modelRefsEqual(requestedModel, confirmed) {
		_ = c.Close()
		return nil, fail("needs_model_selection", "Pi did not select the exact requested default model", 409)
	}
	modelStatus := "ready"
	if s.allowedNativeModel(native.Model) != nil || (resuming && ref.Model != nil && !modelRefsEqual(ref.Model, confirmed)) {
		modelStatus = "needs_model_selection"
	}
	availableData, availableErr := c.Call(ctx, "get_available_models", nil)
	var available struct {
		Models []piModel `json:"models"`
	}
	found := false
	if availableErr == nil && json.Unmarshal(availableData, &available) == nil {
		for _, entry := range available.Models {
			if modelRefsEqual(confirmed, nativeModelRef(&entry)) {
				found = true
				break
			}
		}
	}
	if !found {
		modelStatus = "needs_model_selection"
	}
	if requestedModel != nil && modelStatus != "ready" {
		_ = c.Close()
		return nil, fail("needs_model_selection", "the requested default model is unavailable in native Pi", 409)
	}
	err = s.store.Update(func(st *core.State) error {
		t := st.Tasks[taskID]
		current := t.Sessions[role]
		current.ProcessID = processID
		current.ID = native.SessionID
		current.File = native.SessionFile
		current.Available = true
		current.Busy = native.IsStreaming || native.IsCompacting
		current.Streaming = native.IsStreaming
		current.Compacting = native.IsCompacting
		// An unbound old session can adopt only its explicit verified native
		// value. A previously bound session never adopts a fallback silently.
		if current.Model == nil || !resuming {
			current.Model = confirmed
		}
		current.ModelStatus = modelStatus
		refreshPending(current)
		core.Changed(st, t)
		return nil
	})
	if err != nil {
		_ = c.Close()
		return nil, err
	}
	s.mu.Lock()
	if s.closing {
		s.mu.Unlock()
		_ = c.Close()
		return nil, fmt.Errorf("Host is closing")
	}
	s.clients[key] = c
	s.mu.Unlock()
	return c, nil
}
func (s *Server) piEvent(taskID, role, processID string, raw json.RawMessage) {
	var event struct {
		Type     string   `json:"type"`
		Reason   string   `json:"reason"`
		Aborted  bool     `json:"aborted"`
		ID       string   `json:"id"`
		Method   string   `json:"method"`
		Steering []string `json:"steering"`
		FollowUp []string `json:"followUp"`
		Timeout  *int64   `json:"timeout"`
	}
	if json.Unmarshal(raw, &event) != nil {
		return
	}
	switch event.Type {
	case "agent_start", "agent_settled", "message_end", "extension_ui_request", "awf_process_exit", "awf_process_closed", "queue_update", "compaction_start", "compaction_end":
	default:
		s.store.NativeEvent(taskID, role, processID, map[string]any{"role": role, "event": json.RawMessage(raw)})
		return
	}
	_ = s.store.Update(func(st *core.State) error {
		t := st.Tasks[taskID]
		if t == nil || t.DeletedAt != nil {
			return nil
		}
		ref := t.Sessions[role]
		if ref == nil || ref.ProcessID != processID {
			return nil
		}
		ref.Available = true
		switch event.Type {
		case "agent_start":
			ref.Streaming = true
			ref.Busy = true
			ref.AwaitingStart = false
			refreshPending(ref)
			if t.Budget.ActiveSince == nil {
				now := time.Now().UTC()
				t.Budget.ActiveSince = &now
			}
		case "awf_process_exit", "awf_process_closed":
			ref.Available = false
			ref.PendingCommands = nil
			ref.NativeQueued = 0
			ref.AwaitingStart = false
			rebuildPiControlFence(st, taskID, role, ref)
			ref.Busy = false
			ref.Streaming = false
			ref.Compacting = false
			ref.PendingUI = nil
			ref.DialogDeadlines = nil
			s.chargePi(t)
			if event.Type == "awf_process_exit" {
				t.LastError = "Native Pi process exited; any in-flight prompt requires verification"
			}
		case "message_end":
			if ref.File != "" {
				if _, err := os.Stat(ref.File); err == nil {
					ref.Persisted = true
				}
			}
		case "compaction_start":
			ref.Compacting = true
			ref.Busy = true
			if t.Budget.ActiveSince == nil {
				now := time.Now().UTC()
				t.Budget.ActiveSince = &now
			}
		case "compaction_end":
			if event.Reason == "manual" && event.Aborted {
				for _, requestID := range append([]string(nil), ref.PendingCommands...) {
					request := st.Requests[requestID]
					if request != nil && request.Operation == "pi/compact" && request.ProcessID == processID && (request.Status == "accepted" || request.Status == "needs_verification") {
						request.Status = "cancelled"
						request.Error = "Pi compaction was stopped"
						settleCommand(ref, requestID)
					}
				}
			}
			ref.Compacting = false
			ref.Busy = ref.Streaming
			if !ref.Busy {
				s.chargePi(t)
			}
		case "queue_update":
			ref.NativeQueued = len(event.Steering) + len(event.FollowUp)
			refreshPending(ref)
		case "agent_settled":
			ref.Settled++
			for _, request := range st.Requests {
				if request.TaskID == taskID && request.Role == role && request.SessionID == ref.ID && request.ProcessID == processID && request.Status == "accepted_native" && nativePromptOperation(request.Operation) {
					request.Status = "settled"
				}
			}
			ref.AwaitingStart = false
			refreshPending(ref)
			ref.PendingUI = nil
			ref.DialogDeadlines = nil
			ref.Streaming = false
			ref.Busy = ref.Compacting
			if !ref.Busy {
				s.chargePi(t)
			}
		case "extension_ui_request":
			switch event.Method {
			case "confirm", "input", "select", "editor":
				ref.PendingUI = append(ref.PendingUI, raw)
				if event.Timeout != nil && *event.Timeout >= 0 {
					if ref.DialogDeadlines == nil {
						ref.DialogDeadlines = map[string]time.Time{}
					}
					ref.DialogDeadlines[event.ID] = time.Now().Add(time.Duration(*event.Timeout) * time.Millisecond)
				}
				s.chargePi(t)
			}
		}
		core.Emit(st, taskID, "pi.event", map[string]any{"role": role, "event": json.RawMessage(raw)})
		core.Changed(st, t)
		return nil
	})
	if event.Type == "extension_ui_request" && event.Timeout != nil && *event.Timeout >= 0 {
		delay := time.Duration(*event.Timeout) * time.Millisecond
		s.launch(func() { s.expireDialog(taskID, role, processID, event.ID, delay) })
	}
	if event.Type == "agent_settled" && role == "architect" {
		if t, err := s.task(taskID); err == nil && t.DeletedAt == nil && t.Execution != nil && t.Execution.Status == "completed" && (t.Status == "review" || t.Status == "reporting") {
			s.launch(func() { s.beginExecutionSummary(taskID) })
		}
	}
}
func (s *Server) chargePi(t *core.Task) {
	if t.Budget.ActiveSince != nil {
		elapsed := int64(time.Since(*t.Budget.ActiveSince).Seconds())
		if elapsed > 0 {
			t.Budget.TaskSeconds += elapsed
			t.Budget.PlanSeconds += elapsed
		}
		t.Budget.ActiveSince = nil
	}
}

func (s *Server) prompt(requestID, taskID, role, text string) {
	lock := s.piDispatchLock(taskID, role)
	lock.Lock()
	if receipt := s.store.Snapshot().Requests[requestID]; receipt != nil && receipt.Operation == "execution_result" && receipt.Status == "cancelled" {
		lock.Unlock()
		return
	}
	if s.restoreCancelledPrompt(requestID, taskID, role, text) {
		lock.Unlock()
		return
	}
	saved := s.store.Snapshot().Requests[requestID]
	var c *pi.Client
	var err error
	if saved != nil && saved.SessionID != "" && saved.ProcessID != "" {
		c, err = s.boundPiClient(taskID, piBinding{role, saved.SessionID, saved.ProcessID})
	} else {
		c, err = s.client(taskID, role)
	}
	var binding piBinding
	var startSettled int64
	var pending *pi.PendingCall
	if err == nil {
		task, _ := s.task(taskID)
		if task.Sessions[role].ModelStatus != "ready" {
			err = fail("needs_model_selection", "select an allowed idle model before generating", 409)
		} else {
			err = s.verifyPiGeneration(c, task.Sessions[role])
		}
	}
	if err == nil {
		err = s.store.Update(func(st *core.State) error {
			t := st.Tasks[taskID]
			ref := t.Sessions[role]
			req := st.Requests[requestID]
			if req == nil || req.Status != "accepted" {
				return fail("prompt_cancelled", "prompt is no longer pending", 409)
			}
			if pendingPiControl(st, taskID, role) {
				return fail("pi_control_pending", "Pi control has fenced this prompt", 409)
			}
			if req.SessionID != "" && (req.SessionID != ref.ID || req.ProcessID != "" && !bindingMatches(ref, piBinding{role, req.SessionID, req.ProcessID})) {
				return fail("stale_pi_session", "Pi session changed before message dispatch", 409)
			}
			if req.Operation == "execution_result" {
				if t.DeletedAt != nil || t.Execution == nil || !resultTerminal(t) || t.Status != "reporting" || t.Execution.ResultReview == nil || t.Execution.ResultReview.RequestID != requestID || remainingSeconds(t) <= 0 {
					return fail("result_unavailable", "result review binding or budget changed before dispatch", 409)
				}
			}
			binding = piBinding{role, ref.ID, ref.ProcessID}
			startSettled = ref.Settled
			req.Role = role
			req.SessionID = ref.ID
			req.ProcessID = ref.ProcessID
			req.Dispatched = true
			return nil
		})
	}
	if err == nil {
		pending, err = s.fencedPiBegin(c, "prompt", map[string]any{"message": text, "streamingBehavior": "followUp"})
	}
	lock.Unlock()
	if err != nil {
		_ = s.store.Update(func(st *core.State) error {
			t := st.Tasks[taskID]
			req := st.Requests[requestID]
			if req == nil || req.Status == "cancelled" || req.Operation == "execution_result" && req.Status == "completed" {
				return nil
			}
			req.Status = "failed"
			if req.Dispatched {
				req.Status = "needs_verification"
			}
			req.Error = "Pi did not confirm this message; its original request identity is retained"
			if t != nil && t.Sessions[role] != nil {
				settleCommand(t.Sessions[role], requestID)
				core.Changed(st, t)
			}
			return nil
		})
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	data, err := pending.Wait(ctx)
	if err != nil {
		s.requestDone(requestID, "needs_verification", fmt.Errorf("Pi did not confirm the message; inspect its original receipt"))
		return
	}
	var result struct {
		Disposition string `json:"disposition"`
	}
	_ = json.Unmarshal(data, &result)
	s.requestDone(requestID, "accepted_native", nil)
	ctxState, cancelState := context.WithTimeout(context.Background(), 10*time.Second)
	state, stateErr := c.Call(ctxState, "get_state", nil)
	cancelState()
	_ = s.store.Update(func(st *core.State) error {
		t := st.Tasks[taskID]
		ref := t.Sessions[role]
		if !bindingMatches(ref, binding) {
			return nil
		}
		settleCommand(ref, requestID)
		if stateErr == nil {
			var native struct {
				IsStreaming         bool `json:"isStreaming"`
				IsCompacting        bool `json:"isCompacting"`
				PendingMessageCount int  `json:"pendingMessageCount"`
			}
			_ = json.Unmarshal(state, &native)
			ref.Streaming = native.IsStreaming
			ref.Compacting = native.IsCompacting
			ref.Busy = native.IsStreaming || native.IsCompacting
			ref.NativeQueued = native.PendingMessageCount
			if result.Disposition == "started" && !ref.Busy && ref.NativeQueued == 0 && ref.Settled <= startSettled {
				ref.AwaitingStart = true
			}
			if result.Disposition == "handled" && !ref.Busy {
				s.chargePi(t)
			}
		} else {
			ref.AwaitingStart = true
		}
		refreshPending(ref)
		if !ref.Busy && !ref.Pending {
			if req := st.Requests[requestID]; req != nil && !(req.Operation == "execution_result" && req.Status == "completed") {
				req.Status = "settled"
			}
		}
		core.Changed(st, t)
		return nil
	})

	s.launch(func() { s.watchPiBudget(taskID, role, c) })
}
func (s *Server) watchPiBudget(taskID, role string, c *pi.Client) {
	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-s.stop:
			return
		case <-ticker.C:
		}
		t, err := s.task(taskID)
		if err != nil || t.DeletedAt != nil || !c.Alive() {
			return
		}
		ref := t.Sessions[role]
		if ref == nil || (!ref.Busy && !ref.Pending) {
			return
		}
		_ = s.store.Update(func(st *core.State) error {
			t := st.Tasks[taskID]
			if t.Budget.ActiveSince != nil {
				elapsed := int64(time.Since(*t.Budget.ActiveSince).Seconds())
				if elapsed > 0 {
					t.Budget.TaskSeconds += elapsed
					t.Budget.PlanSeconds += elapsed
					next := t.Budget.ActiveSince.Add(time.Duration(elapsed) * time.Second)
					t.Budget.ActiveSince = &next
				}
			}
			return nil
		})
		t, _ = s.task(taskID)
		seconds := t.Budget.TaskSeconds
		if t.Budget.ActiveSince != nil {
			seconds += int64(time.Since(*t.Budget.ActiveSince).Seconds())
		}
		if seconds >= int64(t.Settings.TaskMinutes*60) || t.Budget.PlanSeconds >= int64(t.Settings.PlanMinutes*60) {
			ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
			err = s.fencedPiStop(ctx, c)
			cancel()
			s.stopForBudget(taskID)
			_ = s.store.Update(func(st *core.State) error {
				t := st.Tasks[taskID]
				s.chargePi(t)
				t.Status = "blocked"
				t.LastError = "Execution budget exhausted"
				if err != nil {
					t.LastError += "; native Pi stop not confirmed: " + err.Error()
				}
				core.Changed(st, t)
				return nil
			})
			return
		}
	}
}

func (s *Server) controlEnv() []string {
	names := []string{s.cfg.TokenEnv, s.cfg.ExtensionTokenEnv}
	for _, n := range s.cfg.Nodes {
		names = append(names, n.TokenEnv)
	}
	return names
}

func (s *Server) expireDialog(taskID, role, processID, id string, delay time.Duration) {
	timer := time.NewTimer(delay)
	defer timer.Stop()
	select {
	case <-s.stop:
		return
	case <-timer.C:
	}
	expired := false
	_ = s.store.Update(func(st *core.State) error {
		t := st.Tasks[taskID]
		ref := t.Sessions[role]
		if ref.ProcessID != processID {
			return nil
		}
		deadline, ok := ref.DialogDeadlines[id]
		if !ok || time.Now().Before(deadline) {
			return nil
		}
		filtered := []json.RawMessage{}
		for _, raw := range ref.PendingUI {
			var v struct {
				ID string `json:"id"`
			}
			_ = json.Unmarshal(raw, &v)
			if v.ID != id {
				filtered = append(filtered, raw)
			}
		}
		ref.PendingUI = filtered
		delete(ref.DialogDeadlines, id)
		if ref.Busy && len(ref.PendingUI) == 0 {
			now := time.Now().UTC()
			t.Budget.ActiveSince = &now
		}
		expired = true
		core.Changed(st, t)
		return nil
	})
	if expired {
		s.mu.Lock()
		c := s.clients[taskID+":"+role]
		s.mu.Unlock()
		if c != nil {
			c.ForgetUI(id)
		}
	}
}

// Legacy tasks retain their explicit project cwd. New tasks never inherit the
// Host cwd or acquire filesystem tools merely by selecting an execution target.
func (s *Server) planningDirectory(t *core.Task) (string, error) {
	switch t.PlanningProfile {
	case "":
		dir := s.cfg.Projects[t.ProjectID]
		if dir == "" {
			return "", fail("project_unavailable", "legacy planning workspace is not configured", 409)
		}
		return dir, nil
	case core.RestrictedPlanning:
		if !requestPattern.MatchString(t.ID) || t.ID == "." || t.ID == ".." {
			return "", fail("invalid_task", "invalid managed task identity", 409)
		}
		base, err := filepath.Abs(s.cfg.DataDir)
		if err != nil {
			return "", err
		}
		dir := filepath.Join(base, "planning", t.ID)
		if err := os.MkdirAll(dir, 0700); err != nil {
			return "", err
		}
		info, err := os.Lstat(dir)
		if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return "", fail("planning_unavailable", "managed planning directory is unavailable", 409)
		}
		return dir, nil
	default:
		return "", fail("planning_unavailable", "unsupported planning profile", 409)
	}
}
