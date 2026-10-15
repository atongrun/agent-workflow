package host

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"reflect"
	"sync/atomic"
	"testing"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
	"github.com/atongrun/agent-workflow/internal/pi"
)

func awaitPiBudgetCondition(t *testing.T, description string, condition func() bool) {
	t.Helper()
	deadline := time.Now().Add(6 * time.Second)
	for time.Now().Before(deadline) {
		if condition() {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal(description)
}

func releasePiBudgetBarrier(t *testing.T, path string) {
	t.Helper()
	if err := os.WriteFile(path, nil, 0600); err != nil {
		t.Error(err)
	}
}

func TestPiBudgetWatchesFirstPromptBeforeAcknowledgement(t *testing.T) {
	s, task, _, log, _ := piControlFixture(t, "budget_no_prompt_ack")
	if err := s.store.Update(func(st *core.State) error {
		current := st.Tasks[task.ID]
		current.Settings.TaskMinutes = 1
		current.Budget.TaskSeconds = 59
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	// The process watcher must survive an idle tick before its first prompt.
	time.Sleep(1200 * time.Millisecond)
	in := actionInput{RequestID: "first-unacknowledged-prompt", Text: "Start the fixture stream"}
	path := "/v1/tasks/" + task.ID + "/messages"
	if w := call(t, s, "POST", path, in); w.Code != 202 {
		t.Fatal(w.Code, w.Body.String())
	}
	// This bound is shorter than prompt's 20 second ACK wait. The fixture
	// emits agent_start, but deliberately never answers the prompt command.
	awaitPiBudgetCondition(t, "budget did not stop the first unacknowledged prompt", func() bool {
		current, _ := s.task(task.ID)
		return current.Status == "blocked" && methodCount(t, log, "abort") == 1
	})
	state := s.store.Snapshot()
	request := state.Requests[in.RequestID]
	if request == nil || !request.Dispatched || request.Status != "accepted" {
		t.Fatalf("expected the original unacknowledged receipt, got %+v", request)
	}
	if state.Tasks[task.ID].Budget.TaskSeconds < 60 || state.Tasks[task.ID].Budget.ActiveSince != nil {
		t.Fatal("budget stop did not settle the original activity")
	}
	if w := call(t, s, "POST", path, in); w.Code != 202 {
		t.Fatal("exact retry lost the original receipt", w.Code, w.Body.String())
	}
	if methodCount(t, log, "prompt") != 1 || methodCount(t, log, "clear_queue") != 1 || methodCount(t, log, "abort") != 1 {
		t.Fatal("budget stop or exact retry replayed native work")
	}
}

func TestPiBudgetReusedClientHasOneWatcher(t *testing.T) {
	for _, operation := range []string{"prompt", "compact"} {
		t.Run(operation, func(t *testing.T) {
			mode := "budget_hold_abort"
			if operation == "prompt" {
				mode = "budget_streaming_hold_abort"
			}
			s, task, control, log, release := piControlFixture(t, mode)
			defer releasePiBudgetBarrier(t, release)
			s.mu.Lock()
			original := s.clients[task.ID+":architect"]
			s.mu.Unlock()
			for _, requestID := range []string{"warmup-one", "warmup-two"} {
				if w := call(t, s, "POST", "/v1/tasks/"+task.ID+"/messages", actionInput{RequestID: requestID, Text: "Reuse the original fixture process"}); w.Code != 202 {
					t.Fatal(w.Code, w.Body.String())
				}
				if operation == "compact" {
					awaitPiRequest(t, s, requestID, "settled")
				} else {
					awaitPiRequest(t, s, requestID, "accepted_native")
				}
			}
			if operation == "compact" {
				control.RequestID = "budget-compact"
				if w := call(t, s, "POST", "/v1/tasks/"+task.ID+"/pi/compact", control); w.Code != 202 {
					t.Fatal(w.Code, w.Body.String())
				}
			}
			awaitPiBudgetCondition(t, "fixture did not enter native activity", func() bool {
				current, _ := s.task(task.ID)
				return current.Sessions["architect"].Busy
			})
			if err := s.store.Update(func(st *core.State) error {
				current := st.Tasks[task.ID]
				current.Settings.TaskMinutes = 1
				current.Budget.TaskSeconds = 60
				return nil
			}); err != nil {
				t.Fatal(err)
			}
			awaitPiBudgetCondition(t, "budget watcher did not reach abort", func() bool { return methodCount(t, log, "abort") > 0 })
			// Abort has not emitted idle/compaction_end or its receipt. Give any
			// extra prompt/compact watcher more than two ticks to reveal itself.
			time.Sleep(2200 * time.Millisecond)
			if methodCount(t, log, "clear_queue") != 1 || methodCount(t, log, "abort") != 1 {
				t.Fatal("reusing the process added duplicate budget watchers")
			}
			s.mu.Lock()
			sameClient := s.clients[task.ID+":architect"] == original
			s.mu.Unlock()
			if !sameClient || methodCount(t, log, "prompt") != 2 {
				t.Fatal("fixture did not reuse the original native process")
			}
			releasePiBudgetBarrier(t, release)
			awaitPiBudgetCondition(t, "budget stop did not finish after native receipt", func() bool {
				current, _ := s.task(task.ID)
				return current.Status == "blocked"
			})
		})
	}
}

func TestPiBudgetStopCannotMutateReplacementBinding(t *testing.T) {
	for _, changed := range []string{"process", "session", "lifecycle", "deleted"} {
		t.Run(changed, func(t *testing.T) {
			s, task, _, log, release := piControlFixture(t, "budget_hold_abort")
			defer releasePiBudgetBarrier(t, release)
			s.mu.Lock()
			automatic := s.clients[task.ID+":architect"]
			s.mu.Unlock()
			if err := automatic.Close(); err != nil {
				t.Fatal(err)
			}
			// Start a direct fixture transport so this test owns exactly one
			// watcher and can wait for its completion before checking state.
			binding := piBinding{"architect", task.Sessions["architect"].ID, "budget-original-process"}
			original, err := pi.Start(pi.Config{Binary: s.cfg.PiBinary, Directory: t.TempDir(), SessionDirectory: t.TempDir(), SessionID: binding.SessionID, OnEvent: func(raw json.RawMessage) {
				s.piEvent(task.ID, binding.Role, binding.ProcessID, raw)
			}})
			if err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() {
				releasePiBudgetBarrier(t, release)
				_ = original.Close()
			})
			ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
			_, err = original.Call(ctx, "get_state", nil)
			cancel()
			if err != nil {
				t.Fatal(err)
			}
			var nodePosts atomic.Int32
			nodeHTTP := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.Method == http.MethodPost {
					nodePosts.Add(1)
				}
				http.NotFound(w, r)
			}))
			t.Cleanup(nodeHTTP.Close)
			s.cfg.Nodes["n"] = NodeConfig{URL: nodeHTTP.URL, TokenEnv: "TEST_NODE_TOKEN"}
			if err := s.store.Update(func(st *core.State) error {
				current := st.Tasks[task.ID]
				ref := current.Sessions[binding.Role]
				ref.ProcessID, ref.Available, ref.Busy = binding.ProcessID, true, true
				current.Settings.TaskMinutes = 1
				current.Budget.TaskSeconds = 60
				current.Execution = &core.Execution{RequestID: "original-execution", JobID: "original-job", Status: "running"}
				return nil
			}); err != nil {
				t.Fatal(err)
			}
			s.mu.Lock()
			s.clients[task.ID+":architect"] = original
			s.mu.Unlock()
			done := make(chan struct{})
			if !s.launch(func() {
				defer close(done)
				s.watchPiBudget(task.ID, binding, task.LifecycleRevision, original)
			}) {
				t.Fatal("watcher did not start")
			}
			awaitPiBudgetCondition(t, "original watcher did not reach the stop barrier", func() bool { return methodCount(t, log, "abort") == 1 })
			if err := s.store.Update(func(st *core.State) error {
				current := st.Tasks[task.ID]
				ref := current.Sessions[binding.Role]
				switch changed {
				case "process":
					ref.ProcessID = "replacement-process"
				case "session":
					ref.ID = "replacement-session"
				case "lifecycle":
					current.LifecycleRevision++
				case "deleted":
					now := time.Now().UTC()
					current.DeletedAt = &now
				}
				active := time.Now().UTC().Add(-5 * time.Second)
				current.Budget = core.Budget{TaskSeconds: 7, ActiveSince: &active}
				current.Status, current.LastError = "planning", "replacement state"
				current.Execution = &core.Execution{RequestID: "replacement-execution", JobID: "replacement-job", Status: "running"}
				return nil
			}); err != nil {
				t.Fatal(err)
			}
			before, _ := s.task(task.ID)
			replacement, err := pi.Start(pi.Config{Binary: s.cfg.PiBinary, Directory: t.TempDir(), SessionDirectory: t.TempDir(), SessionID: before.Sessions[binding.Role].ID})
			if err != nil {
				t.Fatal(err)
			}
			s.mu.Lock()
			s.clients[task.ID+":architect"] = replacement
			s.mu.Unlock()
			releasePiBudgetBarrier(t, release)
			select {
			case <-done:
			case <-time.After(6 * time.Second):
				t.Fatal("original watcher did not finish after its receipt")
			}
			after, _ := s.task(task.ID)
			if !reflect.DeepEqual(before.Budget, after.Budget) || after.Status != before.Status || after.LastError != before.LastError || !reflect.DeepEqual(before.Execution, after.Execution) {
				t.Fatalf("old watcher changed replacement state: before=%+v after=%+v", before, after)
			}
			// Drain launched callbacks before asserting that no delayed global
			// abort or executor cancellation targeted the replacement.
			s.Close()
			if nodePosts.Load() != 0 || methodCount(t, log, "clear_queue") != 1 || methodCount(t, log, "abort") != 1 {
				t.Fatal("old watcher stopped the replacement process or execution")
			}
		})
	}
}

