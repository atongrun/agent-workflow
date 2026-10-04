package host

import (
	"net/http"
	"regexp"
	"sort"
	"strings"
	"time"

	"context"
	"github.com/atongrun/agent-workflow/internal/core"
	"github.com/atongrun/agent-workflow/internal/pi"
)

// Set only by reviewed Linux release packaging. Existing health/Windows version
// contracts are unchanged; dev/unpinned builds never claim activation readiness.
var BuildVersion = "dev"
var BuildSourceCommit = ""
var maintenanceTarget = regexp.MustCompile(`^[0-9a-f]{64}$`)
var maintenanceBuildCommit = regexp.MustCompile(`^[0-9a-f]{40}$`)
var maintenanceBuildVersion = regexp.MustCompile(`^v1\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-rc\.(0|[1-9][0-9]*))?$`)

type maintenanceInput struct {
	RequestID            string `json:"requestId"`
	ExpectedRevision     *int   `json:"expectedRevision"`
	OwnerRequestID       string `json:"ownerRequestId,omitempty"`
	TargetManifestSHA256 string `json:"targetManifestSHA256,omitempty"`
}

func maintenanceEffect(st *core.State) error {
	if st.Maintenance != nil && st.Maintenance.Phase != "open" && st.Maintenance.Phase != "draining" {
		return fail("maintenance_sealed", "Host maintenance forbids native dispatch", 409)
	}
	return nil
}

