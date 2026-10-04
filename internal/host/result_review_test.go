package host

import (
	"encoding/json"
	"fmt"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
	"github.com/atongrun/agent-workflow/internal/node"
)

const fixtureRemoteSHA = "1234567890123456789012345678901234567890"

func fixtureResultEvidence(branch string) []node.Evidence {
	return []node.Evidence{
		{Kind: "tool", Source: "native-diff", Tool: "bash", Status: "completed", MessageID: "msg_diff", CallID: "call_diff", Input: json.RawMessage(`{"command":"git diff HEAD~1 HEAD"}`), Output: "diff --git a/example b/example\n+changed", Metadata: json.RawMessage(`{"exit":0}`)},
		{Kind: "tool", Source: "native-tests", Tool: "bash", Status: "completed", MessageID: "msg_tests", CallID: "call_tests", Input: json.RawMessage(`{"command":"go test ./..."}`), Output: "ok fixture", Metadata: json.RawMessage(`{"exit":0}`)},
		{Kind: "tool", Source: "native-remote", Tool: "bash", Status: "completed", MessageID: "msg_remote", CallID: "call_remote", Input: mustJSON(map[string]string{"command": "git ls-remote origin refs/heads/" + branch}), Output: fixtureRemoteSHA + "\trefs/heads/" + branch, Metadata: json.RawMessage(`{"exit":0}`)},
	}
}
func fixtureEvidenceChecks() []core.EvidenceCheck {
	return []core.EvidenceCheck{{Kind: "diff", Status: "observed", Sources: []string{"native-diff"}}, {Kind: "tests", Status: "observed", Sources: []string{"native-tests"}}, {Kind: "remote_sha", Status: "observed", Sources: []string{"native-remote"}, RemoteSHA: fixtureRemoteSHA}}
}
func finishFixture(t *testing.T, s *Server, taskID string, in extensionInput) *httptest.ResponseRecorder {
	t.Helper()
	r := httptest.NewRequest("POST", "/internal/tasks/"+taskID+"/finish", strings.NewReader(string(mustJSON(in))))
	r.Header.Set("Authorization", "Bearer "+s.scopedToken(taskID, "architect"))
	r.Header.Set("X-AWF-Role", "architect")
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, r)
	return w
}
func terminalReviewFixture(t *testing.T, s *Server, task *core.Task, status string, busy bool) {
	t.Helper()
	if err := s.store.Update(func(st *core.State) error {
		x := st.Tasks[task.ID]
		x.Execution = &core.Execution{RequestID: "result-run", JobID: "result-job", Status: "running"}
		x.Sessions["architect"].Busy = busy
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	s.applyJob(task.ID, &node.Job{ID: "result-job", TaskID: task.ID, RequestID: "result-run", SessionID: "ses_executor", Status: status, Summary: "Model claims push and all tests passed", Evidence: fixtureResultEvidence(task.Branch)}, 0)
}
func TestResultReviewQueuesWhileBusyAndDeduplicatesTerminal(t *testing.T) {
	s, task, _, log, _ := piControlFixture(t, "")
	terminalReviewFixture(t, s, task, "completed", true)
	s.beginExecutionSummary(task.ID)
	st := s.store.Snapshot()
	receipt := st.Requests["result-result-run"]
	if receipt == nil || receipt.Status != "queued" || methodCount(t, log, "prompt") != 0 {
		t.Fatal("busy result was not durably queued")
	}
	ref := st.Tasks[task.ID].Sessions["architect"]
	s.piEvent(task.ID, "architect", ref.ProcessID, json.RawMessage(`{"type":"agent_settled"}`))
	awaitPiRequest(t, s, "result-result-run", "settled")
	var wg sync.WaitGroup
	for range 15 {
		wg.Add(1)
		go func() { defer wg.Done(); s.beginExecutionSummary(task.ID) }()
	}
	wg.Wait()
	if methodCount(t, log, "prompt") != 1 {
		t.Fatal("terminal receipt duplicated result prompt")
	}
	got, _ := s.task(task.ID)
	if got.Execution.ResultReview.SessionID != task.Sessions["architect"].ID || got.Sessions["reviewer"] != nil || got.Status == "done" {
		t.Fatal("review left same session or invented Done")
	}
	if w := finishFixture(t, s, task.ID, extensionInput{RequestID: "review-verdict", ExecutionRequestID: "result-run", Verdict: "done", Summary: "Synthetic fixture evidence assessed", EvidenceChecks: fixtureEvidenceChecks()}); w.Code != 202 {
		t.Fatal(w.Code, w.Body.String())
	}
	s.applyJob(task.ID, &node.Job{ID: "result-job", TaskID: task.ID, RequestID: "result-run", SessionID: "ses_executor", Status: "completed", Evidence: fixtureResultEvidence(task.Branch)}, 0)
	s.applyJob(task.ID, &node.Job{ID: "result-job", TaskID: task.ID, RequestID: "result-run", Status: "running"}, 0)
	got, _ = s.task(task.ID)
	if got.Status != "done" || got.Execution.ResultReview.Status != "reviewed" || got.Execution.ResultReview.IndependentlyVerified || got.Execution.Evidence[0].Verified {
		t.Fatal("late polling reopened verdict or invented independent proof")
	}
}
func TestResultReviewRestartQueuesOnlyUnsentReceipt(t *testing.T) {
	for _, sent := range []bool{false, true} {
		t.Run(core.ID(), func(t *testing.T) {
			s, task, _, log, _ := piControlFixture(t, "")
			terminalReviewFixture(t, s, task, "completed", true)
			s.beginExecutionSummary(task.ID)
			if err := s.store.Update(func(st *core.State) error {
				req := st.Requests["result-result-run"]
				req.Status = "accepted"
				req.Dispatched = sent
				return nil
			}); err != nil {
				t.Fatal(err)
			}
			cfg := s.cfg
			s.Close()
			reopened, err := New(cfg)
			if err != nil {
				t.Fatal(err)
			}
			defer reopened.Close()
			if sent {
				deadline := time.Now().Add(time.Second)
				for time.Now().Before(deadline) {
					got, _ := reopened.task(task.ID)
					if got.Execution.ResultReview.Status == "needs_verification" {
						break
					}
					time.Sleep(10 * time.Millisecond)
				}
				if methodCount(t, log, "prompt") != 0 {
					t.Fatal("restart replayed an ambiguous prompt")
				}
				if reopened.store.Snapshot().Requests["result-result-run"].Status != "needs_verification" {
					t.Fatal("ambiguous receipt lost")
				}
			} else {
				awaitPiRequest(t, reopened, "result-result-run", "settled")
				if methodCount(t, log, "prompt") != 1 {
					t.Fatal("queued result did not recover once")
				}
				got, _ := reopened.task(task.ID)
				if got.Sessions["architect"].ID != task.Sessions["architect"].ID {
					t.Fatal("restart created another context")
				}
			}
		})
	}
}
func TestResultReviewUnknownAndFailedCannotBeDoneOrReworked(t *testing.T) {
	for _, status := range []string{"completed", "failed", "cancelled"} {
		t.Run(status, func(t *testing.T) {
			s := testServer(t)
			task := createTask(t, s, "review-"+status)
			terminalReviewFixture(t, s, task, status, true)
			if w := finishFixture(t, s, task.ID, extensionInput{RequestID: "bad-done", ExecutionRequestID: "result-run", Verdict: "done", Summary: "Model says all passed"}); w.Code != 409 {
				t.Fatal(w.Code, w.Body.String())
			}
			unknown := unknownEvidenceChecks()
			for i := range unknown {
				unknown[i].Notes = "No independently established evidence"
			}
			if w := finishFixture(t, s, task.ID, extensionInput{RequestID: "unknown-review", ExecutionRequestID: "result-run", Verdict: "needs_changes", Summary: "Evidence is unknown", EvidenceChecks: unknown}); w.Code != 202 {
				t.Fatal(w.Code, w.Body.String())
			}
			got, _ := s.task(task.ID)
			if status != "completed" && needsRework(got) {
				t.Fatal("failed/cancelled review authorized rework")
			}
			if got.Execution.ResultReview.Status != "reviewed" || got.Execution.ResultReview.EvidenceChecks[0].Status != "unknown" || got.Status == "done" {
				t.Fatal("unknown review became Done")
			}
		})
	}
}
func TestResultReviewEvidenceGates(t *testing.T) {
	mutations := map[string]func(*core.Task){
		"missing_diff": func(x *core.Task) { x.Execution.Evidence[0].Output = "Only a summary" },
		"failed_tests": func(x *core.Task) { x.Execution.Evidence[1].Metadata = json.RawMessage(`{"exit":1}`) },
		"background_tests": func(x *core.Task) {
			x.Execution.Evidence[1].Input = json.RawMessage(`{"command":"go test ./... & wait"}`)
		},
		"masked_test_exit": func(x *core.Task) {
			x.Execution.Evidence[1].Input = json.RawMessage(`{"command":"go test ./... || true"}`)
		},
		"echoed_test_command": func(x *core.Task) {
			x.Execution.Evidence[1].Input = json.RawMessage(`{"command":"echo go test ./..."}`)
		},
		"conflicting_exit": func(x *core.Task) { x.Execution.Evidence[1].Metadata = json.RawMessage(`{"exit":0,"exitCode":1}`) },
		"unknown_exit":     func(x *core.Task) { x.Execution.Evidence[1].Metadata = nil },
		"push_only": func(x *core.Task) {
			x.Execution.Evidence[2].Input = json.RawMessage(`{"command":"git push origin HEAD"}`)
		},
		"wrong_remote_branch": func(x *core.Task) { x.Execution.Evidence[2].Output = fixtureRemoteSHA + "\trefs/heads/other" },
		"truncated":           func(x *core.Task) { x.Execution.Evidence[0].Truncated = true },
		"wrong_session":       func(x *core.Task) { x.Execution.Evidence[1].SessionID = "ses_other" },
		"uncompleted_tool":    func(x *core.Task) { x.Execution.Evidence[1].Status = "running" },
	}
	for name, mutate := range mutations {
		t.Run(name, func(t *testing.T) {
			s := testServer(t)
			task := createTask(t, s, name)
			terminalReviewFixture(t, s, task, "completed", true)
			if err := s.store.Update(func(st *core.State) error { mutate(st.Tasks[task.ID]); return nil }); err != nil {
				t.Fatal(err)
			}
			if w := finishFixture(t, s, task.ID, extensionInput{RequestID: "reject", ExecutionRequestID: "result-run", Verdict: "done", Summary: "Claimed done", EvidenceChecks: fixtureEvidenceChecks()}); w.Code != 409 {
				t.Fatal(w.Code, w.Body.String())
			}
		})
	}
}
func TestResultReviewBudgetExhaustionAndNonterminal(t *testing.T) {
	s, task, _, log, _ := piControlFixture(t, "")
	if err := s.store.Update(func(st *core.State) error {
		x := st.Tasks[task.ID]
		x.Execution = &core.Execution{RequestID: "result-run", JobID: "result-job", Status: "uncertain"}
		x.Status = "needs_verification"
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	s.beginExecutionSummary(task.ID)
	if s.store.Snapshot().Requests["result-result-run"] != nil {
		t.Fatal("idle/uncertain became terminal review")
	}
	terminalReviewFixture(t, s, task, "completed", false)
	if err := s.store.Update(func(st *core.State) error {
		x := st.Tasks[task.ID]
		x.Budget.TaskSeconds = int64(x.Settings.TaskMinutes * 60)
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	s.beginExecutionSummary(task.ID)
	got, _ := s.task(task.ID)
	if methodCount(t, log, "prompt") != 0 || got.Execution.ResultReview.Status != "blocked" || got.Status != "blocked" {
		t.Fatal("review bypassed exhausted budget")
	}
}

func TestResultReviewEarlyVerdictCancelsUnsentPrompt(t *testing.T) {
	s, task, _, log, _ := piControlFixture(t, "")
	terminalReviewFixture(t, s, task, "completed", true)
	s.beginExecutionSummary(task.ID)
	if w := finishFixture(t, s, task.ID, extensionInput{RequestID: "early-verdict", ExecutionRequestID: "result-run", Verdict: "done", Summary: "Actual fixture outputs assessed", EvidenceChecks: fixtureEvidenceChecks()}); w.Code != 202 {
		t.Fatal(w.Code, w.Body.String())
	}
	st := s.store.Snapshot()
	if st.Requests["result-result-run"].Status != "cancelled" || st.Requests["result-result-run"].Dispatched {
		t.Fatal("unsent result receipt survived verdict")
	}
	s.beginExecutionSummary(task.ID)
	if methodCount(t, log, "prompt") != 0 {
		t.Fatal("verdict caused another prompt")
	}
}
func TestResultReviewSentQueueFailsClosed(t *testing.T) {
	s, task, _, log, _ := piControlFixture(t, "")
	terminalReviewFixture(t, s, task, "completed", true)
	s.beginExecutionSummary(task.ID)
	if err := s.store.Update(func(st *core.State) error { st.Requests["result-result-run"].Dispatched = true; return nil }); err != nil {
		t.Fatal(err)
	}
	s.beginExecutionSummary(task.ID)
	st := s.store.Snapshot()
	if st.Requests["result-result-run"].Status != "needs_verification" || st.Tasks[task.ID].Execution.ResultReview.Status != "needs_verification" || methodCount(t, log, "prompt") != 0 {
		t.Fatal("sent queue was replayed or hid its uncertainty")
	}
}

func TestResultReviewLateVerdictResolvesAmbiguousDelivery(t *testing.T) {
	s, task, _, log, _ := piControlFixture(t, "")
	terminalReviewFixture(t, s, task, "completed", true)
	s.beginExecutionSummary(task.ID)
	if err := s.store.Update(func(st *core.State) error {
		req := st.Requests["result-result-run"]
		req.Dispatched = true
		req.Status = "needs_verification"
		x := st.Tasks[task.ID]
		x.Sessions["architect"].Busy = false
		x.Execution.ResultReview.Status = "needs_verification"
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	if w := finishFixture(t, s, task.ID, extensionInput{RequestID: "late-verdict", ExecutionRequestID: "result-run", Verdict: "done", Summary: "Actual fixture output assessed", EvidenceChecks: fixtureEvidenceChecks()}); w.Code != 202 {
		t.Fatal(w.Code, w.Body.String())
	}
	s.requestDone("result-result-run", "accepted_native", nil)
	s.requestDone("result-result-run", "needs_verification", fmt.Errorf("late lost ACK"))
	st := s.store.Snapshot()
	if st.Requests["result-result-run"].Status != "completed" || st.Requests["result-result-run"].Error != "" || st.Tasks[task.ID].Execution.ResultReview.Status != "reviewed" {
		t.Fatal("late ACK regressed resolved result receipt")
	}
	if lifecycleRequestPending(&st, task.ID) {
		t.Fatal("resolved verdict kept lifecycle blocked")
	}
	s.beginExecutionSummary(task.ID)
	if methodCount(t, log, "prompt") != 0 {
		t.Fatal("ambiguous delivery replayed after verdict")
	}
}
