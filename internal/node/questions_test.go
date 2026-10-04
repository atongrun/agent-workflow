package node

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http/httptest"
	"net/url"
	"os"
	"sync"
	"testing"

	"github.com/atongrun/agent-workflow/internal/opencode"
)

func questionCall(t *testing.T, s *Server, method, path string, in any) *httptest.ResponseRecorder {
	t.Helper()
	b, _ := json.Marshal(in)
	r := httptest.NewRequest(method, path, bytes.NewReader(b))
	r.RemoteAddr = "127.0.0.1:1234"
	r.Header.Set("Authorization", "Bearer "+s.cfg.Token)
	w := httptest.NewRecorder()
	s.ServeHTTP(w, r)
	return w
}
func questionFixture(t *testing.T) (*Server, *fakeNative, Config, Job, QuestionReplyInput, string) {
	t.Helper()
	f := newNative(t, t.TempDir())
	cfg := configFor(t, f)
	s := startNode(t, cfg)
	code, job := call(t, s, "POST", "/v1/jobs", req("question-run"))
	if code != 202 {
		t.Fatal(code)
	}
	job = waitJob(t, s, job.ID, func(j Job) bool { return j.SubmissionState == "submitted" })
	qid := "que_question"
	f.mu.Lock()
	m := opencode.Message{Info: opencode.MessageInfo{ID: "msg_question", SessionID: job.SessionID, ParentID: job.MessageID, Role: "assistant"}, Parts: []opencode.Part{{ID: "part_question", Type: "tool", SessionID: job.SessionID, MessageID: "msg_question", Tool: "question", CallID: "call_question", State: opencode.ToolState{Status: "running"}}}}
	f.messages[job.SessionID] = append(f.messages[job.SessionID], m)
	custom := false
	q := opencode.Question{ID: qid, SessionID: job.SessionID, Tool: &opencode.QuestionTool{MessageID: m.Info.ID, CallID: "call_question"}, Questions: []opencode.QuestionInfo{{Question: "Continue?", Header: "Scope", Options: []opencode.QuestionOption{{Label: "Yes", Description: "Continue approved scope"}}, Custom: &custom}}}
	raw, _ := json.Marshal(q)
	f.questions = []json.RawMessage{raw}
	f.mu.Unlock()
	return s, f, cfg, job, QuestionReplyInput{RequestID: "answer", TaskID: job.TaskID, ExecutionRequestID: job.RequestID, SessionID: job.SessionID, Answers: [][]string{{"Yes"}}}, qid
}
func questionQuery(job Job) string {
	return url.Values{"taskId": {job.TaskID}, "executionRequestId": {job.RequestID}, "sessionId": {job.SessionID}}.Encode()
}
func TestQuestionBindingValidationAndAuth(t *testing.T) {
	s, f, _, job, in, qid := questionFixture(t)
	path := "/v1/jobs/" + job.ID + "/questions"
	if w := questionCall(t, s, "GET", path+"?"+questionQuery(job), nil); w.Code != 200 {
		t.Fatal(w.Code, w.Body.String())
	}
	for _, field := range []string{"task", "session", "execution", "answer"} {
		bad := in
		switch field {
		case "task":
			bad.TaskID = "other"
		case "session":
			bad.SessionID = "ses_other"
		case "execution":
			bad.ExecutionRequestID = "other"
		case "answer":
			bad.Answers = [][]string{{"Not offered"}}
		}
		w := questionCall(t, s, "POST", path+"/"+qid+"/reply", bad)
		if w.Code != 409 && w.Code != 400 {
			t.Fatal(w.Code, w.Body.String())
		}
	}
	f.mu.Lock()
	wrong := opencode.Question{ID: "que_other", SessionID: job.SessionID, Tool: &opencode.QuestionTool{MessageID: "msg_prior", CallID: "call_question"}, Questions: []opencode.QuestionInfo{{Question: "Old turn"}}}
	raw, _ := json.Marshal(wrong)
	f.questions = append(f.questions, raw)
	f.mu.Unlock()
	if w := questionCall(t, s, "POST", path+"/que_other/reply", in); w.Code != 409 {
		t.Fatal("old turn answered", w.Code)
	}
	r := httptest.NewRequest("POST", path+"/"+qid+"/reply", nil)
	r.RemoteAddr = "127.0.0.1:1234"
	w := httptest.NewRecorder()
	s.ServeHTTP(w, r)
	if w.Code != 401 {
		t.Fatal(w.Code)
	}
	f.mu.Lock()
	count := f.questionReplies
	f.mu.Unlock()
	if count != 0 {
		t.Fatal("invalid request sent native reply")
	}
}
func TestQuestionConcurrentRepliesAndRestartReceipts(t *testing.T) {
	s, f, cfg, job, in, qid := questionFixture(t)
	path := "/v1/jobs/" + job.ID + "/questions/" + qid + "/reply"
	var wg sync.WaitGroup
	for range 12 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if w := questionCall(t, s, "POST", path, in); w.Code != 202 && w.Code != 200 {
				t.Errorf("%d %s", w.Code, w.Body.String())
			}
		}()
	}
	wg.Wait()
	f.mu.Lock()
	count := f.questionReplies
	f.mu.Unlock()
	if count != 1 {
		t.Fatal(count)
	}
	changed := in
	changed.Answers = [][]string{{"No"}}
	if w := questionCall(t, s, "POST", path, changed); w.Code != 409 {
		t.Fatal("changed payload accepted")
	}
	changed = in
	changed.RequestID = "other-answer"
	if w := questionCall(t, s, "POST", path, changed); w.Code != 409 {
		t.Fatal("new identity reanswered")
	}
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	reopened := startNode(t, cfg)
	if w := questionCall(t, reopened, "POST", path, in); w.Code != 200 {
		t.Fatal(w.Code, w.Body.String())
	}
	if w := questionCall(t, reopened, "GET", "/v1/jobs/"+job.ID+"/question-replies/"+in.RequestID+"?"+questionQuery(job), nil); w.Code != 200 {
		t.Fatal(w.Code, w.Body.String())
	}
	f.mu.Lock()
	count = f.questionReplies
	f.mu.Unlock()
	if count != 1 {
		t.Fatal("restart resent native reply")
	}
}
func TestQuestionLostACKNeverResends(t *testing.T) {
	s, f, _, job, in, qid := questionFixture(t)
	f.mu.Lock()
	f.dropQuestionReply = true
	f.mu.Unlock()
	path := "/v1/jobs/" + job.ID + "/questions/" + qid + "/reply"
	for range 2 {
		w := questionCall(t, s, "POST", path, in)
		if w.Code != 202 && w.Code != 200 {
			t.Fatal(w.Code, w.Body.String())
		}
		var out struct{ Reply QuestionReply }
		_ = json.Unmarshal(w.Body.Bytes(), &out)
		if out.Reply.Status != "needs_verification" {
			t.Fatal(w.Body.String())
		}
	}
	f.mu.Lock()
	count := f.questionReplies
	f.mu.Unlock()
	if count != 1 {
		t.Fatal(count)
	}
}
func TestQuestionACKPersistenceFailureRemainsUnknown(t *testing.T) {
	s, f, cfg, job, in, qid := questionFixture(t)
	backup := s.jobsDir + "-backup"
	f.mu.Lock()
	f.afterQuestionReply = func() {
		if err := os.Rename(s.jobsDir, backup); err != nil {
			t.Error(err)
		}
	}
	f.mu.Unlock()
	path := "/v1/jobs/" + job.ID + "/questions/" + qid + "/reply"
	if w := questionCall(t, s, "POST", path, in); w.Code != 503 {
		t.Fatal(w.Code, w.Body.String())
	}
	if w := questionCall(t, s, "POST", path, in); w.Code != 200 || bytes.Contains(w.Body.Bytes(), []byte(`"status":"completed"`)) {
		t.Fatal(w.Code, w.Body.String())
	}
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(backup, s.jobsDir); err != nil {
		t.Fatal(err)
	}
	reopened := startNode(t, cfg)
	if w := questionCall(t, reopened, "POST", path, in); w.Code != 200 || bytes.Contains(w.Body.Bytes(), []byte(`"status":"completed"`)) {
		t.Fatal(w.Code, w.Body.String())
	}
	f.mu.Lock()
	count := f.questionReplies
	f.mu.Unlock()
	if count != 1 {
		t.Fatal("uncertain persistence resent reply")
	}
}
func TestQuestionAnswerShapes(t *testing.T) {
	noCustom := false
	yesCustom := true
	cases := []struct {
		q       opencode.Question
		answers [][]string
		ok      bool
	}{
		{opencode.Question{Questions: []opencode.QuestionInfo{{Custom: &noCustom, Options: []opencode.QuestionOption{{Label: "A"}, {Label: "B"}}}}}, [][]string{{"A"}}, true},
		{opencode.Question{Questions: []opencode.QuestionInfo{{Custom: &noCustom, Options: []opencode.QuestionOption{{Label: "A"}}}}}, [][]string{{"other"}}, false},
		{opencode.Question{Questions: []opencode.QuestionInfo{{Custom: &yesCustom}}}, [][]string{{"free answer"}}, true},
		{opencode.Question{Questions: []opencode.QuestionInfo{{}}}, nil, false},
		{opencode.Question{Questions: []opencode.QuestionInfo{{}}}, [][]string{{"A", "B"}}, false},
		{opencode.Question{Questions: []opencode.QuestionInfo{{Multiple: true}}}, [][]string{{"A", "B"}}, true},
		{opencode.Question{Questions: []opencode.QuestionInfo{{Multiple: true}}}, [][]string{{"A", "A"}}, false},
	}
	for _, c := range cases {
		if questionAnswerValid(c.q, c.answers) != c.ok {
			t.Fatal(c)
		}
	}
}

