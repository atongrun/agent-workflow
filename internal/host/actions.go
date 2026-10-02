package host

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
	"github.com/atongrun/agent-workflow/internal/node"
)

type actionInput struct {
	ExpectedTargetRevision *int           `json:"expectedTargetRevision,omitempty"`
	ExecutionRequestID     string         `json:"executionRequestId,omitempty"`
	RequestID              string         `json:"requestId"`
	Role                   string         `json:"role,omitempty"`
	Text                   string         `json:"text,omitempty"`
	Revision               int            `json:"revision,omitempty"`
	Response               map[string]any `json:"response,omitempty"`
	ExpectedSessionID      string         `json:"expectedSessionId,omitempty"`
	ExpectedProcessID      string         `json:"expectedProcessId,omitempty"`
}

func (s *Server) action(w http.ResponseWriter, r *http.Request) {
	var in actionInput
	if err := decode(w, r, &in); err != nil {
		writeError(w, err)
		return
	}
	id := r.PathValue("id")
	op := strings.TrimPrefix(r.URL.Path, "/v1/tasks/"+id+"/")
	if in.Role == "" {
		in.Role = "architect"
	}
	if in.Role != "architect" && in.Role != "reviewer" {
		writeError(w, fail("invalid_role", "role must be architect or reviewer", 400))
		return
	}
	duplicate, err := s.reserveRequest(in.RequestID, id, op, in, func(st *core.State, req *core.Request) error {
		t := st.Tasks[id]
		if t == nil {
			return fail("not_found", "task not found", 404)
		}
		if op == "execution/cancel" || op == "review" || op == "rework" {
			if t.Execution == nil || in.ExecutionRequestID == "" || in.ExecutionRequestID != t.Execution.RequestID {
				return fail("stale_execution", "executionRequestId must match the intended current run", 409)
			}
		}
		switch op {
		case "messages":
			if strings.TrimSpace(in.Text) == "" {
				return fail("empty_message", "text is required", 400)
			}
			if t.Sessions[in.Role] == nil {
				return fail("session_unavailable", "role session does not exist", 409)
			}
			ref := t.Sessions[in.Role]
			if pendingPiControl(st, ref) {
				return fail("pi_control_pending", "wait for the Pi control receipt before sending another message", 409)
			}
			if in.ExpectedSessionID != "" || in.ExpectedProcessID != "" {
				if in.ExpectedSessionID == "" || in.ExpectedProcessID == "" || !ref.Available || !bindingMatches(ref, piBinding{in.Role, in.ExpectedSessionID, in.ExpectedProcessID}) {
					return fail("stale_pi_session", "Pi session changed; refresh and select the command again", 409)
				}
				req.SessionID = ref.ID
				req.ProcessID = ref.ProcessID
			}
			req.Role = in.Role
			for role, ref := range t.Sessions {
				if role != in.Role && (ref.Busy || ref.Pending) {
					return fail("role_busy", "another Pi role is generating for this task", 409)
				}
			}
			if t.PlanningProfile != core.RestrictedPlanning {
				if err := projectAvailable(st, t); err != nil {
					return err
				}
			}
			if remainingSeconds(t) <= 0 {
				return fail("budget_exhausted", "task budget exhausted", 409)
			}
			if t.Status == "created" {
				t.Status = "planning"
			}
			t.Sessions[in.Role].PendingCommands = append(t.Sessions[in.Role].PendingCommands, in.RequestID)
			refreshPending(t.Sessions[in.Role])
		case "pi/abort", "pi/ui-response":
			if t.Sessions[in.Role] == nil || !t.Sessions[in.Role].Available {
				return fail("session_unavailable", "role session is not running", 409)
			}
			if op == "pi/ui-response" {
				if err := validateUIResponse(t.Sessions[in.Role], in.Response); err != nil {
					return err
				}
				ref := t.Sessions[in.Role]
				filtered := []json.RawMessage{}
				for _, raw := range ref.PendingUI {
					var pending struct {
						ID string `json:"id"`
					}
					_ = json.Unmarshal(raw, &pending)
					if pending.ID != in.Response["id"] {
						filtered = append(filtered, raw)
					}
				}
				ref.PendingUI = filtered
				delete(ref.DialogDeadlines, in.Response["id"].(string))
			}
		case "plan/confirm":
			if t.Plan == nil || t.Plan.Revision != in.Revision {
				return fail("plan_changed", "confirm the current plan revision", 409)
			}
			if executionActive(t) {
				return fail("execution_active", "cannot confirm a new plan during execution", 409)
			}
			now := time.Now().UTC()
			t.Plan.ConfirmedAt = &now
			t.Status = "ready"
			if t.Execution != nil && needsRework(t) {
				t.Status = "needs_changes"
			}
		case "start", "rework":
			if err := s.prepareExecution(st, t, in.RequestID, in.Revision, op == "rework", in.ExpectedTargetRevision); err != nil {
				return err
			}
		case "execution/cancel":
			if t.Execution == nil || !executionActive(t) {
				return fail("no_execution", "no active execution to cancel", 409)
			}
			t.Execution.CancelRequested = true
			t.Execution.Status = "cancelling"
		case "review":
			if t.Settings.Reviewer != "pi" {
				return fail("review_disabled", "this task uses the same Pi for planning and execution results", 409)
			}
			if ref := t.Sessions["architect"]; ref != nil && (ref.Busy || ref.Pending) {
				return fail("role_busy", "architect generation must settle before independent review", 409)
			}
			if remainingSeconds(t) <= 0 {
				return fail("budget_exhausted", "review budget exhausted", 409)
			}
			if t.Execution == nil || t.Execution.Status != "completed" {
				return fail("execution_not_complete", "native execution must complete before review", 409)
			}
			for _, review := range t.ReviewHistory {
				if review.ExecutionRequestID == t.Execution.RequestID {
					return fail("review_closed", "this execution already has a review verdict", 409)
				}
			}
			for _, req := range st.Requests {
				if req.TaskID == id && (req.Operation == "auto_review" || req.Operation == "review") && (req.Status == "accepted" || req.Status == "accepted_native" || req.Status == "needs_verification") {
					return fail("review_active", "review is already active or needs verification", 409)
				}
			}
			prepareReviewer(t, in.RequestID)
		default:
			return fail("not_found", "unknown action", 404)
		}
		core.Changed(st, t)
		return nil
	})
	if err != nil {
		writeError(w, err)
		return
	}
	if !duplicate {
		switch op {
		case "messages":
			s.launch(func() { s.prompt(in.RequestID, id, in.Role, in.Text) })
		case "pi/abort":
			s.launch(func() { s.abortPi(in.RequestID, id, in.Role) })
		case "pi/ui-response":
			s.launch(func() { s.respondUI(in.RequestID, id, in.Role, in.Response) })
		case "plan/confirm":
			s.requestDone(in.RequestID, "completed", nil)
		case "start", "rework":
			s.monitor(id)
		case "execution/cancel":
			s.launch(func() { s.cancelExecution(in.RequestID, id, in.ExecutionRequestID) })
		case "review":
			s.launch(func() { s.promptReview(in.RequestID, id) })
		}
	}
	s.response(w, in.RequestID)
}
func executionActive(t *core.Task) bool {
	if t.Execution == nil {
		return false
	}
	switch t.Execution.Status {
	case "completed", "failed", "cancelled":
		return false
	}
	return true
}
func (s *Server) prepareExecution(st *core.State, t *core.Task, requestID string, revision int, rework bool, expectedTargetRevision *int) error {
	if err := projectAvailable(st, t); err != nil {
		return err
	}
	if t.Plan == nil || t.Plan.Revision != revision || t.Plan.ConfirmedAt == nil {
		return fail("plan_unconfirmed", "current plan must be explicitly confirmed", 409)
	}
	if executionActive(t) {
		return fail("execution_active", "execution already active", 409)
	}
	if (t.PlanningProfile == core.RestrictedPlanning && t.TargetRevision == 0) || ((t.PlanningProfile == core.RestrictedPlanning || t.TargetRevision > 0) && expectedTargetRevision == nil) {
		return fail("target_required", "bind an execution target and explicitly start its current revision", 409)
	}
	if expectedTargetRevision != nil && *expectedTargetRevision != t.TargetRevision {
		return fail("target_changed", "start must match the current execution target revision", 409)
	}
	if !taskPiIdle(t) {
		return fail("role_busy", "wait for Pi and its pending dialogs to settle before starting execution", 409)
	}
	if err := s.validateTarget(t); err != nil {
		return err
	}

	if rework {
		if !needsRework(t) {
			return fail("rework_unavailable", "Pi must report changes needed before rework", 409)
		}
		if t.Budget.Reworks >= t.Settings.MaxReworks {
			return fail("rework_limit", "rework budget exhausted", 409)
		}
	} else if t.Execution != nil {
		return fail("use_rework", "existing execution requires an explicit rework", 409)
	}
	if t.Budget.TaskSeconds >= int64(t.Settings.TaskMinutes*60) || t.Budget.PlanSeconds >= int64(t.Settings.PlanMinutes*60) {
		return fail("budget_exhausted", "execution budget exhausted", 409)
	}
	for _, other := range st.Tasks {
		if other.ID != t.ID && other.ProjectID == t.ProjectID && (executionActive(other) || (other.Status == "review" || other.Status == "reporting")) {
			return fail("project_busy", "another task owns this project's execution slot", 409)
		}
	}
	previousSession := ""
	if t.Execution != nil {
		previousSession = t.Execution.SessionID
	}
	if rework {
		t.ExecutionHistory = append(t.ExecutionHistory, *t.Execution)
		t.Budget.Reworks++
	}
	t.Execution = &core.Execution{Target: &core.ExecutionTarget{Revision: t.TargetRevision, ProjectID: t.ProjectID, NodeID: t.NodeID, Repository: t.Repository, RepositoryID: t.RepositoryID}, RequestID: requestID, JobID: node.JobID(requestID), SessionID: previousSession, OriginalSessionID: previousSession, TimeoutSeconds: remainingSeconds(t), Status: "queued", Evidence: []core.Evidence{}}
	t.Status = "queued"
	t.Phase = "execution"
	return nil
}
func prepareReviewer(t *core.Task, requestID string) {
	if t.Sessions["reviewer"] == nil {
		t.Sessions["reviewer"] = &core.Session{ID: core.ID(), PendingUI: []json.RawMessage{}}
	}
	t.Status = "review"
	t.Phase = "review"
	t.Sessions["reviewer"].PendingCommands = append(t.Sessions["reviewer"].PendingCommands, requestID)
	refreshPending(t.Sessions["reviewer"])
}
func (s *Server) abortPi(requestID, taskID, role string) {
	s.mu.Lock()
	c := s.clients[taskID+":"+role]
	s.mu.Unlock()
	if c == nil {
		s.requestDone(requestID, "failed", fmt.Errorf("native session is no longer running"))
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	err := c.Stop(ctx)
	if err != nil {
		s.requestDone(requestID, "needs_verification", err)
		return
	}
	_ = s.store.Update(func(st *core.State) error {
		t := st.Tasks[taskID]
		t.Sessions[role].PendingUI = []json.RawMessage{}
		s.chargePi(t)
		core.Changed(st, t)
		return nil
	})
	s.requestDone(requestID, "accepted_native", nil)
}
func validateUIResponse(ref *core.Session, response map[string]any) error {
	id, ok := response["id"].(string)
	if !ok || id == "" {
		return fail("invalid_ui_response", "native dialog id required", 400)
	}
	if deadline, ok := ref.DialogDeadlines[id]; ok && !time.Now().Before(deadline) {
		return fail("dialog_expired", "native dialog timed out", 409)
	}
	for key := range response {
		if key != "id" && key != "value" && key != "confirmed" && key != "cancelled" {
			return fail("invalid_ui_response", "unsupported native response field", 400)
		}
	}
	if v, ok := response["cancelled"]; ok {
		if v != true || len(response) != 2 {
			return fail("invalid_ui_response", "cancelled must be true and exclusive", 400)
		}
	}
	for _, raw := range ref.PendingUI {
		var dialog struct {
			ID      string   `json:"id"`
			Method  string   `json:"method"`
			Options []string `json:"options"`
		}
		_ = json.Unmarshal(raw, &dialog)
		if dialog.ID != id {
			continue
		}
		if response["cancelled"] == true {
			return nil
		}
		switch dialog.Method {
		case "confirm":
			if _, ok := response["confirmed"].(bool); !ok || len(response) != 2 {
				return fail("invalid_ui_response", "confirm requires an explicit confirmed boolean", 400)
			}
		case "select", "input", "editor":
			v, ok := response["value"].(string)
			if !ok || len(response) != 2 {
				return fail("invalid_ui_response", "dialog requires a string value", 400)
			}
			if dialog.Method == "select" {
				found := false
				for _, choice := range dialog.Options {
					if choice == v {
						found = true
					}
				}
				if !found {
					return fail("invalid_ui_response", "selection is not a native option", 400)
				}
			}
		default:
			return fail("invalid_ui_response", "unsupported native dialog", 400)
		}
		return nil
	}
	return fail("dialog_expired", "native dialog is no longer pending", 409)
}
func (s *Server) respondUI(requestID, taskID, role string, response map[string]any) {
	s.mu.Lock()
	c := s.clients[taskID+":"+role]
	s.mu.Unlock()
	if c == nil {
		s.requestDone(requestID, "failed", fmt.Errorf("native session is no longer running"))
		return
	}
	id, _ := response["id"].(string)
	if err := c.Respond(id, response); err != nil {
		s.requestDone(requestID, "needs_verification", err)
		return
	}
	_ = s.store.Update(func(st *core.State) error {
		t := st.Tasks[taskID]
		ref := t.Sessions[role]
		remaining := []json.RawMessage{}
		for _, raw := range ref.PendingUI {
			var v struct {
				ID string `json:"id"`
			}
			_ = json.Unmarshal(raw, &v)
			if v.ID != id {
				remaining = append(remaining, raw)
			}
		}
		ref.PendingUI = remaining
		if ref.Busy && len(ref.PendingUI) == 0 {
			now := time.Now().UTC()
			t.Budget.ActiveSince = &now
		}
		core.Changed(st, t)
		return nil
	})
	s.requestDone(requestID, "sent_native", nil)
}
func (s *Server) promptReview(requestID, id string) {
	t, err := s.task(id)
	if err != nil {
		return
	}
	payload := map[string]any{"task": t.Title, "goal": t.Goal, "acceptanceCriteria": t.AcceptanceCriteria, "plan": t.Plan, "execution": t.Execution, "branch": t.Branch}
	s.prompt(requestID, id, "reviewer", "Independently review this execution against the confirmed plan and real native evidence. You are the reviewer, separate from the architect. Do not claim evidence absent from native results. Use awf_review to submit approved or needs_changes and concrete findings. An approved review must cite inspected artifacts/test evidence. All Git work, if needed, is your own tool work; the Host never performs Git.\n"+string(mustJSON(payload)))
}

func remainingSeconds(t *core.Task) int {
	used := t.Budget.TaskSeconds
	plan := t.Budget.PlanSeconds
	if t.Budget.ActiveSince != nil {
		delta := int64(time.Since(*t.Budget.ActiveSince).Seconds())
		used += delta
		plan += delta
	}
	left := int64(t.Settings.TaskMinutes*60) - used
	if n := int64(t.Settings.PlanMinutes*60) - plan; n < left {
		left = n
	}
	return int(left)
}
func projectAvailable(st *core.State, t *core.Task) error {
	for _, other := range st.Tasks {
		if other.ID == t.ID || other.ProjectID != t.ProjectID {
			continue
		}
		if executionActive(other) || (other.Status == "review" || other.Status == "reporting") {
			return fail("project_busy", "another task owns this project", 409)
		}
		if other.PlanningProfile == core.RestrictedPlanning {
			continue
		}
		for _, ref := range other.Sessions {
			if ref.Busy || ref.Pending {
				return fail("project_busy", "another task has active native Pi work in this project", 409)
			}
		}
	}
	return nil
}

func (s *Server) stopForBudget(id string) {
	t, err := s.task(id)
	if err != nil {
		return
	}
	for role, ref := range t.Sessions {
		if ref.Busy {
			role := role
			s.launch(func() { s.abortPi("", id, role) })
		}
	}
	if executionActive(t) {
		_ = s.store.Update(func(st *core.State) error {
			st.Tasks[id].Execution.CancelRequested = true
			st.Tasks[id].LastError = "Combined execution budget exhausted"
			return nil
		})
		s.launch(func() { s.cancelExecution("budget-"+t.Execution.RequestID, id, t.Execution.RequestID) })
	}
}

func refreshPending(ref *core.Session) {
	ref.Pending = len(ref.PendingCommands) > 0 || ref.NativeQueued > 0 || ref.AwaitingStart
}
func settleCommand(ref *core.Session, id string) {
	remaining := []string{}
	for _, key := range ref.PendingCommands {
		if key != id {
			remaining = append(remaining, key)
		}
	}
	ref.PendingCommands = remaining
	refreshPending(ref)
}

func needsRework(t *core.Task) bool {
	if t.Execution == nil {
		return false
	}
	if t.Settings.Reviewer != "pi" {
		return t.Completion != nil && t.Completion.Verdict == "needs_changes" && t.Completion.ExecutionRequestID == t.Execution.RequestID
	}
	if len(t.ReviewHistory) == 0 {
		return false
	}
	last := t.ReviewHistory[len(t.ReviewHistory)-1]
	return last.Verdict == "needs_changes" && last.ExecutionRequestID == t.Execution.RequestID
}
