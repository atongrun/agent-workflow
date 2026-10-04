package host

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
)

func enableMaintenance(s *Server) { s.cfg.EnableMaintenance = true }
func maintenanceCall(t *testing.T, s *Server, action, request, owner string, revision int) *httptest.ResponseRecorder {
	t.Helper()
	in := maintenanceInput{RequestID: request, ExpectedRevision: &revision, OwnerRequestID: owner}
	if action == "begin" {
		in.TargetManifestSHA256 = strings.Repeat("a", 64)
	}
	return call(t, s, "POST", "/v1/maintenance/"+action, in)
}
func requireMaintenanceCode(t *testing.T, w *httptest.ResponseRecorder, want int) {
	t.Helper()
	if w.Code != want {
		t.Fatalf("maintenance HTTP%d want%d: %s", w.Code, want, w.Body.String())
	}
}
func TestMaintenanceBeginSealReleaseAndExactRetries(t *testing.T) {
	s := testServer(t)
	enableMaintenance(s)
	task := createTask(t, s, "before-maintenance")
	requireMaintenanceCode(t, maintenanceCall(t, s, "begin", "lease", "", 0), 200)
	requireMaintenanceCode(t, maintenanceCall(t, s, "begin", "lease", "", 0), 200)
	requireMaintenanceCode(t, call(t, s, "POST", "/v1/tasks", createInput{RequestID: "new-task", Title: "New"}), 409)
	// Historical receipt remains readable without a new reservation/effect.
	requireMaintenanceCode(t, call(t, s, "POST", "/v1/tasks", createInput{RequestID: "before-maintenance", Title: "Task", ProjectID: "p", NodeID: "n", Repository: "example/repo", Goal: "Make an authorized small change", AcceptanceCriteria: "Run relevant tests"}), 202)
	requireMaintenanceCode(t, maintenanceCall(t, s, "seal", "seal-wrong", "other", 1), 409)
	requireMaintenanceCode(t, maintenanceCall(t, s, "seal", "sealed", "lease", 1), 200)
	before, _ := os.ReadFile(filepath.Join(s.cfg.DataDir, "state.json"))
	requireMaintenanceCode(t, call(t, s, "GET", "/v1/maintenance", nil), 200)
	requireMaintenanceCode(t, call(t, s, "GET", "/v1/tasks/"+task.ID, nil), 200)
	requireMaintenanceCode(t, maintenanceCall(t, s, "seal", "sealed", "lease", 1), 200)
	after, _ := os.ReadFile(filepath.Join(s.cfg.DataDir, "state.json"))
	if !bytes.Equal(before, after) {
		t.Fatal("sealed read/retry changed bytes")
	}
	if err := s.store.Update(func(st *core.State) error { st.Tasks[task.ID].Title = "unsafe background write"; return nil }); err == nil {
		t.Fatal("sealed store admitted background mutation")
	}
	requireMaintenanceCode(t, maintenanceCall(t, s, "end", "stale-end", "lease", 1), 409)
	requireMaintenanceCode(t, maintenanceCall(t, s, "end", "released", "lease", 2), 200)
	requireMaintenanceCode(t, maintenanceCall(t, s, "begin", "second-lease", "", 3), 200)
	// Retry of an old end cannot release the newer owner.
	requireMaintenanceCode(t, maintenanceCall(t, s, "end", "released", "lease", 2), 200)
	if st := s.store.Snapshot(); st.Maintenance.OwnerRequestID != "second-lease" || st.Maintenance.Phase != "draining" {
		t.Fatal("old end released new lease")
	}
}
func TestMaintenanceDrainExistingWorkAndFailClosedIdle(t *testing.T) {
	for _, mode := range []string{"pending", "streaming", "startup", "reporting", "unknown-task", "unknown-request", "question", "permission", "orphan-request"} {
		t.Run(mode, func(t *testing.T) {
			s := testServer(t)
			enableMaintenance(s)
			task := createTask(t, s, "task")
			if err := s.store.Update(func(st *core.State) error {
				cur := st.Tasks[task.ID]
				switch mode {
				case "pending":
					cur.Sessions["architect"].Pending = true
				case "streaming":
					cur.Sessions["architect"].Streaming = true
				case "reporting":
					cur.Status = "reporting"
				case "unknown-task":
					cur.Status = "future-unknown"
				case "unknown-request":
					st.Requests["uncertain"] = &core.Request{ID: "uncertain", TaskID: task.ID, Operation: "future", Status: "needs_verification"}
				case "question":
					cur.Execution = &core.Execution{Status: "failed", PendingQuestions: []json.RawMessage{json.RawMessage(`{"id":"q"}`)}}
				case "permission":
					cur.Execution = &core.Execution{Status: "failed", PendingPermissions: []json.RawMessage{json.RawMessage(`{"id":"p"}`)}}
				case "orphan-request":
					st.Requests["orphan"] = &core.Request{ID: "orphan", TaskID: "missing", Status: "accepted"}
				}
				return nil
			}); err != nil {
				t.Fatal(err)
			}
			if mode == "startup" {
				s.mu.Lock()
				s.starting++
				s.mu.Unlock()
				defer func() { s.mu.Lock(); s.starting--; s.mu.Unlock() }()
			}
			requireMaintenanceCode(t, maintenanceCall(t, s, "begin", "lease", "", 0), 200)
			requireMaintenanceCode(t, maintenanceCall(t, s, "seal", "seal", "lease", 1), 409)
			requireMaintenanceCode(t, maintenanceCall(t, s, "end", "release", "lease", 1), 200)
		})
	}
	s := testServer(t)
	enableMaintenance(s)
	active := createTask(t, s, "active")
	idle := createTask(t, s, "idle")
	if err := s.store.Update(func(st *core.State) error { st.Tasks[active.ID].Sessions["architect"].Busy = true; return nil }); err != nil {
		t.Fatal(err)
	}
	requireMaintenanceCode(t, maintenanceCall(t, s, "begin", "lease", "", 0), 200)
	st := s.store.Snapshot()
	if maintenanceAdmission(&st, active.ID, "extension/plan") != nil || maintenanceAdmission(&st, active.ID, "execution/question-reply/q") != nil {
		t.Fatal("existing work cannot drain")
	}
	for _, op := range []string{"messages", "start", "rework", "review", "pi/resume", "pi/model", "settings", "model-settings", "extension/future"} {
		if maintenanceAdmission(&st, active.ID, op) == nil {
			t.Fatal("new work admitted", op)
		}
	}
	if maintenanceAdmission(&st, idle.ID, "extension/plan") == nil {
		t.Fatal("idle task invented drain authority")
	}
}
func TestMaintenanceSurvivesRestartAndDisabledConfiguration(t *testing.T) {
	s := testServer(t)
	enableMaintenance(s)
	createTask(t, s, "task")
	requireMaintenanceCode(t, maintenanceCall(t, s, "begin", "lease", "", 0), 200)
	requireMaintenanceCode(t, maintenanceCall(t, s, "seal", "seal", "lease", 1), 200)
	before, _ := os.ReadFile(filepath.Join(s.cfg.DataDir, "state.json"))
	cfg := s.cfg
	s.Close()
	cfg.EnableMaintenance = false
	reopened, err := New(cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	after, _ := os.ReadFile(filepath.Join(cfg.DataDir, "state.json"))
	if !bytes.Equal(before, after) {
		t.Fatal("restart changed sealed durable view")
	}
	requireMaintenanceCode(t, call(t, reopened, "POST", "/v1/tasks", createInput{RequestID: "blocked", Title: "New"}), 409)
	requireMaintenanceCode(t, call(t, reopened, "GET", "/v1/maintenance", nil), 200)
	requireMaintenanceCode(t, maintenanceCall(t, reopened, "end", "release", "lease", 2), 200)
	requireMaintenanceCode(t, call(t, reopened, "POST", "/v1/tasks", createInput{RequestID: "allowed", Title: "New"}), 202)
}
func TestMaintenanceConcurrentCreationAndSealIsAtomic(t *testing.T) {
	s := testServer(t)
	enableMaintenance(s)
	var wg sync.WaitGroup
	responses := make(chan *httptest.ResponseRecorder, 16)
	wg.Add(1)
	go func() { defer wg.Done(); responses <- maintenanceCall(t, s, "begin", "lease", "", 0) }()
	for i := 0; i < 15; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			b := createInput{RequestID: strings.Repeat("x", i+1), Title: "Task"}
			responses <- call(t, s, "POST", "/v1/tasks", b)
		}(i)
	}
	wg.Wait()
	close(responses)
	for w := range responses {
		if w.Code != 200 && w.Code != 202 && w.Code != 409 {
			t.Fatal(w.Code, w.Body.String())
		}
	}
	requireMaintenanceCode(t, maintenanceCall(t, s, "seal", "seal", "lease", 1), 200)
	for _, op := range []string{"start", "messages", "extension/finish", "execution_result"} {
		_, err := s.reserve("late-"+op, "", ""+op, nil, func(*core.State) error { t.Error("sealed effect callback ran"); return nil })
		if err == nil {
			t.Fatal("sealed reservation admitted", op)
		}
	}
}
func TestMaintenanceDefaultsAuthValidationAndBuildEvidence(t *testing.T) {
	s := testServer(t)
	requireMaintenanceCode(t, call(t, s, "GET", "/v1/maintenance", nil), 404)
	enableMaintenance(s)
	req := httptest.NewRequest(http.MethodPost, "/v1/maintenance/begin", strings.NewReader(`{}`))
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, req)
	requireMaintenanceCode(t, w, 401)
	requireMaintenanceCode(t, call(t, s, "POST", "/v1/maintenance/begin", map[string]any{"requestId": "x"}), 400)
	requireMaintenanceCode(t, call(t, s, "POST", "/v1/maintenance/begin", map[string]any{"requestId": "x", "expectedRevision": 0, "targetManifestSHA256": "latest"}), 400)
	w = call(t, s, "GET", "/v1/maintenance", nil)
	requireMaintenanceCode(t, w, 200)
	var data map[string]json.RawMessage
	if json.Unmarshal(w.Body.Bytes(), &data) != nil || string(data["nativeActivationReady"]) != "false" {
		t.Fatal("claimed native readiness")
	}
}