func TestQuestionNativeRejectionIsDurable(t *testing.T) {
	for _, code := range []int{400, 404} {
		t.Run(fmt.Sprint(code), func(t *testing.T) {
			s, f, _, job, in, qid := questionFixture(t)
			f.mu.Lock()
			f.questionReplyStatus = code
			f.mu.Unlock()
			path := "/v1/jobs/" + job.ID + "/questions/" + qid + "/reply"
			for range 2 {
				w := questionCall(t, s, "POST", path, in)
				if w.Code != 202 && w.Code != 200 {
					t.Fatal(w.Code, w.Body.String())
				}
				var out struct{ Reply QuestionReply }
				json.Unmarshal(w.Body.Bytes(), &out)
				if out.Reply.Status != "failed" || out.Reply.ErrorCode == "" {
					t.Fatal(w.Body.String())
				}
			}
			f.mu.Lock()
			count := f.questionReplies
			f.mu.Unlock()
			if count != 0 {
				t.Fatal("rejected answer accepted")
			}
		})
	}
}
func TestQuestionMalformedNativeToolCannotBeAnswered(t *testing.T) {
	for _, field := range []string{"message", "call", "part"} {
		t.Run(field, func(t *testing.T) {
			s, f, _, job, in, qid := questionFixture(t)
			f.mu.Lock()
			var q opencode.Question
			json.Unmarshal(f.questions[0], &q)
			m := &f.messages[job.SessionID][1]
			switch field {
			case "message":
				q.Tool.MessageID = ""
				m.Info.ID = ""
				m.Parts[0].MessageID = ""
			case "call":
				q.Tool.CallID = ""
				m.Parts[0].CallID = ""
			case "part":
				m.Parts[0].ID = ""
			}
			f.questions[0], _ = json.Marshal(q)
			f.mu.Unlock()
			if w := questionCall(t, s, "POST", "/v1/jobs/"+job.ID+"/questions/"+qid+"/reply", in); w.Code != 409 {
				t.Fatal(w.Code, w.Body.String())
			}
			f.mu.Lock()
			count := f.questionReplies
			f.mu.Unlock()
			if count != 0 {
				t.Fatal("malformed tool answered")
			}
		})
	}
}
