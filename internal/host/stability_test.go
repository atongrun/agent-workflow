package host

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/atongrun/agent-workflow/internal/core"
)

func TestFinishReservationSurvivesCrashBeforeRequestDone(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "finish-crash-window")
	// Exercise the exact first durable boundary used by internalAction, then
	// simulate a crash before its former separate requestDone call.
	_, err := s.reserve("finish-crash", task.ID, "extension/finish", map[string]string{"verdict": "done"}, func(st *core.State) error {
		st.Tasks[task.ID].Status = "done"
		st.Tasks[task.ID].Completion = &core.Completion{Verdict: "done", ExecutionRequestID: "original-run"}
		core.Changed(st, st.Tasks[task.ID])
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	s.Close()
	durable, err := core.Open(s.cfg.DataDir)
	if err != nil {
		t.Fatal(err)
	}
	defer durable.Close()
	got := durable.Snapshot()
	if got.Tasks[task.ID].Status != "done" || got.Requests["finish-crash"].Status != "completed" {
		t.Fatal("durable verdict and its receipt diverged at the first commit")
	}
}

func TestSettleEventCannotResolveAnotherProcessOrSession(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "settle-binding")
	if err := s.store.Update(func(st *core.State) error {
		ref := st.Tasks[task.ID].Sessions["architect"]
		ref.ProcessID = "new-process"
		for _, row := range []struct{ id, session, process, role string }{
			{"matching", ref.ID, ref.ProcessID, "architect"},
			{"old-process", ref.ID, "old-process", "architect"},
			{"other-session", "other-session", ref.ProcessID, "architect"},
			{"other-role", ref.ID, ref.ProcessID, "reviewer"},
		} {
			st.Requests[row.id] = &core.Request{ID: row.id, TaskID: task.ID, Role: row.role, SessionID: row.session, ProcessID: row.process, Status: "accepted_native", Operation: "messages"}
		}
		st.Requests["matching-control"] = &core.Request{ID: "matching-control", TaskID: task.ID, Role: "architect", SessionID: ref.ID, ProcessID: ref.ProcessID, Status: "accepted_native", Operation: "pi/model"}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	s.piEvent(task.ID, "architect", "new-process", json.RawMessage(`{"type":"agent_settled"}`))
	requests := s.store.Snapshot().Requests
	if requests["matching"].Status != "settled" {
		t.Fatal("matching original receipt was not settled")
	}
	for _, id := range []string{"old-process", "other-session", "other-role", "matching-control"} {
		if requests[id].Status != "accepted_native" {
			t.Fatalf("settle resolved a foreign receipt: %s", id)
		}
	}
}

func TestRestartKeepsUnknownControlFenceAndExactReceipt(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "restart-fence")
	if err := s.store.Update(func(st *core.State) error {
		ref := st.Tasks[task.ID].Sessions["architect"]
		ref.PendingCommands = []string{"unknown-control"}
		refreshPending(ref)
		st.Requests["unknown-control"] = &core.Request{ID: "unknown-control", TaskID: task.ID, Role: "architect", SessionID: ref.ID, ProcessID: "old-process", Operation: "pi/compact", Status: "needs_verification", Dispatched: true, Hash: "preserve-original-hash"}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	s.Close()
	reopened, err := New(s.cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	st := reopened.store.Snapshot()
	ref := st.Tasks[task.ID].Sessions["architect"]
	if !ref.Pending || taskPiIdle(st.Tasks[task.ID]) || len(ref.PendingCommands) != 1 || ref.PendingCommands[0] != "unknown-control" {
		t.Fatal("restart cleared the unknown control fence")
	}
	if st.Requests["unknown-control"].Hash != "preserve-original-hash" || st.Requests["unknown-control"].Status != "needs_verification" {
		t.Fatal("restart rewrote or resolved the original receipt")
	}
	w := call(t, reopened, "POST", "/v1/tasks/"+task.ID+"/messages", actionInput{RequestID: "new-message", Text: "Do not dispatch"})
	if w.Code != 409 {
		t.Fatal("new message bypassed durable unknown-control fence", w.Code)
	}
}

func TestFinishPersistenceFailureCommitsNeitherOutcomeNorReceipt(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "finish-storage-fault")
	terminalReviewFixture(t, s, task, "completed", true)
	path := filepath.Join(s.cfg.DataDir, "state.json")
	backup := filepath.Join(s.cfg.DataDir, "saved-state.json")
	if err := os.Rename(path, backup); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(path, 0700); err != nil {
		t.Fatal(err)
	}
	w := finishFixture(t, s, task.ID, extensionInput{RequestID: "failed-finish", ExecutionRequestID: "result-run", Verdict: "done", Summary: "Pi assessment", EvidenceChecks: fixtureEvidenceChecks()})
	if w.Code != 500 {
		t.Fatal(w.Code, w.Body.String())
	}
	st := s.store.Snapshot()
	if st.Tasks[task.ID].Status != "reporting" || st.Tasks[task.ID].Completion != nil || st.Requests["failed-finish"] != nil {
		t.Fatal("failed commit exposed an outcome or receipt")
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(backup, path); err != nil {
		t.Fatal(err)
	}
	s.Close()
	durable, err := core.Open(s.cfg.DataDir)
	if err != nil {
		t.Fatal(err)
	}
	defer durable.Close()
	st = durable.Snapshot()
	if st.Tasks[task.ID].Status != "reporting" || st.Requests["failed-finish"] != nil {
		t.Fatal("failed outcome survived restart")
	}
}

func TestPiStopGateUsesDurableReceiptsAfterCacheLoss(t *testing.T) {
	for _, op := range []string{"pi/abort", "pi/model"} {
		t.Run(op, func(t *testing.T) {
			s, task, in, log, _ := piControlFixture(t, "")
			if err := s.store.Update(func(st *core.State) error {
				ref := st.Tasks[task.ID].Sessions["architect"]
				ref.PendingCommands = nil
				refreshPending(ref)
				st.Requests["unknown-control"] = &core.Request{ID: "unknown-control", TaskID: task.ID, Role: "architect", SessionID: ref.ID, ProcessID: "old-process", Operation: op, Status: "needs_verification", Dispatched: true}
				return nil
			}); err != nil {
				t.Fatal(err)
			}
			in.RequestID = "new-stop"
			w := call(t, s, "POST", "/v1/tasks/"+task.ID+"/pi/abort", in)
			if w.Code != 409 || methodCount(t, log, "abort") != 0 {
				t.Fatal("Stop bypassed durable unknown-control gate", w.Code)
			}
		})
	}
}

func TestDurablePendingClassificationPreservesKnownAcknowledgements(t *testing.T) {
	for _, row := range []struct {
		status, op string
		pending    bool
	}{
		{"sent_native", "pi/ui-response", false},
		{"accepted_native", "execution/cancel", false},
		{"accepted_native", "pi/ui-response", false},
		{"accepted_native", "messages", true},
		{"accepted_native", "pi/model", true},
		{"accepted_native", "unsupported", true},
		{"sent_native", "unsupported", true},
		{"unknown", "pi/abort", true},
		{"needs_verification", "pi/compact", true},
		{"completed", "pi/model", false},
		{"cancelled", "messages", false},
	} {
		t.Run(row.status+"/"+row.op, func(t *testing.T) {
			req := &core.Request{ID: "receipt", TaskID: "task", Status: row.status, Operation: row.op}
			st := &core.State{Requests: map[string]*core.Request{req.ID: req}}
			if requestPending(req) != row.pending || lifecycleRequestPending(st, "task") != row.pending {
				t.Fatal("receipt classification differs from lifecycle fence")
			}
		})
	}
}

func TestHistoricalSplitFinishRetryRepairsOnlyReceipt(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "historical-split")
	terminalReviewFixture(t, s, task, "completed", true)
	in := extensionInput{RequestID: "original-finish", ExecutionRequestID: "result-run", Verdict: "done", Summary: "Pi assessment", EvidenceChecks: fixtureEvidenceChecks()}
	if w := finishFixture(t, s, task.ID, in); w.Code != 202 {
		t.Fatal(w.Code, w.Body.String())
	}
	// Reconstruct only the old-version crash window in an isolated fixture.
	if err := s.store.Update(func(st *core.State) error {
		st.Requests[in.RequestID].Status = "needs_verification"
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	before := string(mustJSON(s.store.Snapshot().Tasks[task.ID]))
	if w := finishFixture(t, s, task.ID, in); w.Code != 202 {
		t.Fatal(w.Code, w.Body.String())
	}
	st := s.store.Snapshot()
	if st.Requests[in.RequestID].Status != "completed" || string(mustJSON(st.Tasks[task.ID])) != before {
		t.Fatal("historical retry replayed the verdict or failed to repair receipt")
	}
}

func TestProcessClosureKeepsDurableControlIdleFence(t *testing.T) {
	for _, event := range []string{"awf_process_exit", "awf_process_closed"} {
		t.Run(event, func(t *testing.T) {
			s := testServer(t)
			task := createTask(t, s, "live-close-fence")
			if err := s.store.Update(func(st *core.State) error {
				ref := st.Tasks[task.ID].Sessions["architect"]
				ref.ProcessID = "closing-process"
				st.Requests["unknown-control"] = &core.Request{ID: "unknown-control", TaskID: task.ID, Role: "architect", SessionID: ref.ID, ProcessID: ref.ProcessID, Operation: "pi/compact", Status: "needs_verification", Dispatched: true}
				return nil
			}); err != nil {
				t.Fatal(err)
			}
			s.piEvent(task.ID, "architect", "closing-process", mustJSON(map[string]string{"type": event}))
			st := s.store.Snapshot()
			ref := st.Tasks[task.ID].Sessions["architect"]
			if ref.Available || !ref.Pending || taskPiIdle(st.Tasks[task.ID]) || len(ref.PendingCommands) != 1 || ref.PendingCommands[0] != "unknown-control" {
				t.Fatal("process closure erased durable control idle fence")
			}
			if st.Requests["unknown-control"].Status != "needs_verification" {
				t.Fatal("closure inferred control success")
			}
		})
	}
}

func TestProcessClosureClearsTransientDialogFence(t *testing.T) {
	for _, event := range []string{"awf_process_exit", "awf_process_closed"} {
		t.Run(event, func(t *testing.T) {
			s := testServer(t)
			task := createTask(t, s, "closed-dialog")
			if err := s.store.Update(func(st *core.State) error {
				ref := st.Tasks[task.ID].Sessions["architect"]
				ref.ProcessID = "closing-process"
				ref.PendingUI = []json.RawMessage{json.RawMessage(`{"id":"dialog"}`)}
				refreshPending(ref)
				return nil
			}); err != nil {
				t.Fatal(err)
			}
			s.piEvent(task.ID, "architect", "closing-process", mustJSON(map[string]string{"type": event}))
			st := s.store.Snapshot()
			ref := st.Tasks[task.ID].Sessions["architect"]
			if ref.Available || ref.Pending || len(ref.PendingUI) != 0 || !taskPiIdle(st.Tasks[task.ID]) {
				t.Fatal("closed dialog left ghost pending fence")
			}
		})
	}
}
