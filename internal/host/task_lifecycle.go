package host

import (
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
	"github.com/atongrun/agent-workflow/internal/pi"
)

type lifecycleInput struct {
	RequestID string `json:"requestId"`
}

// Deletion is recoverable metadata, never a filesystem or repository operation.
// A durable deletedAt fences every new reservation before idle processes close.
// Only a verified process exit completes the receipt. Restore never starts Pi.
func (s *Server) taskLifecycle(w http.ResponseWriter, r *http.Request) {
	if len(r.URL.Query()) != 0 {
		writeError(w, fail("invalid_query", "task lifecycle operations do not accept query parameters", 400))
		return
	}
	var in lifecycleInput
	if err := decode(w, r, &in); err != nil {
		writeError(w, err)
		return
	}
	id := r.PathValue("id")
	op := strings.TrimPrefix(r.URL.Path, "/v1/tasks/"+id+"/")
	s.piLifecycle.Lock()
	defer s.piLifecycle.Unlock()
	duplicate, err := s.reserveRequest(in.RequestID, id, op, in, func(st *core.State, req *core.Request) error {
		t := st.Tasks[id]
		if t == nil {
			return fail("not_found", "task not found", 404)
		}
		if op == "restore" {
			if t.DeletedAt == nil {
				return fail("task_not_deleted", "task is not in Trash", 409)
			}
			if lifecycleRequestPending(st, id) {
				return fail("task_needs_verification", "verify the original deletion receipt before restoring", 409)
			}
			t.DeletedAt = nil
			req.Status = "completed"
		} else {
			if t.DeletedAt != nil {
				return fail("task_deleted", "task is already in Trash; inspect its original deletion receipt", 409)
			}
			if executionActive(t) || t.Status == "queued" || t.Status == "executing" || t.Status == "needs_verification" || t.Status == "review" || t.Status == "reporting" {
				return fail("execution_active", "wait for execution and result reporting to settle before deleting", 409)
			}
			if !taskPiIdle(t) || t.Budget.ActiveSince != nil {
				return fail("role_busy", "wait for Pi, queued work, and pending dialogs to settle before deleting", 409)
			}
			if lifecycleRequestPending(st, id) {
				return fail("task_needs_verification", "verify pending or uncertain request receipts before deleting", 409)
			}
			if t.Execution != nil && (len(t.Execution.PendingPermissions) > 0 || len(t.Execution.PendingQuestions) > 0) {
				return fail("execution_active", "execution still has pending native questions or permissions", 409)
			}
			now := time.Now().UTC()
			t.DeletedAt = &now
			for _, ref := range t.Sessions {
				ref.Available = false
				// Detach late callbacks without changing native session/file identity.
				ref.ProcessID = ""
			}
		}
		t.LifecycleRevision++
		core.Changed(st, t)
		return nil
	})
	if err != nil {
		writeError(w, err)
		return
	}
	if !duplicate && op == "delete" {
		clients := []*pi.Client{}
		s.mu.Lock()
		for key, client := range s.clients {
			if strings.HasPrefix(key, id+":") {
				clients = append(clients, client)
				delete(s.clients, key)
			}
		}
		s.mu.Unlock()
		for _, client := range clients {
			closeErr := client.Close()
			deadline := time.Now().Add(5 * time.Second)
			for client.Alive() && time.Now().Before(deadline) {
				time.Sleep(10 * time.Millisecond)
			}
			if client.Alive() {
				err = fmt.Errorf("native Pi exit was not confirmed; verify the original deletion receipt before restoring: %v", closeErr)
			}
		}
		status := "completed"
		if err != nil {
			status = "needs_verification"
		}
		// Do not turn a persistence failure into a successful response. The
		// original accepted receipt remains the only recoverable identity.
		if saveErr := s.store.Update(func(st *core.State) error {
			req := st.Requests[in.RequestID]
			req.Status = status
			if err != nil {
				req.Error = err.Error()
			}
			return nil
		}); saveErr != nil {
			writeError(w, saveErr)
			return
		}
	}
	s.response(w, in.RequestID)
}

func lifecycleRequestPending(st *core.State, id string) bool {
	for _, req := range st.Requests {
		if req.TaskID != id {
			continue
		}
		switch req.Status {
		case "accepted", "needs_verification", "queued", "running", "dispatching", "uncertain", "cancelling":
			return true
		case "accepted_native":
			// Execution cancellation and UI delivery have their own terminal
			// job/dialog state. Native prompt receipts require an actual settle.
			switch req.Operation {
			case "messages", "review", "auto_review", "execution_result":
				return true
			}
		}
	}
	return false
}
