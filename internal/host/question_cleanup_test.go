package host

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"reflect"
	"sync/atomic"
	"testing"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
	"github.com/atongrun/agent-workflow/internal/node"
)

func TestCancelledQuestionCleanupRefreshesOnlyWaits(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "cancel-wait")
	pending := []json.RawMessage{mustJSON(map[string]string{"id": "que_old", "sessionID": "ses_cancelled"})}
	if err := s.store.Update(func(st *core.State) error {
		x := st.Tasks[task.ID]
		x.Status = "cancelled"
		x.Execution = &core.Execution{RequestID: "run", JobID: "job", SessionID: "ses_cancelled", Status: "cancelled", CancelRequested: true, PendingQuestions: pending, Summary: "preserve evidence", AccountedSeconds: 42, Evidence: []core.Evidence{{Source: "old", Verified: false}}, ResultReview: &core.ResultReview{Status: "reviewed", Verdict: "needs_changes"}}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	before, _ := s.task(task.ID)
	job := node.Job{ID: "job", TaskID: task.ID, RequestID: "run", SessionID: "ses_cancelled", Status: "cancelled", CancelRequested: true, AbortConfirmed: true, QuestionCleanupState: "cleared", Summary: "late different summary", ExecutionSeconds: 999}
	bad := job
	bad.SessionID = "other"
	s.applyJob(task.ID, &bad, 0)
	bad = job
	bad.QuestionCleanupState = "needs_verification"
	s.applyJob(task.ID, &bad, 0)
	unchanged, _ := s.task(task.ID)
	if !reflect.DeepEqual(before, unchanged) {
		t.Fatal("unproven receipt changed terminal task")
	}
	s.applyJob(task.ID, &job, 0)
	got, _ := s.task(task.ID)
	want := *before.Execution
	want.PendingQuestions = nil
	if !reflect.DeepEqual(&want, got.Execution) || got.Budget != before.Budget || got.Status != before.Status {
		t.Fatal("wait refresh changed outcome/verdict/counters")
	}
}
func TestCancelledQuestionCleanupOriginalHostRequestRetriesWithoutNewAuthority(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "cancel-retry")
	in := actionInput{RequestID: "original-cancel", ExecutionRequestID: "run", Role: "architect"}
	pending := []json.RawMessage{mustJSON(map[string]string{"id": "que_old", "sessionID": "ses_cancelled"})}
	if _, err := s.reserveRequest(in.RequestID, task.ID, "execution/cancel", in, func(st *core.State, req *core.Request) error {
		x := st.Tasks[task.ID]
		x.Status = "cancelled"
		x.Execution = &core.Execution{RequestID: "run", JobID: "job", SessionID: "ses_cancelled", Status: "cancelled", CancelRequested: true, PendingQuestions: pending}
		req.Status = "accepted_native"
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	var cancels atomic.Int32
	endpoint := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "POST" && r.URL.Path == "/v1/jobs/job/cancel" {
			var body map[string]string
			json.NewDecoder(r.Body).Decode(&body)
			if body["requestId"] != "original-cancel" {
				t.Error("cancellation authority changed")
			}
			cancels.Add(1)
		}
		writeJSON(w, 200, node.Job{ID: "job", TaskID: task.ID, RequestID: "run", SessionID: "ses_cancelled", Status: "cancelled", CancelRequested: true, AbortConfirmed: true, QuestionCleanupState: "cleared"})
	}))
	defer endpoint.Close()
	s.cfg.Nodes["n"] = NodeConfig{URL: endpoint.URL, TokenEnv: "TEST_NODE_TOKEN"}
	path := "/v1/tasks/" + task.ID + "/execution/cancel"
	if w := call(t, s, "POST", path, in); w.Code != 202 {
		t.Fatal(w.Code, w.Body.String())
	}
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) {
		got, _ := s.task(task.ID)
		if len(got.Execution.PendingQuestions) == 0 {
			break
		}
		time.Sleep(time.Millisecond)
	}
	got, _ := s.task(task.ID)
	if len(got.Execution.PendingQuestions) != 0 || cancels.Load() != 1 || got.Execution.Status != "cancelled" {
		t.Fatal("original cancellation did not reconcile waits")
	}
	in.RequestID = "new-cancel"
	if w := call(t, s, "POST", path, in); w.Code != 409 {
		t.Fatal("new terminal cancellation accepted", w.Code)
	}
}