func TestPiBudgetAllowsNonGeneratingControlAfterExhaustion(t *testing.T) {
	s, task, control, log, release := piControlFixture(t, "hold_model")
	defer releasePiBudgetBarrier(t, release)
	if err := s.store.Update(func(st *core.State) error {
		current := st.Tasks[task.ID]
		current.Settings.TaskMinutes = 1
		current.Budget.TaskSeconds = 60
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	before, _ := s.task(task.ID)
	control.Provider, control.ModelID = "test", "two"
	if w := call(t, s, "POST", "/v1/tasks/"+task.ID+"/pi/model", control); w.Code != 202 {
		t.Fatal(w.Code, w.Body.String())
	}
	awaitPiBudgetCondition(t, "model control did not reach its native wait", func() bool { return methodCount(t, log, "set_model") == 1 })
	time.Sleep(2200 * time.Millisecond)
	after, _ := s.task(task.ID)
	if methodCount(t, log, "clear_queue") != 0 || methodCount(t, log, "abort") != 0 || after.Status != before.Status || !reflect.DeepEqual(before.Budget, after.Budget) {
		t.Fatal("budget watcher stopped a non-generating model control")
	}
	releasePiBudgetBarrier(t, release)
	awaitPiRequest(t, s, control.RequestID, "completed")
}
