package host

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
	"github.com/atongrun/agent-workflow/internal/node"
)

func testServer(t *testing.T) *Server {
	t.Helper()
	t.Setenv("TEST_HOST_TOKEN", strings.Repeat("h", 32))
	t.Setenv("TEST_EXTENSION_TOKEN", strings.Repeat("e", 32))
	t.Setenv("TEST_NODE_TOKEN", strings.Repeat("n", 32))
	nodeHTTP := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if serveTestCatalog(w, r) {
			return
		}
		http.NotFound(w, r)
	}))
	t.Cleanup(nodeHTTP.Close)
	s, err := New(Config{DataDir: t.TempDir(), TokenEnv: "TEST_HOST_TOKEN", ExtensionTokenEnv: "TEST_EXTENSION_TOKEN", InternalURL: "http://127.0.0.1:7070", Projects: map[string]string{"p": t.TempDir()}, Nodes: map[string]NodeConfig{"n": {URL: nodeHTTP.URL, TokenEnv: "TEST_NODE_TOKEN"}}})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(s.Close)
	return s
}
func call(t *testing.T, s *Server, method, path string, payload any) *httptest.ResponseRecorder {
	t.Helper()
	b, _ := json.Marshal(payload)
	req := httptest.NewRequest(method, path, bytes.NewReader(b))
	req.Header.Set("Authorization", "Bearer "+s.token)
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, req)
	return w
}
func createTask(t *testing.T, s *Server, request string) *core.Task {
	t.Helper()
	w := call(t, s, "POST", "/v1/tasks", createInput{RequestID: request, Title: "Task", ProjectID: "p", NodeID: "n", Repository: "example/repo", Goal: "Make an authorized small change", AcceptanceCriteria: "Run relevant tests"})
	if w.Code != 202 {
		t.Fatalf("create: %d %s", w.Code, w.Body.String())
	}
	var got struct {
		Task *core.Task `json:"task"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &got); err != nil {
		t.Fatal(err)
	}
	// The original tests exercise persisted, pre-profile tasks. New restricted
	// creation/binding is covered separately by targets_test.go.
	if err := s.store.Update(func(st *core.State) error {
		st.Tasks[got.Task.ID].PlanningProfile = ""
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	got.Task.PlanningProfile = ""
	return got.Task
}
func serveTestCatalog(w http.ResponseWriter, r *http.Request) bool {
	if r.URL.Path != "/v1/projects" {
		return false
	}
	writeJSON(w, 200, map[string]any{"available": true, "reachable": true, "projects": []map[string]any{{"projectId": "p", "label": "p", "ready": true}}})
	return true
}
func TestConcurrentCreateIdempotency(t *testing.T) {
	s := testServer(t)
	var wg sync.WaitGroup
	codes := make(chan int, 20)
	for range 20 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			w := call(t, s, "POST", "/v1/tasks", createInput{RequestID: "same", Title: "Task", ProjectID: "p", NodeID: "n", Goal: "Goal"})
			codes <- w.Code
		}()
	}
	wg.Wait()
	close(codes)
	for code := range codes {
		if code != 202 {
			t.Fatalf("duplicate returned %d", code)
		}
	}
	if len(s.store.Snapshot().Tasks) != 1 {
		t.Fatal("duplicate task created")
	}
	w := call(t, s, "POST", "/v1/tasks", createInput{RequestID: "same", Title: "Different", ProjectID: "p", NodeID: "n", Goal: "Goal"})
	if w.Code != 409 {
		t.Fatalf("expected idempotency conflict: %d", w.Code)
	}
}
func TestSettingsSnapshotAndAuthorization(t *testing.T) {
	s := testServer(t)
	first := createTask(t, s, "first")
	w := call(t, s, "PATCH", "/v1/settings", map[string]any{"requestId": "settings", "defaultBranch": "develop", "branchPrefix": "work/"})
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	second := createTask(t, s, "second")
	if first.Settings.DefaultBranch != "main" || second.Settings.DefaultBranch != "develop" {
		t.Fatal("defaults were not snapshotted")
	}
	req := httptest.NewRequest("GET", "/v1/tasks", nil)
	req.Header.Set("Authorization", s.token)
	w = httptest.NewRecorder()
	s.Handler().ServeHTTP(w, req)
	if w.Code != 401 {
		t.Fatal("accepted naked token")
	}
}
func TestExplicitPlanAndProjectSerial(t *testing.T) {
	s := testServer(t)
	first := createTask(t, s, "one")
	second := createTask(t, s, "two")
	w := call(t, s, "POST", "/v1/tasks/"+first.ID+"/start", actionInput{RequestID: "start", Revision: 1})
	if w.Code != 409 {
		t.Fatal("unconfirmed plan started")
	}
	now := time.Now().UTC()
	err := s.store.Update(func(st *core.State) error {
		st.Tasks[first.ID].Plan = &core.Plan{Revision: 1, Content: "Plan", ConfirmedAt: &now}
		if err := s.prepareExecution(st, st.Tasks[first.ID], "run", 1, false, nil); err != nil {
			return err
		}
		st.Tasks[second.ID].Plan = &core.Plan{Revision: 1, Content: "Other plan", ConfirmedAt: &now}
		if err := s.prepareExecution(st, st.Tasks[second.ID], "other", 1, false, nil); err == nil {
			t.Fatal("parallel project execution accepted")
		}
		if projectAvailable(st, st.Tasks[second.ID]) == nil {
			t.Fatal("cross-task Pi allowed while execution active")
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
}
func TestReworkRetainsBudgetHistoryAndConfirmation(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "rework-task")
	now := time.Now().UTC()
	err := s.store.Update(func(st *core.State) error {
		cur := st.Tasks[task.ID]
		cur.Plan = &core.Plan{Revision: 2, Content: "Revised", ConfirmedAt: &now}
		cur.Execution = &core.Execution{RequestID: "old", JobID: "old-job", SessionID: "native-session", Status: "completed", Evidence: []core.Evidence{{Kind: "tool", Content: "actual native result"}}}
		cur.Completion = &core.Completion{Verdict: "needs_changes", ExecutionRequestID: "old", Summary: "Fix the failing check"}
		cur.Budget.TaskSeconds = 100
		cur.Budget.PlanSeconds = 100
		cur.Status = "needs_changes"
		if err := s.prepareExecution(st, cur, "new", 2, true, nil); err != nil {
			return err
		}
		if cur.Budget.TaskSeconds != 100 || cur.Budget.Reworks != 1 || cur.Execution.SessionID != "native-session" || len(cur.ExecutionHistory) != 1 {
			t.Fatal("rework identity/budget/history lost")
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	_ = s.store.Update(func(st *core.State) error {
		cur := st.Tasks[task.ID]
		cur.Execution.Status = "completed"
		cur.Status = "needs_changes"
		cur.Budget.Reworks = 2
		if err := s.prepareExecution(st, cur, "too-many", 2, true, nil); err == nil {
			t.Fatal("third rework accepted")
		}
		return nil
	})
}
func TestStaleJobReceiptCannotOverwriteRework(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "stale")
	_ = s.store.Update(func(st *core.State) error {
		st.Tasks[task.ID].Execution = &core.Execution{RequestID: "current", JobID: "new", Status: "running"}
		return nil
	})
	s.applyJob(task.ID, &node.Job{ID: "old", RequestID: "old", TaskID: task.ID, Status: "completed"}, 0)
	got, _ := s.task(task.ID)
	if got.Execution.JobID != "new" || got.Execution.Status != "running" {
		t.Fatal("stale receipt overwrote active job")
	}
}
func TestNativeDialogValidation(t *testing.T) {
	ref := &core.Session{PendingUI: []json.RawMessage{json.RawMessage(`{"id":"a","method":"confirm"}`), json.RawMessage(`{"id":"b","method":"select","options":["yes","no"]}`)}}
	for _, v := range []map[string]any{{"id": "a"}, {"id": "a", "value": "yes"}, {"id": "b", "value": "outside"}, {"id": "b", "cancelled": true, "value": "yes"}} {
		if validateUIResponse(ref, v) == nil {
			t.Fatalf("invalid native response accepted: %v", v)
		}
	}
	for _, v := range []map[string]any{{"id": "a", "confirmed": false}, {"id": "b", "value": "yes"}, {"id": "a", "cancelled": true}} {
		if err := validateUIResponse(ref, v); err != nil {
			t.Fatal(err)
		}
	}
}
func TestScopedExtensionCannotCrossTaskOrRole(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "scope")
	req := httptest.NewRequest("POST", "/internal/tasks/"+task.ID+"/plan", strings.NewReader(`{"requestId":"plan","content":"Plan"}`))
	req.Header.Set("Authorization", "Bearer "+s.scopedToken(task.ID, "architect"))
	req.Header.Set("X-AWF-Role", "reviewer")
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, req)
	if w.Code != 401 {
		t.Fatalf("cross-role token accepted: %d", w.Code)
	}
}
func TestMalformedLoopbackURLRejected(t *testing.T) {
	s := testServer(t)
	cfg := s.cfg
	cfg.DataDir = t.TempDir()
	cfg.InternalURL = "http://127.0.0.1:80@evil.invalid"
	other, err := New(cfg)
	if err == nil {
		other.Close()
		t.Fatal("userinfo URL accepted")
	}
}
func TestAmbiguousDispatchNeverRepostsMissingNodeJob(t *testing.T) {
	s := testServer(t)
	var mu sync.Mutex
	posts := 0
	nodeHTTP := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if serveTestCatalog(w, r) {
			return
		}
		if r.Method == "POST" {
			mu.Lock()
			posts++
			mu.Unlock()
			http.Error(w, "acknowledgement lost", 503)
			return
		}
		http.NotFound(w, r)
	}))
	defer nodeHTTP.Close()
	s.cfg.Nodes["n"] = NodeConfig{URL: nodeHTTP.URL, TokenEnv: "TEST_NODE_TOKEN"}
	task := createTask(t, s, "uncertain-dispatch")
	now := time.Now().UTC()
	_ = s.store.Update(func(st *core.State) error {
		cur := st.Tasks[task.ID]
		cur.Plan = &core.Plan{Revision: 1, Content: "Plan", ConfirmedAt: &now}
		return s.prepareExecution(st, cur, "dispatch-once", 1, false, nil)
	})
	s.monitor(task.ID)
	time.Sleep(2300 * time.Millisecond)
	mu.Lock()
	count := posts
	mu.Unlock()
	if count != 1 {
		t.Fatalf("ambiguous POST retried %d times", count)
	}
	cur, _ := s.task(task.ID)
	if !cur.Execution.DispatchAttempted || cur.Status != "needs_verification" {
		t.Fatalf("unknown result hidden: %+v", cur.Execution)
	}
}
func TestCancelBeforeDispatchDoesNotStartJob(t *testing.T) {
	s := testServer(t)
	var mu sync.Mutex
	posts := 0
	nodeHTTP := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if serveTestCatalog(w, r) {
			return
		}
		if r.Method == "POST" {
			mu.Lock()
			posts++
			mu.Unlock()
		}
		http.NotFound(w, r)
	}))
	defer nodeHTTP.Close()
	s.cfg.Nodes["n"] = NodeConfig{URL: nodeHTTP.URL, TokenEnv: "TEST_NODE_TOKEN"}
	task := createTask(t, s, "cancel-before-dispatch")
	now := time.Now().UTC()
	_ = s.store.Update(func(st *core.State) error {
		cur := st.Tasks[task.ID]
		cur.Plan = &core.Plan{Revision: 1, Content: "Plan", ConfirmedAt: &now}
		if err := s.prepareExecution(st, cur, "never-dispatch", 1, false, nil); err != nil {
			return err
		}
		cur.Execution.CancelRequested = true
		return nil
	})
	s.monitor(task.ID)
	time.Sleep(100 * time.Millisecond)
	mu.Lock()
	count := posts
	mu.Unlock()
	if count != 0 {
		t.Fatal("cancelled undispatched work started")
	}
	cur, _ := s.task(task.ID)
	if cur.Status != "cancelled" {
		t.Fatal(cur.Status)
	}
}
func TestStaleExecutionActionsRejected(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "target-binding")
	_ = s.store.Update(func(st *core.State) error {
		st.Tasks[task.ID].Execution = &core.Execution{RequestID: "current", JobID: "current-job", Status: "running"}
		return nil
	})
	for _, action := range []string{"execution/cancel", "review", "rework"} {
		w := call(t, s, "POST", "/v1/tasks/"+task.ID+"/"+action, actionInput{RequestID: "stale-" + strings.ReplaceAll(action, "/", "-"), ExecutionRequestID: "previous"})
		if w.Code != 409 {
			t.Fatalf("stale %s accepted: %d", action, w.Code)
		}
	}
	cur, _ := s.task(task.ID)
	if cur.Execution.CancelRequested {
		t.Fatal("stale action cancelled current execution")
	}
}
func TestPendingNativeReservationBlocksOtherTask(t *testing.T) {
	s := testServer(t)
	first := createTask(t, s, "pending-one")
	second := createTask(t, s, "pending-two")
	_ = s.store.Update(func(st *core.State) error { st.Tasks[first.ID].Sessions["architect"].Pending = true; return nil })
	w := call(t, s, "POST", "/v1/tasks/"+second.ID+"/messages", actionInput{RequestID: "second-message", Role: "architect", Text: "Start planning"})
	if w.Code != 409 {
		t.Fatalf("cross-task pending native reservation ignored: %d", w.Code)
	}
	cur, _ := s.task(first.ID)
	if cur.Sessions["architect"].Busy {
		t.Fatal("pending was mislabeled as observed native busy")
	}
}
func TestConcurrentFirstPromptsReserveProjectAtomically(t *testing.T) {
	s := testServer(t)
	one := createTask(t, s, "concurrent-prompt-one")
	two := createTask(t, s, "concurrent-prompt-two")
	s.mu.Lock()
	s.closing = true
	s.mu.Unlock()
	start := make(chan struct{})
	results := make(chan int, 2)
	for i, id := range []string{one.ID, two.ID} {
		go func(i int, id string) {
			<-start
			w := call(t, s, "POST", "/v1/tasks/"+id+"/messages", actionInput{RequestID: fmt.Sprintf("message-%d", i), Role: "architect", Text: "Plan"})
			results <- w.Code
		}(i, id)
	}
	close(start)
	a, b := <-results, <-results
	if !((a == 202 && b == 409) || (a == 409 && b == 202)) {
		t.Fatalf("first prompts both reserved or failed: %d %d", a, b)
	}
}
func TestConcurrentRolePromptsReserveOneRole(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "concurrent-roles")
	_ = s.store.Update(func(st *core.State) error {
		st.Tasks[task.ID].Sessions["reviewer"] = &core.Session{ID: core.ID()}
		return nil
	})
	s.mu.Lock()
	s.closing = true
	s.mu.Unlock()
	start := make(chan struct{})
	results := make(chan int, 2)
	for _, role := range []string{"architect", "reviewer"} {
		go func(role string) {
			<-start
			w := call(t, s, "POST", "/v1/tasks/"+task.ID+"/messages", actionInput{RequestID: "message-" + role, Role: role, Text: "Discuss"})
			results <- w.Code
		}(role)
	}
	close(start)
	a, b := <-results, <-results
	if !((a == 202 && b == 409) || (a == 409 && b == 202)) {
		t.Fatalf("roles overlapped: %d %d", a, b)
	}
}
func TestNativeEventDoesNotClearOtherInFlightPrompt(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "inflight")
	_ = s.store.Update(func(st *core.State) error {
		ref := st.Tasks[task.ID].Sessions["architect"]
		ref.ProcessID = "process"
		ref.PendingCommands = []string{"first", "second"}
		refreshPending(ref)
		return nil
	})
	s.piEvent(task.ID, "architect", "process", json.RawMessage(`{"type":"agent_start"}`))
	_ = s.store.Update(func(st *core.State) error {
		settleCommand(st.Tasks[task.ID].Sessions["architect"], "first")
		return nil
	})
	cur, _ := s.task(task.ID)
	if !cur.Sessions["architect"].Pending || len(cur.Sessions["architect"].PendingCommands) != 1 {
		t.Fatal("one ACK cleared another pending command")
	}
	s.piEvent(task.ID, "architect", "old-process", json.RawMessage(`{"type":"awf_process_exit"}`))
	cur, _ = s.task(task.ID)
	if !cur.Sessions["architect"].Busy {
		t.Fatal("old process exit clobbered current native state")
	}
}
func TestNativeDialogTimeoutResumesAccounting(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "dialog-timeout")
	_ = s.store.Update(func(st *core.State) error {
		ref := st.Tasks[task.ID].Sessions["architect"]
		ref.ProcessID = "process"
		ref.Streaming = true
		ref.Busy = true
		return nil
	})
	s.piEvent(task.ID, "architect", "process", json.RawMessage(`{"type":"extension_ui_request","id":"expired","method":"confirm","timeout":5}`))
	time.Sleep(30 * time.Millisecond)
	cur, _ := s.task(task.ID)
	ref := cur.Sessions["architect"]
	if len(ref.PendingUI) != 0 || cur.Budget.ActiveSince == nil {
		t.Fatal("dialog timeout did not clear wait and resume accounting")
	}
	if validateUIResponse(ref, map[string]any{"id": "expired", "confirmed": true}) == nil {
		t.Fatal("expired native dialog accepted")
	}
}
func TestDefaultSinglePiCompletionDoesNotCreateReviewer(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "single-pi")
	if task.Settings.Reviewer != "disabled" || s.cfg.MaxPiProcesses != 1 {
		t.Fatal("initial path is not single Pi")
	}
	_ = s.store.Update(func(st *core.State) error {
		cur := st.Tasks[task.ID]
		cur.Execution = &core.Execution{RequestID: "run", JobID: "job", Status: "running"}
		return nil
	})
	s.applyJob(task.ID, &node.Job{ID: "job", TaskID: task.ID, RequestID: "run", Status: "completed", SessionID: "native-executor", Evidence: fixtureResultEvidence(task.Branch)}, 0)
	cur, _ := s.task(task.ID)
	if cur.Status != "reporting" || cur.Phase != "execution" || cur.Sessions["reviewer"] != nil {
		t.Fatalf("default execution created review gate: %+v", cur)
	}
	w := call(t, s, "POST", "/v1/tasks/"+task.ID+"/review", actionInput{RequestID: "no-review", ExecutionRequestID: "run"})
	if w.Code != 409 {
		t.Fatalf("default task accepted separate review: %d", w.Code)
	}
	body := string(mustJSON(extensionInput{RequestID: "finish", ExecutionRequestID: "run", Verdict: "done", Summary: "Synthetic native tool fixture assessed", Findings: []string{}, EvidenceChecks: fixtureEvidenceChecks()}))
	req := httptest.NewRequest("POST", "/internal/tasks/"+task.ID+"/finish", strings.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+s.scopedToken(task.ID, "architect"))
	req.Header.Set("X-AWF-Role", "architect")
	w = httptest.NewRecorder()
	s.Handler().ServeHTTP(w, req)
	if w.Code != 202 {
		t.Fatal(w.Body.String())
	}
	cur, _ = s.task(task.ID)
	if cur.Status != "done" || cur.Completion == nil || cur.Completion.SessionID != cur.Sessions["architect"].ID || cur.Sessions["reviewer"] != nil {
		t.Fatal("completion did not stay in original Pi session")
	}
	if cur.GitMerged != nil {
		t.Fatal("completion invented Git merge")
	}
}
func TestSeparateReviewerIsExplicitOptIn(t *testing.T) {
	s := testServer(t)
	cfg := s.cfg
	cfg.DataDir = t.TempDir()
	cfg.EnableReviewer = true
	optional, err := New(cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer optional.Close()
	task := createTask(t, optional, "optional-review")
	if task.Settings.Reviewer != "pi" {
		t.Fatal("explicit reviewer opt-in was ignored")
	}
}
func TestOldPiFindingsCannotAuthorizeNewRoundRework(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "round-bound-rework")
	now := time.Now().UTC()
	err := s.store.Update(func(st *core.State) error {
		cur := st.Tasks[task.ID]
		cur.Plan = &core.Plan{Revision: 1, Content: "Plan", ConfirmedAt: &now}
		cur.Execution = &core.Execution{RequestID: "new-round", Status: "completed"}
		cur.Completion = &core.Completion{Verdict: "needs_changes", ExecutionRequestID: "old-round"}
		cur.Status = "reporting"
		if err := s.prepareExecution(st, cur, "premature-rework", 1, true, nil); err == nil {
			t.Fatal("old Pi findings authorized a later round")
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
}
