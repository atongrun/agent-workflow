package host

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
	"github.com/atongrun/agent-workflow/internal/pi"
)

func resumePayload(task *core.Task, id string) map[string]any {
	ref := task.Sessions["architect"]
	return map[string]any{"requestId": id, "role": "architect", "expectedSessionId": ref.ID, "expectedProcessId": ref.ProcessID, "expectedLifecycleRevision": task.LifecycleRevision}
}
func TestPiResumeIsExplicitBoundAndIdempotent(t *testing.T) {
	s, task, _, log, _ := piControlFixture(t, "")
	s.mu.Lock()
	client := s.clients[task.ID+":architect"]
	s.mu.Unlock()
	if err := client.Close(); err != nil {
		t.Fatal(err)
	}
	task, _ = s.task(task.ID)
	old := task.Sessions["architect"].ProcessID
	in := resumePayload(task, "resume-original")
	path := "/v1/tasks/" + task.ID + "/pi/resume"
	w := call(t, s, "POST", path, in)
	if w.Code != 202 {
		t.Fatal(w.Code, w.Body.String())
	}
	req := awaitPiRequest(t, s, "resume-original", "completed")
	var result struct {
		Binding piBinding `json:"binding"`
	}
	if err := json.Unmarshal(req.Result, &result); err != nil {
		t.Fatal(err)
	}
	if result.Binding.SessionID != task.Sessions["architect"].ID || result.Binding.ProcessID == "" || result.Binding.ProcessID == old {
		t.Fatal("resume did not retain session with a fresh process")
	}
	latest, _ := s.task(task.ID)
	if !latest.Sessions["architect"].Available || latest.Execution != nil || methodCount(t, log, "prompt") != 0 {
		t.Fatal("resume generated or executed work")
	}
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if w := call(t, s, "POST", path, in); w.Code != 202 {
				t.Errorf("exact retry %d", w.Code)
			}
		}()
	}
	wg.Wait()
	latest, _ = s.task(task.ID)
	if latest.Sessions["architect"].ProcessID != result.Binding.ProcessID {
		t.Fatal("exact retry started another process")
	}
	if w := call(t, s, "POST", "/v1/tasks/"+task.ID+"/requests/resume-original", map[string]any{"requestId": "resume-original", "operation": "pi/resume", "payload": in}); w.Code != 200 {
		t.Fatal(w.Code, w.Body.String())
	}
	in["expectedProcessId"] = "different"
	if w := call(t, s, "POST", path, in); w.Code != 409 {
		t.Fatal("conflicting payload accepted", w.Code)
	}
}
func TestPiResumeRejectsStaleAndUnknownReceipts(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "resume-rejections")
	path := "/v1/tasks/" + task.ID + "/pi/resume"
	for _, field := range []string{"expectedSessionId", "expectedProcessId", "expectedLifecycleRevision"} {
		in := resumePayload(task, "stale-"+field)
		if field == "expectedLifecycleRevision" {
			in[field] = 1
		} else {
			in[field] = "stale"
		}
		if w := call(t, s, "POST", path, in); w.Code != 409 {
			t.Fatal(field, w.Code, w.Body.String())
		}
	}
	if err := s.store.Update(func(st *core.State) error {
		st.Requests["uncertain-resume"] = &core.Request{ID: "uncertain-resume", TaskID: task.ID, Role: "architect", Operation: "pi/resume", Status: "needs_verification", Dispatched: true}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	if w := call(t, s, "POST", path, resumePayload(task, "new-resume")); w.Code != 409 {
		t.Fatal("unknown resume bypassed", w.Code)
	}
}

func TestPiResumeRequiredFieldsAndHTTPValidation(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "resume-input")
	path := "/v1/tasks/" + task.ID + "/pi/resume"
	for _, field := range []string{"requestId", "role", "expectedSessionId", "expectedProcessId", "expectedLifecycleRevision"} {
		in := resumePayload(task, "missing-"+field)
		delete(in, field)
		if w := call(t, s, "POST", path, in); w.Code != 400 {
			t.Fatal(field, w.Code, w.Body.String())
		}
	}
	in := resumePayload(task, "bad-role")
	in["role"] = "executor"
	if w := call(t, s, "POST", path, in); w.Code != 400 {
		t.Fatal(w.Code)
	}
	in = resumePayload(task, "null-process")
	in["expectedProcessId"] = nil
	if w := call(t, s, "POST", path, in); w.Code != 400 {
		t.Fatal(w.Code)
	}
	in = resumePayload(task, "unknown-field")
	in["activate"] = true
	if w := call(t, s, "POST", path, in); w.Code != 400 {
		t.Fatal(w.Code)
	}
	if w := call(t, s, "POST", path+"?role=architect", resumePayload(task, "query")); w.Code != 400 {
		t.Fatal(w.Code)
	}
	if len(s.store.Snapshot().Requests) != 1 {
		t.Fatal("invalid resume reserved a receipt")
	}
}

