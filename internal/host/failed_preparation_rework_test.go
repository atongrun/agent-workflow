package host

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
	"github.com/atongrun/agent-workflow/internal/node"
)

func failedPreparationFixture(t *testing.T) (*Server, *core.Task, *node.Job) {
	t.Helper()
	s := testServer(t)
	task := createTask(t, s, "failed-managed-preparation")
	now := time.Now().UTC()
	err := s.store.Update(func(st *core.State) error {
		x := st.Tasks[task.ID]
		x.PlanningProfile = core.RestrictedPlanning
		x.ProjectID = "managed"
		x.TargetRevision = 1
		x.RepositoryID = "123"
		x.RepositorySource = &core.RepositorySource{BaseRef: "tag", BaseSHA: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", Files: map[string]string{}}
		x.Plan = &core.Plan{Revision: 3, Content: "read only existing tests", ConfirmedAt: &now, Source: "pi_tool"}
		approved, e := approveInput(x)
		if e != nil {
			return e
		}
		approved.RepositoryReadVerified = true
		x.Plan.Approved = approved
		x.Execution = &core.Execution{RequestID: "failed-run", JobID: node.JobID("failed-run"), Status: "failed", DispatchAttempted: true, FinishedAt: &now, Approved: approved, Target: &core.ExecutionTarget{Revision: 1, NodeID: "n", ProjectID: "managed", Repository: x.Repository, RepositoryID: "123"}}
		x.Completion = &core.Completion{Verdict: "needs_changes", ExecutionRequestID: "failed-run"}
		x.Budget.TaskSeconds = 100
		x.Budget.PlanSeconds = 100
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	task, _ = s.task(task.ID)
	job := &node.Job{ID: task.Execution.JobID, RequestID: "failed-run", TaskID: task.ID, ProjectID: "managed", Repository: task.Repository, Branch: task.Branch, Status: "failed", SubmissionState: "queued", CompletedAt: &now}
	return s, task, job
}
func TestFailedPreparationNeedsFreshOriginalDurableReceipt(t *testing.T) {
	_, task, job := failedPreparationFixture(t)
	if needsRework(task) || failedPreparationMatches(task, nil) {
		t.Fatal("model verdict alone permitted failed retry")
	}
	proof := verifyFailedPreparation(task, job)
	if proof == nil || !failedPreparationMatches(task, []*failedPreparationProof{proof}) {
		t.Fatal("verified pre-native failure rejected")
	}
	for name, mutate := range map[string]func(*node.Job){
		"native_creation_unknown": func(j *node.Job) { j.SubmissionState = "creating" }, "native_ready": func(j *node.Job) { j.SubmissionState = "ready" }, "submitted": func(j *node.Job) { j.SubmissionState = "sent_native" }, "session_exists": func(j *node.Job) { j.SessionID = "native" }, "started": func(j *node.Job) { j.StartedAt = j.CompletedAt }, "cancelled": func(j *node.Job) { j.Status = "cancelled" }, "unknown": func(j *node.Job) { j.Status = "needs_verification" }, "no_terminal_receipt": func(j *node.Job) { j.CompletedAt = nil }, "different_run": func(j *node.Job) { j.RequestID = "other" }, "different_task": func(j *node.Job) { j.TaskID = "other" }, "different_branch": func(j *node.Job) { j.Branch = "other" }, "partial_output": func(j *node.Job) { j.Evidence = []node.Evidence{{Kind: "tool"}} }, "charged_native_work": func(j *node.Job) { j.ExecutionSeconds = 1 },
		"permission_pending":    func(j *node.Job) { j.PendingPermissions = []json.RawMessage{json.RawMessage(`{}`)} },
		"question_pending":      func(j *node.Job) { j.PendingQuestions = []json.RawMessage{json.RawMessage(`{}`)} },
		"cancel_requested":      func(j *node.Job) { j.CancelRequested = true },
		"timed_out":             func(j *node.Job) { j.TimedOut = true },
		"native_status":         func(j *node.Job) { j.NativeStatus = "busy" },
		"native_error":          func(j *node.Job) { j.NativeError = "unknown" },
		"terminal_time_changed": func(j *node.Job) { changed := j.CompletedAt.Add(time.Second); j.CompletedAt = &changed },
	} {
		t.Run(name, func(t *testing.T) {
			copy := *job
			mutate(&copy)
			if verifyFailedPreparation(task, &copy) != nil {
				t.Fatal("unsafe receipt accepted")
			}
		})
	}
	for name, mutate := range map[string]func(*core.Task){"target_changed": func(x *core.Task) { x.TargetRevision++ }, "lifecycle_changed": func(x *core.Task) { x.LifecycleRevision++ }, "different_completion": func(x *core.Task) { copy := *x.Completion; copy.ExecutionRequestID = "other"; x.Completion = &copy }, "deleted": func(x *core.Task) { now := time.Now(); x.DeletedAt = &now }} {
		t.Run(name, func(t *testing.T) {
			copy := *task
			mutate(&copy)
			if failedPreparationMatches(&copy, []*failedPreparationProof{proof}) {
				t.Fatal("stale proof admitted")
			}
		})
	}
}
func TestFailedPreparationExplicitReworkPreservesHistoryBudgetAndApproval(t *testing.T) {
	s, task, job := failedPreparationFixture(t)
	nodeHTTP := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/v1/projects" {
			json.NewEncoder(w).Encode(map[string]any{"available": true, "reachable": true, "projects": []map[string]any{{"projectId": "managed", "ready": true, "managed": true}}})
			return
		}
		if r.URL.Path == "/v1/jobs/"+job.ID {
			json.NewEncoder(w).Encode(job)
			return
		}
		http.NotFound(w, r)
	}))
	defer nodeHTTP.Close()
	s.cfg.Nodes["n"] = NodeConfig{URL: nodeHTTP.URL, TokenEnv: "TEST_NODE_TOKEN"}
	// Use the same reservation/preparation path without starting a native monitor.
	proof := verifyFailedPreparation(task, job)
	err := s.store.Update(func(st *core.State) error {
		return s.prepareExecution(st, st.Tasks[task.ID], "explicit-rework", 3, true, ptr(1), proof)
	})
	if err != nil {
		t.Fatal(err)
	}
	got, _ := s.task(task.ID)
	if got.Execution.RequestID != "explicit-rework" || got.Execution.SessionID != "" || got.Execution.Status != "queued" || got.Budget.Reworks != 1 || got.Budget.TaskSeconds != 100 || got.Budget.PlanSeconds != 100 || len(got.ExecutionHistory) != 1 || got.ExecutionHistory[0].Status != "failed" || got.ExecutionHistory[0].RequestID != "failed-run" || got.Execution.Approved.PlanHash != task.Plan.Approved.PlanHash {
		t.Fatal("failed retry changed history, approval or budget")
	}
}

