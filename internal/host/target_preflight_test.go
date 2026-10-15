package host

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
	"github.com/atongrun/agent-workflow/internal/node"
)

// The catalog stays blocked while tests read and update Host state. All network
// traffic is to this local fixture; it cannot start Pi or a native executor.
func blockedTargetNode(t *testing.T, s *Server) (<-chan struct{}, func(), *atomic.Int32) {
	t.Helper()
	entered, release := make(chan struct{}), make(chan struct{})
	var enteredOnce, releaseOnce sync.Once
	var posts atomic.Int32
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/v1/projects" {
			enteredOnce.Do(func() { close(entered) })
			select {
			case <-release:
				serveTestCatalog(w, r)
			case <-r.Context().Done():
			}
			return
		}
		if r.Method == "POST" {
			posts.Add(1)
		}
		http.NotFound(w, r)
	}))
	unlock := func() { releaseOnce.Do(func() { close(release) }) }
	t.Cleanup(remote.Close)
	t.Cleanup(unlock)
	s.cfg.Nodes["n"] = NodeConfig{URL: remote.URL, TokenEnv: "TEST_NODE_TOKEN"}
	return entered, unlock, &posts
}

func awaitTargetProbe(t *testing.T, entered <-chan struct{}) {
	t.Helper()
	select {
	case <-entered:
	case <-time.After(3 * time.Second):
		t.Fatal("node catalog preflight was not reached")
	}
}

func updateDuringTargetProbe(t *testing.T, s *Server, readID string, change func(*core.State)) {
	t.Helper()
	done := make(chan error, 1)
	go func() {
		if w := call(t, s, "GET", "/v1/tasks/"+readID, nil); w.Code != 200 {
			done <- fmt.Errorf("unrelated task read returned %d", w.Code)
			return
		}
		done <- s.store.Update(func(st *core.State) error { change(st); return nil })
	}()
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("node catalog I/O blocked unrelated Host state reads or updates")
	}
}

func awaitTargetResponse(t *testing.T, done <-chan *httptest.ResponseRecorder) *httptest.ResponseRecorder {
	t.Helper()
	select {
	case w := <-done:
		return w
	case <-time.After(3 * time.Second):
		t.Fatal("target reservation did not finish after node preflight")
		return nil
	}
}

func TestTargetPreflightAllowsUnrelatedStateAndExactReplay(t *testing.T) {
	s := testServer(t)
	task := draftTask(t, s, "target-preflight")
	other := draftTask(t, s, "other-target-preflight")
	entered, release, posts := blockedTargetNode(t, s)
	in := targetInput{RequestID: "bind-preflight", ExpectedTargetRevision: ptr(0), Repository: "example/repository", ProjectID: "p", NodeID: "n"}
	path := "/v1/tasks/" + task.ID + "/target"
	done := make(chan *httptest.ResponseRecorder, 1)
	go func() { done <- call(t, s, "PATCH", path, in) }()
	awaitTargetProbe(t, entered)
	updateDuringTargetProbe(t, s, other.ID, func(st *core.State) { st.Tasks[other.ID].Title = "Unrelated update" })
	release()
	if w := awaitTargetResponse(t, done); w.Code != 202 {
		t.Fatal(w.Code, w.Body.String())
	}
	// Historical retry must not consult a now-missing target configuration.
	delete(s.cfg.Nodes, "n")
	if w := call(t, s, "PATCH", path, in); w.Code != 202 {
		t.Fatal("exact target receipt depended on current node availability", w.Code, w.Body.String())
	}
	if posts.Load() != 0 {
		t.Fatal("target validation submitted executor work")
	}
}

