package host

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
	"github.com/atongrun/agent-workflow/internal/node"
	"github.com/atongrun/agent-workflow/internal/opencode"
)

type questionProxyFixture struct {
	mu            sync.Mutex
	posts         int
	lostACK       bool
	wrongHash     bool
	reject        int
	receiptStatus string
	receipt       *node.QuestionReply
}

func hostQuestionFixture(t *testing.T) (*Server, *core.Task, executionQuestionInput, *questionProxyFixture) {
	t.Helper()
	s := testServer(t)
	task := createTask(t, s, "question-task")
	in := executionQuestionInput{RequestID: "answer", ExecutionRequestID: "run", JobID: "job", SessionID: "ses_native", Answers: [][]string{{"Yes"}}}
	f := &questionProxyFixture{receiptStatus: "completed"}
	native := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		f.mu.Lock()
		defer f.mu.Unlock()
		if r.Header.Get("Authorization") != "Bearer "+strings.Repeat("n", 32) {
			t.Error("missing node authentication")
			w.WriteHeader(401)
			return
		}
		if r.Method == "GET" {
			q := r.URL.Query()
			if len(q) != 3 || q.Get("taskId") != task.ID || q.Get("executionRequestId") != in.ExecutionRequestID || q.Get("sessionId") != in.SessionID {
				t.Error("wrong query binding")
				w.WriteHeader(409)
				return
			}
			if strings.HasSuffix(r.URL.Path, "/questions") {
				writeJSON(w, 200, executionQuestionsView{TaskID: task.ID, JobID: in.JobID, ExecutionRequestID: in.ExecutionRequestID, SessionID: in.SessionID, Questions: []opencode.Question{{ID: "que_question", SessionID: in.SessionID, Tool: &opencode.QuestionTool{MessageID: "msg_question", CallID: "call_question"}, Questions: []opencode.QuestionInfo{{Question: "Continue?"}}}}})
				return
			}
			if f.receipt == nil {
				writeError(w, fail("request_not_found", "not found", 404))
				return
			}
			writeJSON(w, 200, map[string]any{"reply": f.receipt})
			return
		}
		f.posts++
		if f.reject != 0 {
			writeError(w, fail("invalid_answers", "invalid selection", f.reject))
			return
		}
		var body node.QuestionReplyInput
		if json.NewDecoder(r.Body).Decode(&body) != nil || body.TaskID != task.ID || body.SessionID != in.SessionID || body.ExecutionRequestID != in.ExecutionRequestID {
			t.Error("wrong reply binding")
			w.WriteHeader(400)
			return
		}
		receipt := node.QuestionReply{RequestID: body.RequestID, QuestionID: "que_question", TaskID: body.TaskID, JobID: in.JobID, ExecutionRequestID: body.ExecutionRequestID, SessionID: body.SessionID, Status: f.receiptStatus, PayloadHash: node.QuestionReplyHash("que_question", body)}
		if f.wrongHash {
			receipt.PayloadHash = strings.Repeat("0", 64)
		}
		f.receipt = &receipt
		if f.lostACK {
			f.lostACK = false
			conn, _, _ := w.(http.Hijacker).Hijack()
			conn.Close()
			return
		}
		writeJSON(w, 202, map[string]any{"reply": receipt})
	}))
	t.Cleanup(native.Close)
	s.cfg.Nodes["n"] = NodeConfig{URL: native.URL, TokenEnv: "TEST_NODE_TOKEN"}
	if err := s.store.Update(func(st *core.State) error {
		x := st.Tasks[task.ID]
		x.Execution = &core.Execution{RequestID: in.ExecutionRequestID, JobID: in.JobID, SessionID: in.SessionID, Status: "running"}
		x.Status = "executing"
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	return s, task, in, f
}
func hostQuestionPath(task *core.Task) string {
	return "/v1/tasks/" + task.ID + "/execution/questions/que_question/reply"
}
func TestExecutionQuestionProxyBindingAndValidation(t *testing.T) {
	s, task, in, f := hostQuestionFixture(t)
	q := url.Values{"executionRequestId": {in.ExecutionRequestID}, "jobId": {in.JobID}, "sessionId": {in.SessionID}}.Encode()
	if w := call(t, s, "GET", "/v1/tasks/"+task.ID+"/execution/questions?"+q, nil); w.Code != 200 {
		t.Fatal(w.Code, w.Body.String())
	}
	for _, field := range []string{"job", "session", "execution", "answers", "query", "question"} {
		bad := in
		path := hostQuestionPath(task)
		switch field {
		case "job":
			bad.JobID = "other"
		case "session":
			bad.SessionID = "other"
		case "execution":
			bad.ExecutionRequestID = "other"
		case "answers":
			bad.Answers = nil
		case "query":
			path += "?extra=1"
		case "question":
			path = strings.Replace(path, "que_question", "call_question", 1)
		}
		if w := call(t, s, "POST", path, bad); w.Code != 400 && w.Code != 409 {
			t.Fatal(field, w.Code, w.Body.String())
		}
	}
	r := httptest.NewRequest("POST", hostQuestionPath(task), strings.NewReader(string(mustJSON(in))))
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, r)
	if w.Code != 401 {
		t.Fatal("unauthenticated reply accepted", w.Code)
	}
	if f.posts != 0 {
		t.Fatal("invalid reply forwarded")
	}
}
func TestExecutionQuestionConcurrentAndLostProxyACKReconciliation(t *testing.T) {
	s, task, in, f := hostQuestionFixture(t)
	f.lostACK = true
	if w := call(t, s, "POST", hostQuestionPath(task), in); w.Code != 202 {
		t.Fatal(w.Code, w.Body.String())
	}
	if got := s.store.Snapshot().Requests[in.RequestID]; got.Status != "needs_verification" {
		t.Fatal(got)
	}
	var wg sync.WaitGroup
	for range 12 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if w := call(t, s, "POST", hostQuestionPath(task), in); w.Code != 202 {
				t.Error(w.Code, w.Body.String())
			}
		}()
	}
	wg.Wait()
	f.mu.Lock()
	posts := f.posts
	f.mu.Unlock()
	if posts != 1 || s.store.Snapshot().Requests[in.RequestID].Status != "completed" {
		t.Fatal("reply did not reconcile exactly once", posts)
	}
	changed := in
	changed.Answers = [][]string{{"No"}}
	if w := call(t, s, "POST", hostQuestionPath(task), changed); w.Code != 409 {
		t.Fatal("changed payload accepted")
	}
	if w := call(t, s, "GET", "/v1/tasks/"+task.ID+"/requests/"+in.RequestID, nil); w.Code != 200 || !strings.Contains(w.Body.String(), `"status":"completed"`) {
		t.Fatal(w.Code, w.Body.String())
	}
}
func TestExecutionQuestionUnknownAndRejectedReceipts(t *testing.T) {
	for _, mode := range []string{"unknown", "wrong_hash", "rejected"} {
		t.Run(mode, func(t *testing.T) {
			s, task, in, f := hostQuestionFixture(t)
			want := 202
			status := "needs_verification"
			if mode == "unknown" {
				f.receiptStatus = "needs_verification"
			}
			if mode == "wrong_hash" {
				f.wrongHash = true
			}
			if mode == "rejected" {
				f.reject = 400
				want = 400
				status = "failed"
			}
			for range 2 {
				if w := call(t, s, "POST", hostQuestionPath(task), in); w.Code != want {
					t.Fatal(w.Code, w.Body.String())
				}
			}
			if f.posts != 1 || s.store.Snapshot().Requests[in.RequestID].Status != status {
				t.Fatal("retry resent or false completion", f.posts)
			}
		})
	}
}
func TestExecutionQuestionHistoricalReceiptOnly(t *testing.T) {
	s, task, in, f := hostQuestionFixture(t)
	f.lostACK = true
	call(t, s, "POST", hostQuestionPath(task), in)
	if err := s.store.Update(func(st *core.State) error {
		x := st.Tasks[task.ID]
		x.ExecutionHistory = append(x.ExecutionHistory, *x.Execution)
		x.Execution = &core.Execution{RequestID: "new", JobID: "new", SessionID: "ses_new", Status: "running"}
		now := time.Now()
		x.DeletedAt = &now
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	if w := call(t, s, "POST", hostQuestionPath(task), in); w.Code != 202 {
		t.Fatal(w.Code, w.Body.String())
	}
	if f.posts != 1 || s.store.Snapshot().Requests[in.RequestID].Status != "completed" {
		t.Fatal("historical receipt resent or failed to reconcile")
	}
	fresh := in
	fresh.RequestID = "fresh"
	if w := call(t, s, "POST", hostQuestionPath(task), fresh); w.Code != 409 {
		t.Fatal("deleted historical reply accepted", w.Code)
	}
}
