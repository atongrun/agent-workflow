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
			var doneChecks []core.EvidenceCheck
			if status != "completed" {
				doneChecks = fixtureEvidenceChecks()
			}
			if w := finishFixture(t, s, task.ID, extensionInput{RequestID: "bad-done", ExecutionRequestID: "result-run", Verdict: "done", Summary: "Model says all passed", EvidenceChecks: doneChecks}); w.Code != 409 {
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
func TestResultReviewReceiptIdentityGates(t *testing.T) {
	mutations := map[string]func(*core.Task){
		"missing_record":          func(x *core.Task) { x.Execution.Evidence = x.Execution.Evidence[1:] },
		"ambiguous_record":        func(x *core.Task) { x.Execution.Evidence = append(x.Execution.Evidence, x.Execution.Evidence[0]) },
		"wrong_session":           func(x *core.Task) { x.Execution.Evidence[1].SessionID = "ses_other" },
		"empty_execution_session": func(x *core.Task) { x.Execution.SessionID = "" },
		"uncompleted_tool":        func(x *core.Task) { x.Execution.Evidence[1].Status = "running" },
		"wrong_kind":              func(x *core.Task) { x.Execution.Evidence[1].Kind = "summary" },
		"missing_tool":            func(x *core.Task) { x.Execution.Evidence[1].Tool = "" },
		"missing_message_id":      func(x *core.Task) { x.Execution.Evidence[1].MessageID = "" },
		"missing_call_id":         func(x *core.Task) { x.Execution.Evidence[1].CallID = "" },
		"stale_execution":         func(x *core.Task) { x.Execution.RequestID = "new-run" },
		"not_reporting":           func(x *core.Task) { x.Status = "executing" },
		"changed_pi_session":      func(x *core.Task) { x.Sessions["architect"].ID = "other-pi" },
		"stale_lifecycle":         func(x *core.Task) { x.LifecycleRevision++ },
	}
	for name, mutate := range mutations {
		t.Run(name, func(t *testing.T) {
			s := testServer(t)
			task := createTask(t, s, name)
			terminalReviewFixture(t, s, task, "completed", true)
			if err := s.store.Update(func(st *core.State) error { mutate(st.Tasks[task.ID]); return nil }); err != nil {
				t.Fatal(err)
			}
			before, _ := s.task(task.ID)
			if w := finishFixture(t, s, task.ID, extensionInput{RequestID: "reject", ExecutionRequestID: "result-run", Verdict: "done", Summary: "Pi assessment", EvidenceChecks: fixtureEvidenceChecks()}); w.Code != 409 {
				t.Fatal(w.Code, w.Body.String())
			}
			got, _ := s.task(task.ID)
			if got.Status != before.Status || got.Completion != nil {
				t.Fatal("invalid reference changed outcome")
			}
		})
	}
}

func TestResultReviewContentsArePiJudgment(t *testing.T) {
	// Synthetic native receipts demonstrate the protocol boundary, not an
	// endorsement of the contents or a reconstruction of the production task.
	mutations := map[string]func(*core.Task){
		"no_diff_marker":   func(x *core.Task) { x.Execution.Evidence[0].Output = "Only a summary" },
		"failed_tests":     func(x *core.Task) { x.Execution.Evidence[1].Metadata = json.RawMessage(`{"exit":1}`) },
		"conflicting_exit": func(x *core.Task) { x.Execution.Evidence[1].Metadata = json.RawMessage(`{"exit":0,"exitCode":1}`) },
		"unknown_exit":     func(x *core.Task) { x.Execution.Evidence[1].Metadata = nil },
		"other_tool": func(x *core.Task) {
			x.Execution.Evidence[1].Tool = "read"
			x.Execution.Evidence[1].Input = json.RawMessage(`{"filePath":"example"}`)
		},
		"empty_output": func(x *core.Task) { x.Execution.Evidence[0].Output = "" },
		"truncated": func(x *core.Task) {
			x.Execution.Evidence[0].Truncated = true
			x.Execution.Evidence[1].Metadata = json.RawMessage(`{"exit":0,"truncated":true}`)
		},
		"different_remote_output": func(x *core.Task) { x.Execution.Evidence[2].Output = fixtureRemoteSHA + "\trefs/heads/other" },
		"windows_wrapper": func(x *core.Task) {
			x.Execution.Evidence[1].Input = json.RawMessage(`{"command":"powershell -Command 'npm test; exit $LASTEXITCODE'"}`)
		},
		"substitution_and_pipeline": func(x *core.Task) {
			x.Execution.Evidence[2].Input = json.RawMessage(`{"command":"sha=$(git ls-remote origin); printf '%s' \"$sha\" | cat"}`)
		},
		"echoed_command": func(x *core.Task) { x.Execution.Evidence[1].Input = json.RawMessage(`{"command":"echo go test"}`) },
	}
	for name, mutate := range mutations {
		t.Run(name, func(t *testing.T) {
			s := testServer(t)
			task := createTask(t, s, name)
			terminalReviewFixture(t, s, task, "completed", true)
			if err := s.store.Update(func(st *core.State) error {
				mutate(st.Tasks[task.ID])
				st.Tasks[task.ID].Budget = core.Budget{TaskSeconds: 161, PlanSeconds: 161, Reworks: 0}
				return nil
			}); err != nil {
				t.Fatal(err)
			}
			before, _ := s.task(task.ID)
			if w := finishFixture(t, s, task.ID, extensionInput{RequestID: "pi-verdict", ExecutionRequestID: "result-run", Verdict: "done", Summary: "Pi review conclusion, not machine verification", EvidenceChecks: fixtureEvidenceChecks()}); w.Code != 202 {
				t.Fatal(w.Code, w.Body.String())
			}
			got, _ := s.task(task.ID)
			if got.Status != "done" || got.Execution.ResultReview.IndependentlyVerified || string(mustJSON(before.Execution.Evidence)) != string(mustJSON(got.Execution.Evidence)) || before.Budget != got.Budget {
				t.Fatal("review rewrote evidence, promoted verification or changed counters")
			}
			for _, e := range got.Execution.Evidence {
				if e.Verified {
					t.Fatal("Pi judgment promoted native verification")
				}
			}
		})
	}
}

func TestResultReviewAssessmentSchemaAndSources(t *testing.T) {
	mutations := map[string]struct {
		mutate func([]core.EvidenceCheck)
		code   int
	}{
		"duplicate_source":   {func(c []core.EvidenceCheck) { c[0].Sources = []string{"native-diff", "native-diff"} }, 409},
		"empty_source":       {func(c []core.EvidenceCheck) { c[0].Sources = []string{""} }, 409},
		"no_source":          {func(c []core.EvidenceCheck) { c[0].Sources = nil }, 409},
		"too_many_sources":   {func(c []core.EvidenceCheck) { c[0].Sources = make([]string, 101) }, 409},
		"foreign_source":     {func(c []core.EvidenceCheck) { c[0].Sources = []string{"other-task-source"} }, 409},
		"duplicate_kind":     {func(c []core.EvidenceCheck) { c[1].Kind = "diff" }, 400},
		"unknown_kind":       {func(c []core.EvidenceCheck) { c[0].Kind = "complete" }, 400},
		"invalid_status":     {func(c []core.EvidenceCheck) { c[0].Status = "verified" }, 400},
		"invalid_sha_format": {func(c []core.EvidenceCheck) { c[2].RemoteSHA = "remote is good" }, 400},
	}
	for name, test := range mutations {
		t.Run(name, func(t *testing.T) {
			s := testServer(t)
			task := createTask(t, s, name)
			terminalReviewFixture(t, s, task, "completed", true)
			checks := fixtureEvidenceChecks()
			test.mutate(checks)
			if w := finishFixture(t, s, task.ID, extensionInput{RequestID: "reject", ExecutionRequestID: "result-run", Verdict: "done", Summary: "Pi assessment", EvidenceChecks: checks}); w.Code != test.code {
				t.Fatal(w.Code, w.Body.String())
			}
		})
	}
}

func TestResultReviewFreeTextNeverCompletesTask(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "chat-only")
	terminalReviewFixture(t, s, task, "completed", true)
	for _, text := range []string{"done", `"done"`, "done!", "complete", `{"verdict":"done"}`} {
		for _, eventType := range []string{"message_update", "message_end"} {
			s.piEvent(task.ID, "architect", task.Sessions["architect"].ProcessID, mustJSON(map[string]any{"type": eventType, "message": map[string]any{"role": "assistant", "content": []map[string]string{{"type": "text", "text": text}}}}))
			got, _ := s.task(task.ID)
			if got.Status != "reporting" || got.Completion != nil {
				t.Fatal("free text completed task")
			}
		}
		if text != "done" {
			if w := finishFixture(t, s, task.ID, extensionInput{RequestID: core.ID(), ExecutionRequestID: "result-run", Verdict: text, Summary: "Text is not enum", EvidenceChecks: fixtureEvidenceChecks()}); w.Code != 400 {
				t.Fatal(w.Code, w.Body.String())
			}
		}
	}
	if w := finishFixture(t, s, task.ID, extensionInput{RequestID: "legal-enum", ExecutionRequestID: "result-run", Verdict: "done", Summary: "Pi structured assessment", EvidenceChecks: fixtureEvidenceChecks()}); w.Code != 202 {
		t.Fatal(w.Code, w.Body.String())
	}
}