func TestTargetPreflightFailureCannotReplaceConcurrentReceipt(t *testing.T) {
	s := testServer(t)
	task := draftTask(t, s, "concurrent-target-receipt")
	entered, release := make(chan struct{}), make(chan struct{})
	var releaseOnce sync.Once
	var checks atomic.Int32
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if checks.Add(1) == 1 {
			close(entered)
			select {
			case <-release:
				http.Error(w, "catalog unavailable", http.StatusServiceUnavailable)
			case <-r.Context().Done():
			}
			return
		}
		serveTestCatalog(w, r)
	}))
	t.Cleanup(remote.Close)
	unlock := func() { releaseOnce.Do(func() { close(release) }) }
	t.Cleanup(unlock)
	s.cfg.Nodes["n"] = NodeConfig{URL: remote.URL, TokenEnv: "TEST_NODE_TOKEN"}
	in := targetInput{RequestID: "concurrent-target-bind", ExpectedTargetRevision: ptr(0), Repository: "example/repository", ProjectID: "p", NodeID: "n"}
	path := "/v1/tasks/" + task.ID + "/target"
	done := make(chan *httptest.ResponseRecorder, 1)
	go func() { done <- call(t, s, "PATCH", path, in) }()
	awaitTargetProbe(t, entered)
	if w := call(t, s, "PATCH", path, in); w.Code != 202 {
		t.Fatal("concurrent identical reservation failed", w.Code, w.Body.String())
	}
	unlock()
	if w := awaitTargetResponse(t, done); w.Code != 202 {
		t.Fatal("failed preflight replaced the committed receipt", w.Code, w.Body.String())
	}
	if current, _ := s.task(task.ID); current.TargetRevision != 1 {
		t.Fatal("concurrent retry changed the target twice")
	}
}

func TestTargetPreflightRejectsChangedOriginalBinding(t *testing.T) {
	for name, change := range map[string]func(*core.Task){
		"identity":  func(task *core.Task) { task.Repository = "example/changed" },
		"revision":  func(task *core.Task) { task.TargetRevision++ },
		"lifecycle": func(task *core.Task) { task.LifecycleRevision++ },
	} {
		t.Run(name, func(t *testing.T) {
			s := testServer(t)
			task := draftTask(t, s, "stale-target-preflight")
			entered, release, posts := blockedTargetNode(t, s)
			in := targetInput{RequestID: "stale-target-bind", ExpectedTargetRevision: ptr(0), Repository: "example/repository", ProjectID: "p", NodeID: "n"}
			done := make(chan *httptest.ResponseRecorder, 1)
			go func() { done <- call(t, s, "PATCH", "/v1/tasks/"+task.ID+"/target", in) }()
			awaitTargetProbe(t, entered)
			updateDuringTargetProbe(t, s, task.ID, func(st *core.State) { change(st.Tasks[task.ID]) })
			release()
			if w := awaitTargetResponse(t, done); w.Code != 409 || !strings.Contains(w.Body.String(), "target_changed") {
				t.Fatal("stale node verification admitted a target", w.Code, w.Body.String())
			}
			if s.store.Snapshot().Requests[in.RequestID] != nil || posts.Load() != 0 {
				t.Fatal("stale preflight reserved a request or submitted executor work")
			}
		})
	}
}

func TestExecutionPreflightRejectsLifecycleChangeWithoutHoldingStore(t *testing.T) {
	for _, operation := range []string{"start", "rework"} {
		t.Run(operation, func(t *testing.T) {
			s := testServer(t)
			task := createTask(t, s, "execution-preflight")
			planFixture(t, s, task.ID, true)
			in := actionInput{RequestID: "new-execution", Revision: 1}
			if operation == "rework" {
				in.ExecutionRequestID = "previous-execution"
				if err := s.store.Update(func(st *core.State) error {
					current := st.Tasks[task.ID]
					current.Execution = &core.Execution{RequestID: in.ExecutionRequestID, Status: "completed"}
					current.Completion = &core.Completion{ExecutionRequestID: in.ExecutionRequestID, Verdict: "needs_changes"}
					current.Status = "needs_changes"
					return nil
				}); err != nil {
					t.Fatal(err)
				}
			}
			entered, release, posts := blockedTargetNode(t, s)
			done := make(chan *httptest.ResponseRecorder, 1)
			go func() { done <- call(t, s, "POST", "/v1/tasks/"+task.ID+"/"+operation, in) }()
			awaitTargetProbe(t, entered)
			updateDuringTargetProbe(t, s, task.ID, func(st *core.State) { st.Tasks[task.ID].LifecycleRevision++ })
			release()
			if w := awaitTargetResponse(t, done); w.Code != 409 || !strings.Contains(w.Body.String(), "target_changed") {
				t.Fatal("stale preflight authorized execution", w.Code, w.Body.String())
			}
			state := s.store.Snapshot()
			current := state.Tasks[task.ID]
			if state.Requests[in.RequestID] != nil || current.Budget.Reworks != 0 || len(current.ExecutionHistory) != 0 || posts.Load() != 0 {
				t.Fatal("failed preflight left execution, rework or dispatch side effects")
			}
			if operation == "start" && current.Execution != nil || operation == "rework" && (current.Execution == nil || current.Execution.RequestID != in.ExecutionRequestID) {
				t.Fatal("failed preflight changed the original execution")
			}
		})
	}
}

