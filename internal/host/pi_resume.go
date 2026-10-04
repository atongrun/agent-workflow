package host

import (
	"net/http"
	"os"
	"strings"

	"github.com/atongrun/agent-workflow/internal/core"
)

type piResumeInput struct {
	RequestID                 string  `json:"requestId"`
	Role                      string  `json:"role"`
	ExpectedSessionID         string  `json:"expectedSessionId"`
	ExpectedProcessID         *string `json:"expectedProcessId"`
	ExpectedLifecycleRevision *int    `json:"expectedLifecycleRevision"`
}

func (s *Server) piResume(w http.ResponseWriter, r *http.Request) {
	if len(r.URL.Query()) != 0 {
		writeError(w, fail("invalid_query", "resume does not accept query parameters", 400))
		return
	}
	var in piResumeInput
	if err := decode(w, r, &in); err != nil {
		writeError(w, err)
		return
	}
	if !validPiRole(in.Role) || in.ExpectedSessionID == "" || in.ExpectedProcessID == nil || in.ExpectedLifecycleRevision == nil {
		writeError(w, fail("invalid_resume", "role, session, process and lifecycle binding are required", 400))
		return
	}
	id := r.PathValue("id")
	lock := s.piDispatchLock(id, in.Role)
	lock.Lock()
	duplicate, err := s.reserveRequest(in.RequestID, id, "pi/resume", in, func(st *core.State, req *core.Request) error {
		task := st.Tasks[id]
		if task == nil {
			return fail("not_found", "task not found", 404)
		}
		if task.LifecycleRevision != *in.ExpectedLifecycleRevision {
			return fail("task_lifecycle_changed", "task lifecycle changed; reload before resuming", 409)
		}
		ref := task.Sessions[in.Role]
		if ref == nil || ref.ID != in.ExpectedSessionID || ref.ProcessID != *in.ExpectedProcessID {
			return fail("stale_pi_session", "Pi binding changed; reload before resuming", 409)
		}
		if pendingPiControl(st, id, in.Role) {
			return fail("pi_control_pending", "inspect the original control receipt before resuming", 409)
		}
		// Capacity validation is read-only. Actual startup rechecks under piLifecycle.
		s.mu.Lock()
		defer s.mu.Unlock()
		existing := s.clients[id+":"+in.Role]
		if existing == nil || !existing.Alive() {
			count := s.starting
			reclaimable := false
			for key, client := range s.clients {
				if !client.Alive() {
					continue
				}
				count++
				parts := strings.SplitN(key, ":", 2)
				if len(parts) == 2 && piReclaimable(st, parts[0], parts[1]) {
					reclaimable = true
				}
			}
			if count >= s.cfg.MaxPiProcesses && !reclaimable {
				return fail("pi_capacity", "all native Pi slots are active or protected; wait for a session to settle", 409)
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
		if !s.launch(func() { s.runPiResume(id, in) }) {
			s.finishPiResume(in.RequestID, "failed", "Host is closing; Pi resume was not attempted", nil)
		}
	}
	s.response(w, in.RequestID)
}
func (s *Server) runPiResume(taskID string, in piResumeInput) {
	lock := s.piDispatchLock(taskID, in.Role)
	lock.Lock()
	defer lock.Unlock()
	err := s.store.Update(func(st *core.State) error {
		task := st.Tasks[taskID]
		req := st.Requests[in.RequestID]
		if req == nil || req.Status != "accepted" {
			return fail("resume_cancelled", "resume is no longer pending", 409)
		}
		if task == nil || task.DeletedAt != nil || task.LifecycleRevision != *in.ExpectedLifecycleRevision || !bindingMatches(task.Sessions[in.Role], piBinding{in.Role, in.ExpectedSessionID, *in.ExpectedProcessID}) {
			return fail("stale_pi_session", "binding changed before Pi resume", 409)
		}
		return nil
	})
	if err != nil {
		s.finishPiResume(in.RequestID, "failed", "Pi resume binding changed before startup", nil)
		return
	}
	client, err := s.clientWithStartFence(taskID, in.Role, func(processID string) error {
		return s.store.Update(func(st *core.State) error {
			task := st.Tasks[taskID]
			req := st.Requests[in.RequestID]
			if req == nil || req.Status != "accepted" || task == nil || task.DeletedAt != nil || task.LifecycleRevision != *in.ExpectedLifecycleRevision || !bindingMatches(task.Sessions[in.Role], piBinding{in.Role, in.ExpectedSessionID, processID}) {
				return fail("stale_pi_session", "binding changed before native startup", 409)
			}
			req.Dispatched = true
			req.ProcessID = processID
			return nil
		})
	})
	if err != nil {
		status, message := "failed", "Pi resume failed before native startup"
		if req := s.store.Snapshot().Requests[in.RequestID]; req != nil && req.Dispatched {
			status, message = "needs_verification", "Pi resume was not confirmed; inspect the original receipt before continuing"
		}
		s.finishPiResume(in.RequestID, status, message, nil)
		return
	}
	task, err := s.task(taskID)
	if err != nil || !client.Alive() || !task.Sessions[in.Role].Available {
		s.finishPiResume(in.RequestID, "needs_verification", "Pi did not remain available after resume", nil)
		return
	}
	binding := piBinding{in.Role, task.Sessions[in.Role].ID, task.Sessions[in.Role].ProcessID}
	s.finishPiResume(in.RequestID, "completed", "", &binding)
}
func (s *Server) finishPiResume(requestID, status, message string, binding *piBinding) {
	_ = s.store.Update(func(st *core.State) error {
		req := st.Requests[requestID]
		if req == nil || req.Status != "accepted" {
			return nil
		}
		task := st.Tasks[req.TaskID]
		if task == nil {
			return nil
		}
		ref := task.Sessions[req.Role]
		if status == "completed" && (binding == nil || !bindingMatches(ref, *binding) || !ref.Available) {
			status = "needs_verification"
			message = "Pi process changed before its resume receipt"
		}
		req.Status = status
		req.Error = message
		if status == "completed" {
			req.SessionID = binding.SessionID
			req.ProcessID = binding.ProcessID
			req.Result = mustJSON(map[string]any{"binding": binding})
			settleCommand(ref, requestID)
		} else if status == "failed" && ref != nil {
			settleCommand(ref, requestID)
		}
		core.Changed(st, task)
		return nil
	})
}

// Reporting/review owns its original Pi until the typed verdict settles. Other
// idle conversations may be reclaimed only for explicit activation, never GET.
func piReclaimable(st *core.State, taskID, role string) bool {
	task := st.Tasks[taskID]
	if task == nil || task.Status == "reporting" || task.Status == "review" || !taskPiIdle(task) || lifecycleRequestPending(st, taskID) {
		return false
	}
	ref := task.Sessions[role]
	if ref == nil {
		return false
	}
	if ref.Persisted {
		if _, err := os.Stat(ref.File); err != nil {
			return false
		}
	}
	return true
}