func TestMaintenanceSerializesNativeSendAndRejectsLateEffects(t *testing.T) {
	s := testServer(t)
	enableMaintenance(s)
	entered, release := make(chan struct{}), make(chan struct{})
	var sends int
	n := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		sends++
		close(entered)
		<-release
		w.Write([]byte(`{}`))
	}))
	defer n.Close()
	s.cfg.Nodes["maintenance-fixture"] = NodeConfig{URL: n.URL}
	requireMaintenanceCode(t, maintenanceCall(t, s, "begin", "lease", "", 0), 200)
	finished := make(chan error, 1)
	go func() {
		_, err := s.nodeCall(context.Background(), "maintenance-fixture", "POST", "/cancel", nil, nil)
		finished <- err
	}()
	<-entered
	sealed := make(chan *httptest.ResponseRecorder, 1)
	go func() { sealed <- maintenanceCall(t, s, "seal", "seal", "lease", 1) }()
	select {
	case <-sealed:
		t.Fatal("sealed while native effect was in flight")
	case <-time.After(30 * time.Millisecond):
	}
	close(release)
	if err := <-finished; err != nil {
		t.Fatal(err)
	}
	requireMaintenanceCode(t, <-sealed, 200)
	if _, err := s.nodeCall(context.Background(), "maintenance-fixture", "POST", "/late", nil, nil); err == nil {
		t.Fatal("late cancel reached native node")
	}
	// These wrappers must fail before dereferencing a native client, proving
	// stale budget/queued UI callbacks cannot send once seal wins.
	if s.fencedPiStop(context.Background(), nil) == nil {
		t.Fatal("late budget stop admitted")
	}
	if s.fencedPiRespond(nil, "expired", nil) == nil {
		t.Fatal("late UI response admitted")
	}
	if _, err := s.fencedPiBegin(nil, "abort", nil); err == nil {
		t.Fatal("late control admitted")
	}
	if sends != 1 {
		t.Fatal("unexpected native writes", sends)
	}
	before := s.store.Snapshot().Sequence
	s.store.Event("", "late", nil)
	s.store.NativeEvent("", "architect", "late", nil)
	if s.store.Snapshot().Sequence != before {
		t.Fatal("late event changed sealed view")
	}
}
