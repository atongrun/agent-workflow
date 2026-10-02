package host

import (
	"encoding/json"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
	"github.com/atongrun/agent-workflow/internal/node"
)

func lifecycleCall(t *testing.T, s *Server, taskID, operation, requestID string) *httptest.ResponseRecorder {
	t.Helper()
	return call(t, s, "POST", "/v1/tasks/"+taskID+"/"+operation, lifecycleInput{RequestID: requestID})
}
func TestTaskTrashPreservesHistoryAndOriginalReceipts(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "trash-task")
	other := createTask(t, s, "other-task")
	file := filepath.Join(t.TempDir(), "native.jsonl")
	content := []byte("preserved native history\n")
	if err := os.WriteFile(file, content, 0600); err != nil {
		t.Fatal(err)
	}
	_ = s.store.Update(func(st *core.State) error {
		cur := st.Tasks[task.ID]
		cur.Sessions["architect"].File = file
		cur.Sessions["architect"].Persisted = true
		cur.Plan = &core.Plan{Revision: 3, Content: "original plan"}
		cur.Execution = &core.Execution{RequestID: "run", JobID: "job", Status: "completed", Evidence: []core.Evidence{{Content: "real result"}}}
		cur.ExecutionHistory = []core.Execution{{RequestID: "past", Status: "failed"}}
		cur.Completion = &core.Completion{Verdict: "done", ExecutionRequestID: "run"}
		cur.Status = "done"
		return nil
	})
	before := s.store.Snapshot()
	w := lifecycleCall(t, s, task.ID, "delete", "delete-1")
	if w.Code != 202 {
		t.Fatalf("delete: %d %s", w.Code, w.Body)
	}
	deleted := s.store.Snapshot()
	if deleted.Tasks[task.ID].DeletedAt == nil || deleted.Requests["delete-1"].Status != "completed" {
		t.Fatal("deletion not completed durably")
	}
	for _, path := range []string{"/v1/tasks", "/v1/tasks?deleted=false", "/v1/overview"} {
		w = call(t, s, "GET", path, nil)
		var body struct {
			Tasks []*core.Task `json:"tasks"`
		}
		_ = json.Unmarshal(w.Body.Bytes(), &body)
		if len(body.Tasks) != 1 || body.Tasks[0].ID != other.ID {
			t.Fatalf("deleted task visible in %s: %s", path, w.Body)
		}
	}
	w = call(t, s, "GET", "/v1/tasks?deleted=true", nil)
	var trash struct {
		Tasks []*core.Task `json:"tasks"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &trash)
	if len(trash.Tasks) != 1 || trash.Tasks[0].ID != task.ID {
		t.Fatalf("missing Trash item: %s", w.Body)
	}
	for _, query := range []string{"?deleted=true&deleted=false", "?deleted=yes", "?all=true"} {
		if w = call(t, s, "GET", "/v1/tasks"+query, nil); w.Code != 400 {
			t.Fatal("accepted ambiguous query")
		}
	}
	if w = call(t, s, "GET", "/v1/tasks/"+task.ID, nil); w.Code != 200 {
		t.Fatal("deleted detail not readable")
	}
	for _, op := range []string{"delete", "restore"} {
		request := "delete-1"
		if op == "restore" {
			request = "restore-1"
			w = lifecycleCall(t, s, task.ID, op, request)
			if w.Code != 202 {
				t.Fatalf("restore: %d %s", w.Code, w.Body)
			}
		}
		w = call(t, s, "POST", "/v1/tasks/"+task.ID+"/requests/"+request, map[string]any{"requestId": request, "operation": op, "payload": lifecycleInput{RequestID: request}})
		if w.Code != 200 || !strings.Contains(w.Body.String(), `"status":"completed"`) {
			t.Fatalf("receipt lookup: %s", w.Body)
		}
	}
	// Replaying the old delete after restore is receipt-only, never a new delete.
	if w = lifecycleCall(t, s, task.ID, "delete", "delete-1"); w.Code != 202 {
		t.Fatal(w.Body)
	}
	after := s.store.Snapshot()
	cur := after.Tasks[task.ID]
	old := before.Tasks[task.ID]
	if cur.DeletedAt != nil || cur.ID != old.ID || cur.Sessions["architect"].ID != old.Sessions["architect"].ID || cur.Sessions["architect"].File != file || string(mustJSON(cur.Plan)) != string(mustJSON(old.Plan)) || string(mustJSON(cur.Execution)) != string(mustJSON(old.Execution)) || string(mustJSON(cur.ExecutionHistory)) != string(mustJSON(old.ExecutionHistory)) || string(mustJSON(cur.Completion)) != string(mustJSON(old.Completion)) {
		t.Fatal("restore changed history or identity")
	}
	if string(mustJSON(after.Requests["trash-task"])) != string(mustJSON(before.Requests["trash-task"])) {
		t.Fatal("historical request changed")
	}
	if b, err := os.ReadFile(file); err != nil || string(b) != string(content) {
		t.Fatal("native file removed or changed")
	}
	if w = lifecycleCall(t, s, task.ID, "restore", "delete-1"); w.Code != 409 {
		t.Fatal("request ID reused across operations")
	}
}

func TestTaskDeleteRejectsActiveAndUncertainWork(t *testing.T) {
	cases := map[string]func(*core.State, *core.Task){
		"execution":    func(_ *core.State, t *core.Task) { t.Execution = &core.Execution{Status: "running"} },
		"queued":       func(_ *core.State, t *core.Task) { t.Status = "queued" },
		"uncertain":    func(_ *core.State, t *core.Task) { t.Execution = &core.Execution{Status: "uncertain"} },
		"reporting":    func(_ *core.State, t *core.Task) { t.Status = "reporting" },
		"review":       func(_ *core.State, t *core.Task) { t.Status = "review" },
		"busy":         func(_ *core.State, t *core.Task) { t.Sessions["architect"].Busy = true },
		"pending":      func(_ *core.State, t *core.Task) { t.Sessions["architect"].Pending = true },
		"streaming":    func(_ *core.State, t *core.Task) { t.Sessions["architect"].Streaming = true },
		"compacting":   func(_ *core.State, t *core.Task) { t.Sessions["architect"].Compacting = true },
		"awaiting":     func(_ *core.State, t *core.Task) { t.Sessions["architect"].AwaitingStart = true },
		"native_queue": func(_ *core.State, t *core.Task) { t.Sessions["architect"].NativeQueued = 1 },
		"dialog": func(_ *core.State, t *core.Task) {
			t.Sessions["architect"].PendingUI = []json.RawMessage{json.RawMessage(`{"id":"dialog"}`)}
		},
		"control": func(_ *core.State, t *core.Task) { t.Sessions["architect"].PendingCommands = []string{"control"} },
		"receipt": func(st *core.State, t *core.Task) {
			st.Requests["pending"] = &core.Request{TaskID: t.ID, Operation: "pi/model", Status: "needs_verification"}
		},
		"native_prompt": func(st *core.State, t *core.Task) {
			st.Requests["pending"] = &core.Request{TaskID: t.ID, Operation: "messages", Status: "accepted_native"}
		},
		"permission": func(_ *core.State, t *core.Task) {
			t.Execution = &core.Execution{Status: "completed", PendingPermissions: []json.RawMessage{json.RawMessage(`{}`)}}
		},
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			s := testServer(t)
			task := createTask(t, s, "active")
			_ = s.store.Update(func(st *core.State) error { mutate(st, st.Tasks[task.ID]); return nil })
			w := lifecycleCall(t, s, task.ID, "delete", "blocked-delete")
			if w.Code != 409 {
				t.Fatalf("accepted active delete: %s", w.Body)
			}
			st := s.store.Snapshot()
			if st.Tasks[task.ID].DeletedAt != nil || st.Requests["blocked-delete"] != nil {
				t.Fatal("rejected delete left state")
			}
		})
	}
}

func TestDeletedTaskFencesNewMutationsAndLateCallbacks(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "fence")
	if w := lifecycleCall(t, s, task.ID, "delete", "delete"); w.Code != 202 {
		t.Fatal(w.Body)
	}
	before := s.store.Snapshot()
	for _, op := range []string{"messages", "plan/confirm", "start", "rework", "review", "execution/cancel", "pi/ui-response"} {
		w := call(t, s, "POST", "/v1/tasks/"+task.ID+"/"+op, actionInput{RequestID: "new-" + strings.ReplaceAll(op, "/", "-"), Text: "new"})
		if w.Code != 409 || !strings.Contains(w.Body.String(), "task_deleted") {
			t.Fatalf("%s: %d %s", op, w.Code, w.Body)
		}
	}
	w := call(t, s, "PATCH", "/v1/tasks/"+task.ID+"/target", targetInput{RequestID: "target"})
	if w.Code != 409 || !strings.Contains(w.Body.String(), "task_deleted") {
		t.Fatal(w.Body)
	}
	for _, op := range []string{"model", "compact", "abort"} {
		w = call(t, s, "POST", "/v1/tasks/"+task.ID+"/pi/"+op, piControlInput{RequestID: "control-" + op, Role: "architect", ExpectedSessionID: "s", ExpectedProcessID: "p"})
		if w.Code != 409 || !strings.Contains(w.Body.String(), "task_deleted") {
			t.Fatalf("%s: %d %s", op, w.Code, w.Body)
		}
	}
	if _, err := s.client(task.ID, "architect"); err == nil {
		t.Fatal("started Pi for deleted task")
	}
	if w = call(t, s, "GET", "/v1/tasks/"+task.ID+"/messages", nil); w.Code != 409 {
		t.Fatal(w.Body)
	}
	s.piEvent(task.ID, "architect", "", json.RawMessage(`{"type":"agent_start"}`))
	s.store.NativeEvent(task.ID, "architect", "", map[string]string{"text": "late"})
	s.applyJob(task.ID, &node.Job{TaskID: task.ID, Status: "running"}, 0)
	s.beginExecutionSummary(task.ID)
	s.recoverExecutions()
	after := s.store.Snapshot()
	if string(mustJSON(before.Tasks[task.ID])) != string(mustJSON(after.Tasks[task.ID])) || before.Sequence != after.Sequence {
		t.Fatal("late work mutated deleted task")
	}
}

func TestTaskDeleteClosesIdleProcessAndFencesConcurrentReads(t *testing.T) {
	s, task, _, _, _ := piControlFixture(t, "")
	s.mu.Lock()
	client := s.clients[task.ID+":architect"]
	s.mu.Unlock()
	var wg sync.WaitGroup
	for range 10 {
		wg.Add(1)
		go func() { defer wg.Done(); _, _ = s.client(task.ID, "architect") }()
	}
	w := lifecycleCall(t, s, task.ID, "delete", "delete-idle")
	wg.Wait()
	if w.Code != 202 || client.Alive() {
		t.Fatalf("idle process still alive: %d %s", w.Code, w.Body)
	}
	st := s.store.Snapshot()
	if st.Tasks[task.ID].Sessions["architect"].Available || st.Requests["delete-idle"].Status != "completed" {
		t.Fatal("deletion receipt/process state incomplete")
	}
	if w = lifecycleCall(t, s, task.ID, "restore", "restore-idle"); w.Code != 202 {
		t.Fatal(w.Body)
	}
	s.mu.Lock()
	count := len(s.clients)
	s.mu.Unlock()
	if count != 0 {
		t.Fatal("restore automatically resumed Pi")
	}
	if st.Tasks[task.ID].Sessions["architect"].ID != task.Sessions["architect"].ID {
		t.Fatal("native ID changed")
	}
}

func TestTaskDeleteRestartAndUncertainReceipt(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "restart")
	if w := lifecycleCall(t, s, task.ID, "delete", "delete-restart"); w.Code != 202 {
		t.Fatal(w.Body)
	}
	cfg := s.cfg
	s.Close()
	restarted, err := New(cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer restarted.Close()
	if restarted.store.Snapshot().Tasks[task.ID].DeletedAt == nil {
		t.Fatal("Trash lost on restart")
	}
	if w := lifecycleCall(t, restarted, task.ID, "delete", "delete-restart"); w.Code != 202 {
		t.Fatal(w.Body)
	}
	_ = restarted.store.Update(func(st *core.State) error { st.Requests["delete-restart"].Status = "needs_verification"; return nil })
	if w := lifecycleCall(t, restarted, task.ID, "restore", "unsafe-restore"); w.Code != 409 {
		t.Fatal("restored before exit verified")
	}
}

func TestTaskDeleteRacesReservation(t *testing.T) {
	for range 15 {
		s := testServer(t)
		task := createTask(t, s, "race")
		start := make(chan struct{})
		var wg sync.WaitGroup
		wg.Add(1)
		go func() {
			defer wg.Done()
			<-start
			_, _ = s.reserve("queued-work", task.ID, "messages", nil, func(st *core.State) error { st.Tasks[task.ID].Sessions["architect"].Pending = true; return nil })
		}()
		close(start)
		w := lifecycleCall(t, s, task.ID, "delete", "delete-race")
		wg.Wait()
		st := s.store.Snapshot()
		if st.Tasks[task.ID].DeletedAt != nil && st.Requests["queued-work"] != nil {
			t.Fatalf("delete and new work both won: %s", w.Body)
		}
		s.Close()
	}
}

func TestDeletedTaskNeverRecoversAutomaticExecution(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "no-auto")
	now := time.Now().UTC()
	_ = s.store.Update(func(st *core.State) error {
		cur := st.Tasks[task.ID]
		cur.DeletedAt = &now
		cur.Status = "reporting"
		cur.Execution = &core.Execution{Status: "completed", RequestID: "old"}
		return nil
	})
	before := s.store.Snapshot()
	s.recoverExecutions()
	s.beginExecutionSummary(task.ID)
	s.beginAutomaticReview(task.ID)
	if len(s.store.Snapshot().Requests) != len(before.Requests) {
		t.Fatal("deleted task automatically dispatched")
	}
}

func TestTaskDeleteWaitsForInflightPiStartup(t *testing.T) {
	s, task, _, log, release := piControlFixture(t, "")
	s.mu.Lock()
	old := s.clients[task.ID+":architect"]
	s.mu.Unlock()
	_ = old.Close()
	closeDeadline := time.Now().Add(5 * time.Second)
	for old.Alive() && time.Now().Before(closeDeadline) {
		time.Sleep(5 * time.Millisecond)
	}
	if old.Alive() {
		t.Fatal("fixture did not close")
	}
	launcher, err := os.ReadFile(s.cfg.PiBinary)
	if err != nil {
		t.Fatal(err)
	}
	launcher = []byte(strings.Replace(string(launcher), "PI_CONTROL_TEST_MODE=''", "PI_CONTROL_TEST_MODE='hold_state'", 1))
	if err := os.WriteFile(s.cfg.PiBinary, launcher, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(log, nil, 0600); err != nil {
		t.Fatal(err)
	}
	defer os.WriteFile(release, nil, 0600)
	started := make(chan error, 1)
	go func() { _, err := s.client(task.ID, "architect"); started <- err }()
	deadline := time.Now().Add(5 * time.Second)
	for {
		b, _ := os.ReadFile(log)
		if strings.Contains(string(b), "get_state") {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("fixture startup did not reach native read")
		}
		time.Sleep(5 * time.Millisecond)
	}
	deleted := make(chan *httptest.ResponseRecorder, 1)
	go func() { deleted <- lifecycleCall(t, s, task.ID, "delete", "delete-startup") }()
	select {
	case <-deleted:
		t.Fatal("delete raced past process startup")
	case <-time.After(20 * time.Millisecond):
	}
	if err := os.WriteFile(release, nil, 0600); err != nil {
		t.Fatal(err)
	}
	if err := <-started; err != nil {
		t.Fatal(err)
	}
	if w := <-deleted; w.Code != 202 {
		t.Fatal(w.Body)
	}
	s.mu.Lock()
	count := len(s.clients)
	s.mu.Unlock()
	if count != 0 || s.store.Snapshot().Requests["delete-startup"].Status != "completed" {
		t.Fatal("startup process survived deletion")
	}
}

func TestTaskDeleteCoordinatesIdleEviction(t *testing.T) {
	s, task, _, _, _ := piControlFixture(t, "")
	other := createTask(t, s, "eviction-other")
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		if _, err := s.client(other.ID, "architect"); err != nil {
			t.Errorf("other task startup: %v", err)
		}
	}()
	w := lifecycleCall(t, s, task.ID, "delete", "delete-eviction")
	wg.Wait()
	if w.Code != 202 {
		t.Fatal(w.Body)
	}
	s.mu.Lock()
	deletedClient := s.clients[task.ID+":architect"]
	otherClient := s.clients[other.ID+":architect"]
	s.mu.Unlock()
	if deletedClient != nil || otherClient == nil || !otherClient.Alive() {
		t.Fatal("delete/evict affected the wrong process")
	}
}

func TestTaskRestoreRejectsOldExecutionCallbacks(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "old-callback")
	_ = s.store.Update(func(st *core.State) error {
		cur := st.Tasks[task.ID]
		cur.Status = "done"
		cur.Execution = &core.Execution{RequestID: "run", JobID: "job", Status: "completed"}
		return nil
	})
	if w := lifecycleCall(t, s, task.ID, "delete", "delete-callback"); w.Code != 202 {
		t.Fatal(w.Body)
	}
	if w := lifecycleCall(t, s, task.ID, "restore", "restore-callback"); w.Code != 202 {
		t.Fatal(w.Body)
	}
	before := s.store.Snapshot()
	s.applyJob(task.ID, &node.Job{TaskID: task.ID, RequestID: "run", ID: "job", Status: "running"}, 0)
	s.beginExecutionSummary(task.ID)
	if after := s.store.Snapshot(); string(mustJSON(before.Tasks[task.ID])) != string(mustJSON(after.Tasks[task.ID])) {
		t.Fatal("old execution callback resumed restored task")
	}
}

func TestTaskRestoreFencesDelayedExtensionRequest(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "delayed-extension")
	// This fully formed request was sent by the original native lifecycle but
	// did not reach the Host handler until after deletion and restoration.
	req := httptest.NewRequest("POST", "/internal/tasks/"+task.ID+"/plan", strings.NewReader(`{"requestId":"late-plan","content":"obsolete native plan"}`))
	req.Header.Set("Authorization", "Bearer "+s.scopedToken(task.ID, "architect"))
	req.Header.Set("X-AWF-Role", "architect")
	if w := lifecycleCall(t, s, task.ID, "delete", "delete-extension"); w.Code != 202 {
		t.Fatal(w.Body)
	}
	if w := lifecycleCall(t, s, task.ID, "restore", "restore-extension"); w.Code != 202 {
		t.Fatal(w.Body)
	}
	before := s.store.Snapshot()
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, req)
	if w.Code != 409 {
		t.Fatalf("old extension request mutated restored task: %d %s", w.Code, w.Body)
	}
	after := s.store.Snapshot()
	if after.Requests["late-plan"] != nil || string(mustJSON(before.Tasks[task.ID])) != string(mustJSON(after.Tasks[task.ID])) {
		t.Fatal("late extension request changed state")
	}
}

func TestExtensionLifecycleLegacyReplayAndFreshRestore(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "extension-generation")
	invoke := func(body string) *httptest.ResponseRecorder {
		req := httptest.NewRequest("POST", "/internal/tasks/"+task.ID+"/plan", strings.NewReader(body))
		req.Header.Set("Authorization", "Bearer "+s.scopedToken(task.ID, "architect"))
		req.Header.Set("X-AWF-Role", "architect")
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, req)
		return w
	}
	legacy := `{"requestId":"original-plan","content":"original native plan"}`
	if w := invoke(legacy); w.Code != 202 {
		t.Fatal(w.Body)
	}
	originalReceipt := string(mustJSON(s.store.Snapshot().Requests["original-plan"]))
	// Explicit zero from the new extension serializes identically to historical
	// input with the field absent, keeping the original idempotency fingerprint.
	if w := invoke(`{"requestId":"original-plan","content":"original native plan","lifecycleRevision":0}`); w.Code != 202 {
		t.Fatal(w.Body)
	}
	if w := lifecycleCall(t, s, task.ID, "delete", "delete-generation"); w.Code != 202 {
		t.Fatal(w.Body)
	}
	if w := lifecycleCall(t, s, task.ID, "restore", "restore-generation"); w.Code != 202 {
		t.Fatal(w.Body)
	}
	if w := invoke(legacy); w.Code != 202 {
		t.Fatal("historical extension receipt no longer replayable")
	}
	if string(mustJSON(s.store.Snapshot().Requests["original-plan"])) != originalReceipt {
		t.Fatal("historical receipt changed")
	}
	for _, body := range []string{`{"requestId":"old-zero","content":"late","lifecycleRevision":0}`, `{"requestId":"future-generation","content":"late","lifecycleRevision":4}`} {
		if w := invoke(body); w.Code != 409 {
			t.Fatal("noncurrent lifecycle accepted")
		}
	}
	if w := invoke(`{"requestId":"fresh-plan","content":"fresh restored plan","lifecycleRevision":2}`); w.Code != 202 {
		t.Fatal(w.Body)
	}
	if s.store.Snapshot().Tasks[task.ID].Plan.Content != "fresh restored plan" {
		t.Fatal("fresh restored native generation blocked")
	}
}
