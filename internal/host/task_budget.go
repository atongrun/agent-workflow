package host

import (
	"net/http"

	"github.com/atongrun/agent-workflow/internal/core"
)

type budgetInput struct {
	RequestID              string `json:"requestId"`
	ExpectedBudgetRevision *int   `json:"expectedBudgetRevision"`
	TaskMinutes            *int   `json:"taskMinutes,omitempty"`
	MaxReworks             *int   `json:"maxReworks,omitempty"`
}

// Limits are totals, not new allowances. Only settled tasks may tighten them;
// counters, native waits, history and execution fingerprints remain intact.
func (s *Server) updateBudget(w http.ResponseWriter, r *http.Request) {
	if len(r.URL.Query()) != 0 {
		writeError(w, fail("invalid_query", "budget changes do not accept query parameters", 400))
		return
	}
	var in budgetInput
	if err := decode(w, r, &in); err != nil {
		writeError(w, err)
		return
	}
	id := r.PathValue("id")
	s.piLifecycle.Lock()
	defer s.piLifecycle.Unlock()
	_, err := s.reserveRequest(in.RequestID, id, "budget", in, func(st *core.State, req *core.Request) error {
		t := st.Tasks[id]
		if t == nil {
			return fail("not_found", "task not found", 404)
		}
		if in.ExpectedBudgetRevision == nil || *in.ExpectedBudgetRevision != t.BudgetRevision {
			return fail("budget_changed", "reload the current budget revision before saving", 409)
		}
		if in.TaskMinutes == nil && in.MaxReworks == nil || in.TaskMinutes != nil && *in.TaskMinutes < 1 || in.MaxReworks != nil && *in.MaxReworks < 0 {
			return fail("invalid_budget", "supply taskMinutes >= 1 or maxReworks >= 0", 400)
		}
		minutes, reworks := t.Settings.TaskMinutes, t.Settings.MaxReworks
		if in.TaskMinutes != nil {
			minutes = *in.TaskMinutes
		}
		if in.MaxReworks != nil {
			reworks = *in.MaxReworks
		}
		if minutes > t.Settings.TaskMinutes || reworks > t.Settings.MaxReworks {
			return fail("budget_increase", "task budget limits may only decrease", 409)
		}
		if minutes == t.Settings.TaskMinutes && reworks == t.Settings.MaxReworks {
			return fail("budget_unchanged", "at least one budget limit must decrease", 409)
		}
		// Status checks also fence result reporting after a terminal native job.
		if executionActive(t) || !budgetTaskSettled(t.Status) {
			return fail("execution_active", "wait for execution and reporting to settle before tightening the budget", 409)
		}
		if !taskPiIdle(t) || t.Budget.ActiveSince != nil {
			return fail("role_busy", "wait for Pi, queued work and pending dialogs to settle", 409)
		}
		if !budgetRequestsSettled(st, id) {
			return fail("task_needs_verification", "settle pending or uncertain request receipts before tightening the budget", 409)
		}
		if t.Execution != nil && (len(t.Execution.PendingPermissions) > 0 || len(t.Execution.PendingQuestions) > 0) {
			return fail("execution_active", "settle native permissions and questions before tightening the budget", 409)
		}
		before := map[string]int{"taskMinutes": t.Settings.TaskMinutes, "maxReworks": t.Settings.MaxReworks}
		t.Settings.TaskMinutes, t.Settings.MaxReworks = minutes, reworks
		t.BudgetRevision++
		req.Status = "completed"
		req.Result = mustJSON(map[string]any{"budgetRevision": t.BudgetRevision, "before": before, "after": map[string]int{"taskMinutes": minutes, "maxReworks": reworks}})
		core.Emit(st, id, "budget.tightened", map[string]any{"requestId": in.RequestID, "change": req.Result})
		core.Changed(st, t)
		return nil
	})
	if err != nil {
		writeError(w, err)
		return
	}
	s.response(w, in.RequestID)
}

// Unknown persisted/future statuses cannot prove that a task has settled.
func budgetTaskSettled(status string) bool {
	switch status {
	case "created", "planning", "awaiting_confirmation", "ready", "needs_changes", "blocked", "cancelled", "done":
		return true
	}
	return false
}

func budgetRequestsSettled(st *core.State, id string) bool {
	for _, req := range st.Requests {
		if req.TaskID != id {
			continue
		}
		switch req.Status {
		case "completed", "failed", "cancelled", "settled":
			continue
		case "sent_native":
			if req.Operation == "pi/ui-response" {
				continue
			}
		case "accepted_native":
			// These receipts use the already-checked job/session idle boundary.
			// Prompts still require a settled receipt; unknown operations fail closed.
			if req.Operation == "execution/cancel" || req.Operation == "pi/abort" {
				continue
			}
		}
		return false
	}
	return true
}