func TestFailedPreparationReworkActionRequiresAuthenticatedFreshProof(t *testing.T) {
	for _, scenario := range []string{"success", "unavailable", "wrong_receipt", "target_changed", "lifecycle_changed", "run_changed", "plan_hash_changed"} {
		t.Run(scenario, func(t *testing.T) {
			s, task, original := failedPreparationFixture(t)
			var originalReads atomic.Int32
			mock := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.Header.Get("Authorization") != "Bearer "+strings.Repeat("n", 32) {
					t.Error("missing authenticated Node read")
					w.WriteHeader(401)
					return
				}
				if r.URL.Path == "/v1/projects" {
					json.NewEncoder(w).Encode(map[string]any{"available": true, "reachable": true, "projects": []map[string]any{{"projectId": "managed", "ready": true, "managed": true}}})
					return
				}
				if r.URL.Path == "/v1/jobs/"+original.ID {
					originalReads.Add(1)
					if scenario == "unavailable" {
						w.WriteHeader(503)
						return
					}
					job := *original
					if scenario == "wrong_receipt" {
						job.TaskID = "different"
					}
					if scenario == "target_changed" || scenario == "lifecycle_changed" || scenario == "run_changed" || scenario == "plan_hash_changed" {
						s.store.Update(func(st *core.State) error {
							x := st.Tasks[task.ID]
							switch scenario {
							case "target_changed":
								x.TargetRevision++
							case "lifecycle_changed":
								x.LifecycleRevision++
							case "run_changed":
								x.Execution.RequestID = "other-run"
							case "plan_hash_changed":
								a := *x.Execution.Approved
								a.PlanHash = "other-hash"
								x.Execution.Approved = &a
							}
							return nil
						})
					}
					json.NewEncoder(w).Encode(job)
					return
				}
				if r.URL.Path == "/v1/jobs/"+node.JobID("retry-action") {
					json.NewEncoder(w).Encode(node.Job{ID: node.JobID("retry-action"), RequestID: "retry-action", TaskID: task.ID, Status: "queued", SubmissionState: "queued"})
					return
				}
				http.NotFound(w, r)
			}))
			t.Cleanup(func() { s.Close(); mock.Close() })
			s.cfg.Nodes["n"] = NodeConfig{URL: mock.URL, TokenEnv: "TEST_NODE_TOKEN"}
			in := actionInput{RequestID: "retry-action", Revision: 3, ExpectedTargetRevision: ptr(1), ExecutionRequestID: "failed-run"}
			response := call(t, s, "POST", "/v1/tasks/"+task.ID+"/rework", in)
			if originalReads.Load() != 1 {
				t.Fatal("original durable receipt was not read exactly once")
			}
			if scenario == "success" {
				if response.Code != 202 {
					t.Fatal(response.Code, response.Body.String())
				}
				retry := call(t, s, "POST", "/v1/tasks/"+task.ID+"/rework", in)
				if retry.Code != 202 || originalReads.Load() != 1 {
					t.Fatal("historical retry performed new admission or Node proof read")
				}
			} else if response.Code != 409 {
				t.Fatal("unverified or stale preparation admitted", response.Code)
			}
		})
	}
}
