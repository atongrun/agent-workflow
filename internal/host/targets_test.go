package host

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
)

func ptr(i int) *int { return &i }
func draftTask(t *testing.T, s *Server, id string) *core.Task {
	t.Helper()
	w := call(t, s, "POST", "/v1/tasks", map[string]any{"requestId": id, "title": "Discuss a change"})
	if w.Code != 202 {
		t.Fatalf("create draft: %d %s", w.Code, w.Body.String())
	}
	var out struct {
		Task *core.Task `json:"task"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &out); err != nil {
		t.Fatal(err)
	}
	return out.Task
}
func bindTask(t *testing.T, s *Server, task *core.Task, request string) *core.Task {
	t.Helper()
	w := call(t, s, "PATCH", "/v1/tasks/"+task.ID+"/target", targetInput{RequestID: request, ExpectedTargetRevision: ptr(task.TargetRevision), Repository: "example/repository", RepositoryID: "12345", ProjectID: "p", NodeID: "n"})
	if w.Code != 202 {
		t.Fatalf("bind: %d %s", w.Code, w.Body.String())
	}
	got, _ := s.task(task.ID)
	return got
}
func planFixture(t *testing.T, s *Server, id string, confirmed bool) {
	t.Helper()
	if err := s.store.Update(func(st *core.State) error {
		p := &core.Plan{Revision: 1, Content: "A concrete scope and acceptance plan"}
		if confirmed {
			now := time.Now().UTC()
			p.ConfirmedAt = &now
		}
		st.Tasks[id].Plan = p
		return nil
	}); err != nil {
		t.Fatal(err)
	}
}
func TestTitleOnlyDraftAndLegacyCreateHash(t *testing.T) {
	s := testServer(t)
	task := draftTask(t, s, "title-only")
	if task.ID == "" || task.PlanID != task.ID || task.PlanningProfile != core.RestrictedPlanning || task.TargetRevision != 0 || task.Goal != "" || task.AcceptanceCriteria != "" || task.Repository != "" || task.ProjectID != "" || task.NodeID != "" || task.Execution != nil {
		t.Fatalf("unexpected draft: %+v", task)
	}
	if len(task.Sessions) != 1 || task.Sessions["architect"].ID == "" {
		t.Fatal("missing automatic session identity")
	}
	before := *task.Sessions["architect"]
	if got := draftTask(t, s, "title-only"); got.ID != task.ID || !reflect.DeepEqual(before, *got.Sessions["architect"]) {
		t.Fatal("duplicate replaced task/session")
	}
	for _, title := range []string{"", " \n\t "} {
		if w := call(t, s, "POST", "/v1/tasks", map[string]any{"requestId": "blank", "title": title}); w.Code != 400 {
			t.Fatal("blank title accepted")
		}
	}
	// This is the exact historical create-input serialization. Do not normalize
	// user input or add non-omitempty fields to the request hash.
	in := createInput{RequestID: "legacy-hash", Title: " Task ", ProjectID: "p", Repository: "old unchecked repository", Goal: " Goal ", AcceptanceCriteria: "Checks", NodeID: "n"}
	original := `{"requestId":"legacy-hash","title":" Task ","projectId":"p","repository":"old unchecked repository","goal":" Goal ","acceptanceCriteria":"Checks","nodeId":"n"}`
	w := call(t, s, "POST", "/v1/tasks", in)
	if w.Code != 202 {
		t.Fatal(w.Body.String())
	}
	hash := sha256.Sum256([]byte(original))
	req := s.store.Snapshot().Requests[in.RequestID]
	if req.Hash != hex.EncodeToString(hash[:]) {
		t.Fatal("legacy create hash changed")
	}
	cfg := s.cfg
	s.Close()
	cfg.Projects = map[string]string{}
	cfg.Nodes = map[string]NodeConfig{}
	restarted, err := New(cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer restarted.Close()
	if w = call(t, restarted, "POST", "/v1/tasks", in); w.Code != 202 {
		t.Fatalf("removed config broke replay: %s", w.Body.String())
	}
	in.Title = "changed"
	if w = call(t, restarted, "POST", "/v1/tasks", in); w.Code != 409 || !strings.Contains(w.Body.String(), "idempotency_conflict") {
		t.Fatalf("mutable config masked hash conflict: %s", w.Body.String())
	}
	got, _ := restarted.task(task.ID)
	if got.ID != task.ID || got.Sessions["architect"].ID != before.ID || got.PlanningProfile != core.RestrictedPlanning {
		t.Fatal("restart changed draft identity/profile")
	}
}
func TestTargetBindingIdempotencyRevisionAndConfirmation(t *testing.T) {
	s := testServer(t)
	task := draftTask(t, s, "binding")
	planFixture(t, s, task.ID, true)
	session := task.Sessions["architect"].ID
	task = bindTask(t, s, task, "bind-first")
	if task.TargetRevision != 1 || task.Plan.ConfirmedAt != nil || task.Status != "awaiting_confirmation" || task.Sessions["architect"].ID != session || task.Execution != nil {
		t.Fatal("binding changed identity or failed to invalidate confirmation")
	}
	in := targetInput{RequestID: "bind-first", ExpectedTargetRevision: ptr(0), Repository: "example/repository", RepositoryID: "12345", ProjectID: "p", NodeID: "n"}
	oldNode := s.cfg.Nodes["n"]
	delete(s.cfg.Nodes, "n")
	if w := call(t, s, "PATCH", "/v1/tasks/"+task.ID+"/target", in); w.Code != 202 {
		t.Fatalf("replay checked removed config: %s", w.Body.String())
	}
	s.cfg.Nodes["n"] = oldNode
	if got, _ := s.task(task.ID); got.TargetRevision != 1 {
		t.Fatal("duplicate binding incremented revision")
	}
	in.Repository = "example/other"
	if w := call(t, s, "PATCH", "/v1/tasks/"+task.ID+"/target", in); w.Code != 409 || !strings.Contains(w.Body.String(), "idempotency_conflict") {
		t.Fatal("changed replay accepted")
	}
	in.RequestID = "stale"
	if w := call(t, s, "PATCH", "/v1/tasks/"+task.ID+"/target", in); w.Code != 409 || !strings.Contains(w.Body.String(), "target_changed") {
		t.Fatal("stale revision accepted")
	}
	in.ExpectedTargetRevision = nil
	if w := call(t, s, "PATCH", "/v1/tasks/"+task.ID+"/target", in); w.Code != 409 {
		t.Fatal("missing revision accepted")
	}
	planFixture(t, s, task.ID, true)
	bindTask(t, s, task, "bind-second")
	if got, _ := s.task(task.ID); got.Plan.ConfirmedAt != nil || got.TargetRevision != 2 {
		t.Fatal("target change retained plan confirmation")
	}
}
func TestTargetConcurrentChangesAndBusyHistoryFreeze(t *testing.T) {
	s := testServer(t)
	task := draftTask(t, s, "binding-race")
	var wg sync.WaitGroup
	var success atomic.Int32
	for _, id := range []string{"save-a", "save-b"} {
		wg.Add(1)
		go func(id string) {
			defer wg.Done()
			w := call(t, s, "PATCH", "/v1/tasks/"+task.ID+"/target", targetInput{RequestID: id, ExpectedTargetRevision: ptr(0), Repository: "example/repository", ProjectID: "p", NodeID: "n"})
			if w.Code == 202 {
				success.Add(1)
			} else if w.Code != 409 {
				t.Errorf("unexpected race code %d", w.Code)
			}
		}(id)
	}
	wg.Wait()
	if success.Load() != 1 {
		t.Fatal("optimistic concurrent binding was not exclusive")
	}
	fixtures := map[string]func(*core.Task){
		"busy":    func(t *core.Task) { t.Sessions["architect"].Busy = true },
		"pending": func(t *core.Task) { t.Sessions["architect"].Pending = true },
		"dialog": func(t *core.Task) {
			t.Sessions["architect"].PendingUI = []json.RawMessage{json.RawMessage(`{"id":"pending"}`)}
		},
		"execution": func(t *core.Task) { t.Execution = &core.Execution{Status: "failed"} },
		"history":   func(t *core.Task) { t.ExecutionHistory = []core.Execution{{Status: "completed"}} },
	}
	for name, fixture := range fixtures {
		t.Run(name, func(t *testing.T) {
			x := draftTask(t, s, "freeze-"+name)
			if err := s.store.Update(func(st *core.State) error { fixture(st.Tasks[x.ID]); return nil }); err != nil {
				t.Fatal(err)
			}
			w := call(t, s, "PATCH", "/v1/tasks/"+x.ID+"/target", targetInput{RequestID: "reject-" + name, ExpectedTargetRevision: ptr(0), Repository: "example/repository", ProjectID: "p", NodeID: "n"})
			if w.Code != 409 {
				t.Fatalf("accepted unsafe target change: %s", w.Body.String())
			}
		})
	}
}
func TestStartRequiresCurrentConfirmedReadyTarget(t *testing.T) {
	s := testServer(t)
	task := draftTask(t, s, "gated-start")
	planFixture(t, s, task.ID, true)
	start := func(id string, revision *int) *httptest.ResponseRecorder {
		return call(t, s, "POST", "/v1/tasks/"+task.ID+"/start", actionInput{RequestID: id, Revision: 1, ExpectedTargetRevision: revision})
	}
	if w := start("unbound", ptr(0)); w.Code != 409 {
		t.Fatal("unbound task started")
	}
	task = bindTask(t, s, task, "bind-gate")
	if w := start("unconfirmed", ptr(1)); w.Code != 409 {
		t.Fatal("changed target kept confirmation")
	}
	planFixture(t, s, task.ID, true)
	for name, revision := range map[string]*int{"missing": nil, "stale": ptr(0)} {
		if w := start(name, revision); w.Code != 409 {
			t.Fatal("missing/stale target revision started")
		}
	}
	old := s.cfg.Nodes["n"]
	var posts atomic.Int32
	unavailable := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "POST" {
			posts.Add(1)
		}
		http.Error(w, "private internal path must not leak", 503)
	}))
	defer unavailable.Close()
	s.cfg.Nodes["n"] = NodeConfig{URL: unavailable.URL, TokenEnv: old.TokenEnv}
	if w := start("offline", ptr(1)); w.Code != 409 || strings.Contains(w.Body.String(), "private internal") {
		t.Fatalf("offline start: %s", w.Body.String())
	}
	if posts.Load() != 0 {
		t.Fatal("failed validation dispatched node work")
	}
	s.cfg.Nodes["n"] = old
	if err := s.store.Update(func(st *core.State) error {
		return s.prepareExecution(st, st.Tasks[task.ID], "authorized", 1, false, ptr(1))
	}); err != nil {
		t.Fatal(err)
	}
	got, _ := s.task(task.ID)
	if got.Execution == nil || got.Execution.Target == nil || got.Execution.Target.Revision != 1 || got.Execution.Target.RepositoryID != "12345" {
		t.Fatal("execution missing exact target snapshot")
	}
	original := s.jobRequest(got)
	got.Repository = "altered/metadata"
	got.ProjectID = "other"
	if changed := s.jobRequest(got); !reflect.DeepEqual(original, changed) {
		t.Fatal("dispatch ignored durable target snapshot")
	}
}
func TestCatalogIntersectionAndManagedPlanning(t *testing.T) {
	s := testServer(t)
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]any{"available": true, "reachable": true, "projects": []map[string]any{{"projectId": "p", "label": "/secret/workspace", "ready": true}, {"projectId": "outside", "label": "private", "ready": true}}})
	}))
	defer remote.Close()
	s.cfg.Nodes["n"] = NodeConfig{URL: remote.URL, TokenEnv: "TEST_NODE_TOKEN"}
	w := call(t, s, "GET", "/v1/targets", nil)
	if w.Code != 200 || strings.Contains(w.Body.String(), "secret") || strings.Contains(w.Body.String(), "outside") || !strings.Contains(w.Body.String(), `"ready":true`) {
		t.Fatalf("catalog: %s", w.Body.String())
	}
	first := draftTask(t, s, "managed-a")
	second := draftTask(t, s, "managed-b")
	firstDir, err := s.planningDirectory(first)
	if err != nil {
		t.Fatal(err)
	}
	if firstDir != filepath.Join(s.cfg.DataDir, "planning", first.ID) || firstDir == s.cfg.Projects["p"] {
		t.Fatal("draft inherited a project or Host cwd")
	}
	if info, err := os.Stat(firstDir); err != nil || info.Mode().Perm()&0077 != 0 {
		t.Fatal("managed directory is not private")
	}
	first = bindTask(t, s, first, "managed-bind")
	if boundDir, err := s.planningDirectory(first); err != nil || firstDir != boundDir {
		t.Fatal("binding changed restricted cwd")
	}
	st := s.store.Snapshot()
	st.Tasks[first.ID].Sessions["architect"].Busy = true
	if err := projectAvailable(&st, st.Tasks[second.ID]); err != nil {
		t.Fatal("unbound tasks contend on empty project")
	}
	st.Tasks[second.ID].ProjectID = "p"
	if err := projectAvailable(&st, st.Tasks[second.ID]); err != nil {
		t.Fatal("restricted Pi incorrectly owns configured workspace")
	}
}
func TestRepositorySyntaxAndLegacyActionHash(t *testing.T) {
	for _, value := range []string{"", "https://github.com/example/repo", "../repo", "example/..", "example/.", "example/repo\n", "example/repo/extra"} {
		if validRepository(value, "") {
			t.Fatalf("accepted %q", value)
		}
	}
	if !validRepository("example/repo.name", "123") || validRepository("example/repo", "001") {
		t.Fatal("repository ID validation")
	}
	// New optional action fields must not change the prior serialized payload.
	old := `{"requestId":"start-old","role":"architect","revision":2}`
	got, _ := json.Marshal(actionInput{RequestID: "start-old", Role: "architect", Revision: 2})
	if string(got) != old {
		t.Fatalf("legacy action hash changed: %s", got)
	}
}

func TestStartAndTargetMutationShareAtomicReservation(t *testing.T) {
	s := testServer(t)
	for attempt := 0; attempt < 10; attempt++ {
		task := draftTask(t, s, "atomic-"+string(rune('a'+attempt)))
		task = bindTask(t, s, task, "atomic-bind-"+task.ID)
		planFixture(t, s, task.ID, true)
		var wg sync.WaitGroup
		var started, saved bool
		wg.Add(2)
		go func() {
			defer wg.Done()
			_, err := s.reserve("atomic-start-"+task.ID, task.ID, "start", actionInput{RequestID: "atomic-start-" + task.ID, Revision: 1, ExpectedTargetRevision: ptr(1)}, func(st *core.State) error {
				return s.prepareExecution(st, st.Tasks[task.ID], "atomic-start-"+task.ID, 1, false, ptr(1))
			})
			started = err == nil
		}()
		go func() {
			defer wg.Done()
			w := call(t, s, "PATCH", "/v1/tasks/"+task.ID+"/target", targetInput{RequestID: "atomic-save-" + task.ID, ExpectedTargetRevision: ptr(1), Repository: "example/changed", ProjectID: "p", NodeID: "n"})
			saved = w.Code == 202
			if w.Code != 202 && w.Code != 409 {
				t.Errorf("unexpected target race error: %s", w.Body.String())
			}
		}()
		wg.Wait()
		if started == saved {
			t.Fatalf("start and target write did not serialize: start=%v save=%v", started, saved)
		}
		got, _ := s.task(task.ID)
		if started && (got.TargetRevision != 1 || got.Execution.Target.Revision != 1 || got.Execution.Target.Repository != "example/repository") {
			t.Fatal("execution authorized a different target")
		}
		if saved && (got.TargetRevision != 2 || got.Plan.ConfirmedAt != nil || got.Execution != nil) {
			t.Fatal("target mutation retained execution authority")
		}
		// Release the project slot between independent race fixtures.
		if err := s.store.Update(func(st *core.State) error {
			if st.Tasks[task.ID].Execution != nil {
				st.Tasks[task.ID].Execution.Status = "cancelled"
			}
			return nil
		}); err != nil {
			t.Fatal(err)
		}
	}
}
func TestTargetCatalogUnknownMismatchAndOfflineFailClosed(t *testing.T) {
	for _, test := range []struct {
		name, body string
		code       int
		status     string
	}{
		{"legacy-health-count", `{"projects":12}`, 200, "unknown"},
		{"old-node", `{}`, 404, "unknown"},
		{"offline", `private upstream error`, 503, "unavailable"},
		{"native-offline", `{"available":true,"reachable":false,"projects":[{"projectId":"p","ready":true}]}`, 200, "unavailable"},
		{"mismatch", `{"available":true,"reachable":true,"projects":[{"projectId":"other","ready":true}]}`, 200, "online"},
	} {
		t.Run(test.name, func(t *testing.T) {
			s := testServer(t)
			var posts atomic.Int32
			remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.Method == "POST" {
					posts.Add(1)
				}
				w.WriteHeader(test.code)
				_, _ = w.Write([]byte(test.body))
			}))
			defer remote.Close()
			s.cfg.Nodes["n"] = NodeConfig{URL: remote.URL, TokenEnv: "TEST_NODE_TOKEN"}
			targets, status := s.targetCatalog(t.Context(), "n")
			if status != test.status {
				t.Fatalf("status=%s want %s", status, test.status)
			}
			for _, target := range targets {
				if target.Ready {
					t.Fatal("unverified executable pair advertised")
				}
			}
			task := draftTask(t, s, "catalog-"+test.name)
			planFixture(t, s, task.ID, true)
			w := call(t, s, "PATCH", "/v1/tasks/"+task.ID+"/target", targetInput{RequestID: "catalog-save", ExpectedTargetRevision: ptr(0), Repository: "example/repository", ProjectID: "p", NodeID: "n"})
			if w.Code != 409 || posts.Load() != 0 {
				t.Fatalf("unsafe target save: %d %s", w.Code, w.Body.String())
			}
			got, _ := s.task(task.ID)
			if got.TargetRevision != 0 || got.Execution != nil || got.Repository != "" {
				t.Fatal("failed save modified task")
			}
		})
	}
}

func TestReboundLegacyTaskRequiresTargetRevision(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "legacy-rebinding")
	task = bindTask(t, s, task, "legacy-save")
	planFixture(t, s, task.ID, true)
	w := call(t, s, "POST", "/v1/tasks/"+task.ID+"/start", actionInput{RequestID: "legacy-stale-start", Revision: 1})
	if w.Code != 409 || !strings.Contains(w.Body.String(), "target_required") {
		t.Fatalf("legacy client authorized rebound target: %d %s", w.Code, w.Body.String())
	}
}
func TestFirstDispatchRevalidatesQueuedSnapshot(t *testing.T) {
	s := testServer(t)
	var ready atomic.Bool
	ready.Store(true)
	var checks, posts atomic.Int32
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/v1/projects" {
			checks.Add(1)
			writeJSON(w, 200, map[string]any{"available": true, "reachable": ready.Load(), "projects": []map[string]any{{"projectId": "p", "ready": ready.Load()}}})
			return
		}
		if r.Method == "POST" {
			posts.Add(1)
			http.Error(w, "unexpected dispatch", 503)
			return
		}
		http.NotFound(w, r)
	}))
	defer remote.Close()
	s.cfg.Nodes["n"] = NodeConfig{URL: remote.URL, TokenEnv: "TEST_NODE_TOKEN"}
	task := bindTask(t, s, draftTask(t, s, "queued-revalidate"), "queued-bind")
	planFixture(t, s, task.ID, true)
	if err := s.store.Update(func(st *core.State) error {
		return s.prepareExecution(st, st.Tasks[task.ID], "queued-start", 1, false, ptr(1))
	}); err != nil {
		t.Fatal(err)
	}
	ready.Store(false)
	checks.Store(0)
	s.monitor(task.ID)
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		got, _ := s.task(task.ID)
		if got.Status == "needs_verification" {
			if got.Execution.DispatchAttempted || posts.Load() != 0 || checks.Load() == 0 {
				t.Fatal("offline queued target reached first dispatch")
			}
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("first-dispatch target validation did not report its blocker")
}

func TestLegacyStartupReservationFreezesWorkspace(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "legacy-start-reservation")
	s.cfg.Projects["alternate"] = t.TempDir()
	if err := s.store.Update(func(st *core.State) error {
		st.Tasks[task.ID].Sessions["architect"].ProcessID = "starting-process"
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	w := call(t, s, "PATCH", "/v1/tasks/"+task.ID+"/target", targetInput{RequestID: "legacy-move", ExpectedTargetRevision: ptr(0), Repository: "example/repository", ProjectID: "alternate", NodeID: "n"})
	if w.Code != 409 || !strings.Contains(w.Body.String(), "target_locked") {
		t.Fatalf("legacy startup workspace moved: %s", w.Body.String())
	}
}