// The snapshot and actual send share a read lease. Seal takes the write lease,
// so a late budget stop, cancellation or retry cannot cross the durable seal.
func (s *Server) beginNativeEffect() (func(), error) {
	s.nativeEffects.RLock()
	st := s.store.Snapshot()
	if err := maintenanceEffect(&st); err != nil {
		s.nativeEffects.RUnlock()
		return nil, err
	}
	return s.nativeEffects.RUnlock, nil
}
func (s *Server) fencedPiBegin(c *pi.Client, method string, fields map[string]any) (*pi.PendingCall, error) {
	done, err := s.beginNativeEffect()
	if err != nil {
		return nil, err
	}
	defer done()
	return c.BeginCall(method, fields)
}
func (s *Server) fencedPiStop(ctx context.Context, c *pi.Client) error {
	done, err := s.beginNativeEffect()
	if err != nil {
		return err
	}
	defer done()
	return c.Stop(ctx)
}
func (s *Server) fencedPiRespond(c *pi.Client, id string, response map[string]any) error {
	done, err := s.beginNativeEffect()
	if err != nil {
		return err
	}
	defer done()
	return c.Respond(id, response)
}
func maintenanceAdmission(st *core.State, taskID, op string) error {
	m := st.Maintenance
	if m == nil || m.Phase == "open" {
		return nil
	}
	if strings.HasPrefix(op, "maintenance/") {
		return nil
	} // handler performs owner/CAS checks
	if m.Phase != "draining" {
		return fail("maintenance_sealed", "Host is sealed for maintenance", 409)
	}
	drain := false
	for _, id := range m.DrainTasks {
		if id == taskID {
			drain = true
			break
		}
	}
	if drain {
		switch op {
		case "execution/cancel", "pi/abort", "pi/ui-response", "execution_result", "auto_review", "extension/context", "extension/plan", "extension/execute", "extension/finish", "extension/review":
			return nil
		}
		if strings.HasPrefix(op, "execution/question-reply/") {
			return nil
		}
	}
	return fail("maintenance_draining", "Host maintenance blocks new work; settle existing work or release the lease", 409)
}
func maintenanceTaskBusy(st *core.State, t *core.Task) bool {
	if executionActive(t) || !taskPiIdle(t) || t.Budget.ActiveSince != nil || !budgetTaskSettled(t.Status) {
		return true
	}
	if t.Execution != nil && (len(t.Execution.PendingQuestions) > 0 || len(t.Execution.PendingPermissions) > 0) {
		return true
	}
	return !budgetRequestsSettled(st, t.ID)
}
func (s *Server) maintenanceIdle(st *core.State) (bool, []string) {
	blockers := []string{}
	for _, t := range st.Tasks {
		if maintenanceTaskBusy(st, t) {
			blockers = append(blockers, "task:"+t.ID)
		}
	}
	for _, req := range st.Requests {
		if strings.HasPrefix(req.Operation, "maintenance/") {
			continue
		}
		if st.Tasks[req.TaskID] == nil && requestPending(req) {
			blockers = append(blockers, "request:"+req.ID)
		}
	}
	s.mu.Lock()
	if s.starting > 0 {
		blockers = append(blockers, "pi-startup")
	}
	if s.closing {
		blockers = append(blockers, "host-closing")
	}
	s.mu.Unlock()
	sort.Strings(blockers)
	return len(blockers) == 0, blockers
}
func (s *Server) maintenanceStatus(w http.ResponseWriter, r *http.Request) {
	if len(r.URL.Query()) != 0 {
		writeError(w, fail("invalid_query", "maintenance status has no query parameters", 400))
		return
	}
	st := s.store.Snapshot()
	m := st.Maintenance
	if m == nil {
		m = &core.Maintenance{Phase: "open"}
	}
	idle, blockers := s.maintenanceIdle(&st)
	writeJSON(w, 200, map[string]any{"maintenance": m, "idleObserved": idle, "blockers": blockers, "nativeActivationReady": false, "build": map[string]any{"available": maintenanceBuildVersion.MatchString(BuildVersion) && maintenanceBuildCommit.MatchString(BuildSourceCommit), "version": BuildVersion, "sourceCommit": BuildSourceCommit, "hostProtocol": "v1", "piRPCVersion": "1.0.2"}})
}
func (s *Server) maintenanceAction(w http.ResponseWriter, r *http.Request) {
	if len(r.URL.Query()) != 0 {
		writeError(w, fail("invalid_query", "maintenance actions have no query parameters", 400))
		return
	}
	action := r.PathValue("action")
	if action != "begin" && action != "seal" && action != "end" {
		writeError(w, fail("not_found", "unknown maintenance action", 404))
		return
	}
	var in maintenanceInput
	if err := decode(w, r, &in); err != nil {
		writeError(w, err)
		return
	}
	if in.ExpectedRevision == nil || *in.ExpectedRevision < 0 {
		writeError(w, fail("invalid_maintenance", "expectedRevision is required", 400))
		return
	}
	if action == "begin" {
		if in.OwnerRequestID != "" || !maintenanceTarget.MatchString(in.TargetManifestSHA256) {
			writeError(w, fail("invalid_maintenance", "begin requires an exact target manifest SHA256 and no owner", 400))
			return
		}
	} else if !requestPattern.MatchString(in.OwnerRequestID) || in.TargetManifestSHA256 != "" {
		writeError(w, fail("invalid_maintenance", "seal/end require the original owner requestId", 400))
		return
	}
	// Startup/eviction cannot straddle the final idle check and durable seal.
	s.piLifecycle.Lock()
	defer s.piLifecycle.Unlock()
	s.nativeEffects.Lock()
	defer s.nativeEffects.Unlock()
	_, err := s.reserveRequest(in.RequestID, "", "maintenance/"+action, in, func(st *core.State, req *core.Request) error {
		current := st.Maintenance
		if current == nil {
			current = &core.Maintenance{Phase: "open"}
		}
		if current.Revision != *in.ExpectedRevision {
			return fail("maintenance_changed", "refresh maintenance revision", 409)
		}
		next := *current
		switch action {
		case "begin":
			if current.Phase != "open" {
				return fail("maintenance_owned", "an existing lease must be explicitly released", 409)
			}
			now := time.Now().UTC()
			next = core.Maintenance{Revision: current.Revision, Phase: "draining", OwnerRequestID: in.RequestID, TargetManifestSHA256: in.TargetManifestSHA256, BeganAt: &now}
			for id, t := range st.Tasks {
				if maintenanceTaskBusy(st, t) {
					next.DrainTasks = append(next.DrainTasks, id)
				}
			}
			sort.Strings(next.DrainTasks)
		case "seal", "end":
			if current.Phase == "open" || current.OwnerRequestID != in.OwnerRequestID {
				return fail("maintenance_owner_changed", "use the original maintenance owner requestId", 409)
			}
			if action == "seal" {
				if current.Phase != "draining" {
					return fail("maintenance_sealed", "lease is already sealed", 409)
				}
				if idle, _ := s.maintenanceIdle(st); !idle {
					return fail("maintenance_busy", "existing work or unknown outcomes must settle before sealing", 409)
				}
				next.Phase = "sealed"
			} else {
				next = core.Maintenance{Revision: current.Revision, Phase: "open"}
			}
		}
		next.Revision++
		st.Maintenance = &next
		req.Status = "completed"
		req.Result = mustJSON(next)
		core.Emit(st, "", "maintenance."+action, map[string]any{"requestId": in.RequestID, "maintenance": next})
		return nil
	})
	if err != nil {
		writeError(w, err)
		return
	}
	st := s.store.Snapshot()
	writeJSON(w, 200, map[string]any{"maintenance": st.Maintenance, "request": st.Requests[in.RequestID], "nativeActivationReady": false})
}