func TestPiResumeCapacityProtectsAwaitingVerdict(t *testing.T) {
	s, task, _, _, _ := piControlFixture(t, "")
	if err := s.store.Update(func(st *core.State) error { st.Tasks[task.ID].Status = "reporting"; return nil }); err != nil {
		t.Fatal(err)
	}
	other := createTask(t, s, "resume-over-capacity")
	w := call(t, s, "POST", "/v1/tasks/"+other.ID+"/pi/resume", resumePayload(other, "capacity-resume"))
	if w.Code != 409 || !strings.Contains(w.Body.String(), "pi_capacity") {
		t.Fatal(w.Code, w.Body.String())
	}
	if s.store.Snapshot().Requests["capacity-resume"] != nil {
		t.Fatal("capacity rejection dispatched")
	}
	original, _ := s.task(task.ID)
	if !original.Sessions["architect"].Available {
		t.Fatal("capacity rejection displaced protected process")
	}
}

func TestPiResumeUnknownExactRetryAfterRestartDoesNotStart(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "resume-unknown")
	var in piResumeInput
	if err := json.Unmarshal(mustJSON(resumePayload(task, "unknown-original")), &in); err != nil {
		t.Fatal(err)
	}
	_, err := s.reserveRequest("unknown-original", task.ID, "pi/resume", in, func(st *core.State, req *core.Request) error {
		req.Role = "architect"
		req.SessionID = task.Sessions["architect"].ID
		req.Status = "needs_verification"
		req.Dispatched = true
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	original := string(mustJSON(s.store.Snapshot().Requests["unknown-original"]))
	s.Close()
	reopened, err := New(s.cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	w := call(t, reopened, "POST", "/v1/tasks/"+task.ID+"/pi/resume", in)
	if w.Code != 202 {
		t.Fatal(w.Code, w.Body.String())
	}
	if string(mustJSON(reopened.store.Snapshot().Requests["unknown-original"])) != original {
		t.Fatal("exact retry rewrote unknown receipt")
	}
	if reopened.store.Snapshot().Tasks[task.ID].Sessions["architect"].Available || len(reopened.clients) != 0 {
		t.Fatal("unknown resume replayed startup")
	}
	if w := call(t, reopened, "POST", "/v1/tasks/"+task.ID+"/pi/resume", resumePayload(task, "replacement")); w.Code != 409 {
		t.Fatal("restart lost unknown resume fence", w.Code)
	}
}

func TestPiResumePreStartupFailureDoesNotLeaveUnknownGate(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "resume-no-catalog")
	in := resumePayload(task, "resume-before-start")
	path := "/v1/tasks/" + task.ID + "/pi/resume"
	if w := call(t, s, "POST", path, in); w.Code != 202 {
		t.Fatal(w.Code, w.Body.String())
	}
	req := awaitPiRequest(t, s, "resume-before-start", "failed")
	if req.Dispatched || len(s.clients) != 0 || s.store.Snapshot().Tasks[task.ID].Sessions["architect"].Pending {
		t.Fatal("pre-start failure retained dispatch gate")
	}
	original := string(mustJSON(req))
	if w := call(t, s, "POST", path, in); w.Code != 202 {
		t.Fatal(w.Code)
	}
	if string(mustJSON(s.store.Snapshot().Requests[req.ID])) != original {
		t.Fatal("failed exact retry replayed")
	}
	if w := call(t, s, "POST", path, resumePayload(task, "resume-new-attempt")); w.Code != 202 {
		t.Fatal(w.Code, w.Body.String())
	}
	awaitPiRequest(t, s, "resume-new-attempt", "failed")
}

func TestPiResumeMissingPersistedEvictionCandidateRejectsBeforeReservation(t *testing.T) {
	s, task, _, log, _ := piControlFixture(t, "")
	if err := s.store.Update(func(st *core.State) error {
		ref := st.Tasks[task.ID].Sessions["architect"]
		ref.Persisted = true
		ref.File = filepath.Join(t.TempDir(), "missing.jsonl")
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	other := createTask(t, s, "resume-missing-candidate")
	before, _ := os.ReadFile(log)
	w := call(t, s, "POST", "/v1/tasks/"+other.ID+"/pi/resume", resumePayload(other, "resume-missing"))
	if w.Code != 409 || !strings.Contains(w.Body.String(), "pi_capacity") || s.store.Snapshot().Requests["resume-missing"] != nil {
		t.Fatal(w.Code, w.Body.String())
	}
	after, _ := os.ReadFile(log)
	if !reflect.DeepEqual(before, after) || !s.store.Snapshot().Tasks[task.ID].Sessions["architect"].Available {
		t.Fatal("rejected activation changed original process")
	}
}

func TestPiResumeAttemptedStartupFailureRemainsFenced(t *testing.T) {
	s, task, _, _, _ := piControlFixture(t, "")
	if err := s.clients[task.ID+":architect"].Close(); err != nil {
		t.Fatal(err)
	}
	task, _ = s.task(task.ID)
	s.cfg.PiBinary = filepath.Join(t.TempDir(), "missing-pi")
	in := resumePayload(task, "resume-start-failure")
	path := "/v1/tasks/" + task.ID + "/pi/resume"
	if w := call(t, s, "POST", path, in); w.Code != 202 {
		t.Fatal(w.Code, w.Body.String())
	}
	req := awaitPiRequest(t, s, "resume-start-failure", "needs_verification")
	if !req.Dispatched || req.ProcessID == task.Sessions["architect"].ProcessID {
		t.Fatal("startup boundary was not durably fenced")
	}
	current, _ := s.task(task.ID)
	if w := call(t, s, "POST", path, resumePayload(current, "resume-replacement")); w.Code != 409 {
		t.Fatal("unknown startup was bypassed", w.Code)
	}
	original := string(mustJSON(req))
	if w := call(t, s, "POST", path, in); w.Code != 202 {
		t.Fatal(w.Code)
	}
	if string(mustJSON(s.store.Snapshot().Requests[req.ID])) != original {
		t.Fatal("unknown exact retry replayed")
	}
}

func TestUnconfirmedEvictionRetainsCapacityOwnership(t *testing.T) {
	s, task, _, log, _ := piControlFixture(t, "")
	key := task.ID + ":architect"
	if err := s.clients[key].Close(); err != nil {
		t.Fatal(err)
	}
	release := make(chan struct{})
	// Hold final callback confirmation after the fixture process has exited.
	client, err := pi.Start(pi.Config{Binary: s.cfg.PiBinary, Directory: t.TempDir(), SessionDirectory: t.TempDir(), SessionID: task.Sessions["architect"].ID, OnEvent: func(raw json.RawMessage) {
		var event struct {
			Type string `json:"type"`
		}
		_ = json.Unmarshal(raw, &event)
		if event.Type == "awf_process_closed" {
			<-release
		}
	}})
	if err != nil {
		t.Fatal(err)
	}
	defer close(release)
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	if _, err := client.Call(ctx, "get_state", nil); err != nil {
		t.Fatal(err)
	}
	s.mu.Lock()
	s.clients[key] = client
	s.mu.Unlock()
	if err := s.store.Update(func(st *core.State) error { st.Tasks[task.ID].Sessions["architect"].Available = true; return nil }); err != nil {
		t.Fatal(err)
	}
	other := createTask(t, s, "unconfirmed-eviction")
	before, _ := os.ReadFile(log)
	if _, err := s.client(other.ID, "architect"); err == nil {
		t.Fatal("started after unconfirmed native exit")
	}
	s.mu.Lock()
	owned := s.clients[key] == client
	starting := s.starting
	s.mu.Unlock()
	after, _ := os.ReadFile(log)
	if !owned || !client.Alive() || starting != 0 || !reflect.DeepEqual(before, after) || s.store.Snapshot().Tasks[other.ID].Sessions["architect"].Available {
		t.Fatalf("unconfirmed generation escaped capacity ownership: owned=%v alive=%v starting=%d logEqual=%v available=%v before=%q after=%q", owned, client.Alive(), starting, reflect.DeepEqual(before, after), s.store.Snapshot().Tasks[other.ID].Sessions["architect"].Available, before, after)
	}
}

func TestDeadClientCannotReplaceProtectedCapacitySlot(t *testing.T) {
	s, protected, _, _, _ := piControlFixture(t, "")
	deadTask := createTask(t, s, "dead-capacity-entry")
	dead, err := pi.Start(pi.Config{Binary: s.cfg.PiBinary, Directory: t.TempDir(), SessionDirectory: t.TempDir(), SessionID: deadTask.Sessions["architect"].ID})
	if err != nil {
		t.Fatal(err)
	}
	if err := dead.Close(); err != nil {
		t.Fatal(err)
	}
	s.mu.Lock()
	s.clients[deadTask.ID+":architect"] = dead
	s.mu.Unlock()
	if err := s.store.Update(func(st *core.State) error { st.Tasks[protected.ID].Status = "reporting"; return nil }); err != nil {
		t.Fatal(err)
	}
	other := createTask(t, s, "cannot-reclaim-dead-entry")
	if _, err := s.client(other.ID, "architect"); err == nil {
		t.Fatal("dead map entry was counted as a released live capacity slot")
	}
	if !s.store.Snapshot().Tasks[protected.ID].Sessions["architect"].Available || s.store.Snapshot().Tasks[other.ID].Sessions["architect"].Available {
		t.Fatal("protected capacity was oversubscribed")
	}
}