func TestResultReviewConcurrentVerdictsAndExactRetries(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "concurrent-verdict")
	terminalReviewFixture(t, s, task, "completed", true)
	var wg sync.WaitGroup
	codes := make(chan int, 8)
	for i := range 8 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			w := finishFixture(t, s, task.ID, extensionInput{RequestID: fmt.Sprintf("verdict-%d", i), ExecutionRequestID: "result-run", Verdict: "done", Summary: "Pi assessment", EvidenceChecks: fixtureEvidenceChecks()})
			codes <- w.Code
		}()
	}
	wg.Wait()
	close(codes)
	accepted := 0
	for code := range codes {
		if code == 202 {
			accepted++
		} else if code != 409 {
			t.Fatalf("unexpected concurrent finish status: %d", code)
		}
	}
	got, _ := s.task(task.ID)
	if accepted != 1 || len(got.CompletionHistory) != 1 || got.Status != "done" {
		t.Fatal("concurrent verdict produced multiple transitions")
	}
	var winner string
	for id, request := range s.store.Snapshot().Requests {
		if request.TaskID == task.ID && request.Operation == "extension/finish" {
			winner = id
		}
	}
	in := extensionInput{RequestID: winner, ExecutionRequestID: "result-run", Verdict: "done", Summary: "Pi assessment", EvidenceChecks: fixtureEvidenceChecks()}
	before := string(mustJSON(got))
	if w := finishFixture(t, s, task.ID, in); w.Code != 202 {
		t.Fatal(w.Code, w.Body.String())
	}
	got, _ = s.task(task.ID)
	if string(mustJSON(got)) != before {
		t.Fatal("exact retry changed finished task")
	}
	in.Summary = "different assessment"
	if w := finishFixture(t, s, task.ID, in); w.Code != 409 {
		t.Fatal(w.Code, w.Body.String())
	}
}

func TestResultReviewCannotCiteAnotherTaskOrHistoricalExecution(t *testing.T) {
	for _, historical := range []bool{false, true} {
		t.Run(fmt.Sprint(historical), func(t *testing.T) {
			s := testServer(t)
			task := createTask(t, s, "current-task")
			other := createTask(t, s, "other-task")
			terminalReviewFixture(t, s, task, "completed", true)
			terminalReviewFixture(t, s, other, "completed", true)
			if err := s.store.Update(func(st *core.State) error {
				st.Tasks[other.ID].Execution.Evidence[0].Source = "foreign-native-source"
				if historical {
					old := *st.Tasks[other.ID].Execution
					st.Tasks[task.ID].ExecutionHistory = append(st.Tasks[task.ID].ExecutionHistory, old)
				}
				return nil
			}); err != nil {
				t.Fatal(err)
			}
			checks := fixtureEvidenceChecks()
			checks[0].Sources = []string{"foreign-native-source"}
			if w := finishFixture(t, s, task.ID, extensionInput{RequestID: "foreign-verdict", ExecutionRequestID: "result-run", Verdict: "done", Summary: "Pi assessment", EvidenceChecks: checks}); w.Code != 409 {
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