func TestExecutionPreflightExactReplaySkipsUnavailableCatalog(t *testing.T) {
	for _, operation := range []string{"start", "rework"} {
		t.Run(operation, func(t *testing.T) {
			s := testServer(t)
			task := createTask(t, s, "execution-receipt")
			planFixture(t, s, task.ID, true)
			in := actionInput{RequestID: "successful-execution", Revision: 1}
			if operation == "rework" {
				in.ExecutionRequestID = "previous-execution"
				if err := s.store.Update(func(st *core.State) error {
					current := st.Tasks[task.ID]
					current.Execution = &core.Execution{RequestID: in.ExecutionRequestID, Status: "completed"}
					current.Completion = &core.Completion{ExecutionRequestID: in.ExecutionRequestID, Verdict: "needs_changes"}
					current.Status = "needs_changes"
					return nil
				}); err != nil {
					t.Fatal(err)
				}
			}
			entered, release := make(chan struct{}), make(chan struct{})
			var enteredOnce, releaseOnce sync.Once
			var unavailable atomic.Bool
			var catalogs, posts atomic.Int32
			remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path == "/v1/projects" {
					catalogs.Add(1)
					if unavailable.Load() {
						http.Error(w, "catalog unavailable", http.StatusServiceUnavailable)
					} else {
						serveTestCatalog(w, r)
					}
					return
				}
				if r.Method == "GET" && r.URL.Path == "/v1/jobs/"+node.JobID(in.RequestID) {
					enteredOnce.Do(func() { close(entered) })
					select {
					case <-release:
						writeJSON(w, 200, node.Job{ID: node.JobID(in.RequestID), TaskID: task.ID, RequestID: in.RequestID, Status: "running"})
					case <-r.Context().Done():
					}
					return
				}
				if r.Method == "POST" {
					posts.Add(1)
				}
				http.NotFound(w, r)
			}))
			t.Cleanup(remote.Close)
			t.Cleanup(func() { releaseOnce.Do(func() { close(release) }) })
			s.cfg.Nodes["n"] = NodeConfig{URL: remote.URL, TokenEnv: "TEST_NODE_TOKEN"}
			path := "/v1/tasks/" + task.ID + "/" + operation
			if w := call(t, s, "POST", path, in); w.Code != 202 {
				t.Fatal("initial execution reservation failed", w.Code, w.Body.String())
			}
			select {
			case <-entered:
			case <-time.After(3 * time.Second):
				t.Fatal("monitor did not reach the original job read")
			}
			unavailable.Store(true)
			if w := call(t, s, "POST", path, in); w.Code != 202 {
				t.Fatal("exact execution retry depended on node availability", w.Code, w.Body.String())
			}
			if catalogs.Load() != 1 || posts.Load() != 0 {
				t.Fatal("exact execution retry queried the catalog or submitted work")
			}
			current, _ := s.task(task.ID)
			if current.Execution.RequestID != in.RequestID || operation == "rework" && (current.Budget.Reworks != 1 || len(current.ExecutionHistory) != 1) {
				t.Fatal("exact execution retry changed the reserved execution")
			}
		})
	}
}

func TestDispatchPreflightRejectsChangedSnapshotWithoutHoldingStore(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "dispatch-preflight")
	planFixture(t, s, task.ID, true)
	if err := s.store.Update(func(st *core.State) error {
		return s.prepareExecution(st, st.Tasks[task.ID], "queued-preflight", 1, false, nil)
	}); err != nil {
		t.Fatal(err)
	}
	entered, release, posts := blockedTargetNode(t, s)
	s.monitor(task.ID)
	awaitTargetProbe(t, entered)
	updateDuringTargetProbe(t, s, task.ID, func(st *core.State) {
		st.Tasks[task.ID].Execution.Target.Repository = "example/different-snapshot"
	})
	release()
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) {
		current, _ := s.task(task.ID)
		if current.Status == "needs_verification" {
			s.Close()
			if current.Execution.DispatchAttempted || posts.Load() != 0 || !strings.Contains(current.Execution.Error, "changed during node verification") {
				t.Fatal("stale execution snapshot crossed the dispatch fence")
			}
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatal("changed dispatch snapshot was not rejected")
}
