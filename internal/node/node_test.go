package node

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/atongrun/agent-workflow/internal/opencode"
)

type fakeNative struct {
	mu                                  sync.Mutex
	t                                   *testing.T
	workspace                           string
	server                              *httptest.Server
	sessions                            map[string]opencode.Session
	messages                            map[string][]opencode.Message
	statuses                            map[string]opencode.Status
	permissions                         []json.RawMessage
	questions                           []json.RawMessage
	events                              map[chan string]bool
	creates, prompts, aborts, streams   int
	dropPrompt, dropCreate, emptyPrompt bool
	failCreate                          bool
	questionReplies                     int
	questionReplyStatus                 int
	questionRejects                     int
	questionRejectStatus                int
	requests                            int
	dropQuestionReject                  bool
	retainQuestionOnReject              bool
	questionReadStatus                  int
	afterQuestionReject                 func()
	dropQuestionReply                   bool
	afterQuestionReply                  func()
	lastModel                           *opencode.ModelSelection
}

func newNative(t *testing.T, workspace string) *fakeNative {
	f := &fakeNative{t: t, workspace: workspace, sessions: map[string]opencode.Session{}, messages: map[string][]opencode.Message{}, statuses: map[string]opencode.Status{}, events: map[chan string]bool{}}
	f.server = httptest.NewServer(http.HandlerFunc(f.serve))
	t.Cleanup(f.server.Close)
	return f
}
func (f *fakeNative) serve(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/global/health" && r.URL.Query().Get("directory") != f.workspace {
		f.t.Errorf("directory missing or changed: %s", r.URL)
		http.Error(w, "wrong directory", 403)
		return
	}
	if r.URL.Path == "/event" {
		w.Header().Set("Content-Type", "text/event-stream")
		fmt.Fprint(w, "data: {\"type\":\"server.connected\",\"properties\":{}}\n\n")
		w.(http.Flusher).Flush()
		ch := make(chan string, 8)
		f.mu.Lock()
		f.events[ch] = true
		f.streams++
		f.mu.Unlock()
		defer func() { f.mu.Lock(); delete(f.events, ch); f.mu.Unlock() }()
		for {
			select {
			case <-r.Context().Done():
				return
			case msg := <-ch:
				if msg == "disconnect" {
					return
				}
				fmt.Fprintf(w, "data: %s\n\n", msg)
				w.(http.Flusher).Flush()
			}
		}
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	f.requests++
	respond := func(v any) { w.Header().Set("Content-Type", "application/json"); _ = json.NewEncoder(w).Encode(v) }
	switch r.URL.Path {
	case "/global/health":
		respond(opencode.Health{Healthy: true, Version: "1.18.34"})
		return
	case "/permission":
		if f.permissions == nil {
			respond([]any{})
		} else {
			respond(f.permissions)
		}
		return
	case "/question":
		if f.questionReadStatus != 0 {
			http.Error(w, "unavailable", f.questionReadStatus)
			return
		}
		if f.questions == nil {
			respond([]any{})
		} else {
			respond(f.questions)
		}
		return
	case "/session/status":
		respond(f.statuses)
		return
	case "/session":
		if r.Method == "POST" {
			if f.failCreate {
				f.creates++
				http.Error(w, "native setup unavailable", 503)
				return
			}
			var req struct {
				Title string `json:"title"`
			}
			_ = json.NewDecoder(r.Body).Decode(&req)
			f.creates++
			id := fmt.Sprintf("ses_%d", f.creates)
			s := opencode.Session{ID: id, Title: req.Title, Directory: f.workspace}
			f.sessions[id] = s
			if f.dropCreate {
				f.dropCreate = false
				conn, _, _ := w.(http.Hijacker).Hijack()
				conn.Close()
				return
			}
			respond(s)
			return
		}
		out := []opencode.Session{}
		for _, s := range f.sessions {
			out = append(out, s)
		}
		respond(out)
		return
	}
	if strings.HasPrefix(r.URL.Path, "/question/") && strings.HasSuffix(r.URL.Path, "/reject") && r.Method == "POST" {
		qid := strings.TrimSuffix(strings.TrimPrefix(r.URL.Path, "/question/"), "/reject")
		found := false
		kept := []json.RawMessage{}
		for _, raw := range f.questions {
			var q opencode.Question
			json.Unmarshal(raw, &q)
			if q.ID == qid {
				found = true
				if f.retainQuestionOnReject {
					kept = append(kept, raw)
				}
			} else {
				kept = append(kept, raw)
			}
		}
		if !found {
			http.Error(w, "expired", 404)
			return
		}
		f.questions = kept
		f.questionRejects++
		if f.afterQuestionReject != nil {
			f.afterQuestionReject()
		}
		if f.dropQuestionReject {
			f.dropQuestionReject = false
			conn, _, _ := w.(http.Hijacker).Hijack()
			conn.Close()
			return
		}
		if f.questionRejectStatus != 0 {
			http.Error(w, "expired", f.questionRejectStatus)
			return
		}
		respond(true)
		return
	}
	if strings.HasPrefix(r.URL.Path, "/question/") && strings.HasSuffix(r.URL.Path, "/reply") && r.Method == "POST" {
		if f.questionReplyStatus != 0 {
			http.Error(w, "native question rejection", f.questionReplyStatus)
			return
		}
		qid := strings.TrimSuffix(strings.TrimPrefix(r.URL.Path, "/question/"), "/reply")
		var body struct {
			Answers [][]string `json:"answers"`
		}
		if json.NewDecoder(r.Body).Decode(&body) != nil {
			http.Error(w, "bad JSON", 400)
			return
		}
		found := false
		kept := []json.RawMessage{}
		for _, raw := range f.questions {
			var q opencode.Question
			_ = json.Unmarshal(raw, &q)
			if q.ID == qid {
				found = true
			} else {
				kept = append(kept, raw)
			}
		}
		if !found {
			http.Error(w, "expired question", 404)
			return
		}
		f.questions = kept
		f.questionReplies++
		if f.afterQuestionReply != nil {
			f.afterQuestionReply()
		}
		if f.dropQuestionReply {
			f.dropQuestionReply = false
			conn, _, _ := w.(http.Hijacker).Hijack()
			conn.Close()
			return
		}
		respond(true)
		return
	}
	bits := strings.Split(strings.Trim(r.URL.Path, "/"), "/")
	if len(bits) < 2 || bits[0] != "session" {
		http.NotFound(w, r)
		return
	}
	id := bits[1]
	s, ok := f.sessions[id]
	if !ok {
		http.NotFound(w, r)
		return
	}
	if len(bits) == 2 {
		respond(s)
		return
	}
	switch bits[2] {
	case "message":
		m := f.messages[id]
		if m == nil {
			m = []opencode.Message{}
		}
		respond(m)
	case "prompt_async":
		var req struct {
			MessageID string                   `json:"messageID"`
			Parts     []map[string]string      `json:"parts"`
			Model     *opencode.ModelSelection `json:"model"`
		}
		if json.NewDecoder(r.Body).Decode(&req) != nil {
			http.Error(w, "bad JSON", 400)
			return
		}
		f.prompts++
		f.lastModel = req.Model
		if !strings.HasPrefix(req.MessageID, "msg_") || len(req.MessageID) != 30 {
			f.t.Errorf("non-native-shaped message ID: %s", req.MessageID)
		}
		if !f.emptyPrompt {
			m := opencode.Message{Info: opencode.MessageInfo{ID: req.MessageID, SessionID: id, Role: "user"}}
			m.Info.Time.Created = time.Now().UnixMilli()
			f.messages[id] = append(f.messages[id], m)
			f.statuses[id] = opencode.Status{Type: "busy"}
		}
		if f.dropPrompt {
			f.dropPrompt = false
			conn, _, _ := w.(http.Hijacker).Hijack()
			conn.Close()
			return
		}
		w.WriteHeader(http.StatusNoContent)
	case "abort":
		f.aborts++
		delete(f.statuses, id)
		respond(true)
	default:
		http.NotFound(w, r)
	}
}
func (f *fakeNative) counts() (int, int, int) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.creates, f.prompts, f.aborts
}
func (f *fakeNative) complete(id string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	messages := f.messages[id]
	if len(messages) == 0 {
		f.t.Fatal("missing native user message")
	}
	parent := messages[len(messages)-1].Info.ID
	now := time.Now().UnixMilli()
	tool := opencode.Message{Info: opencode.MessageInfo{ID: "msg_tool", SessionID: id, ParentID: parent, Role: "assistant", Finish: "tool-calls"}, Parts: []opencode.Part{{ID: "prt_test", Type: "tool", Tool: "bash", CallID: "call_test", State: opencode.ToolState{Status: "completed", Input: json.RawMessage(`{"command":"go test ./..."}`), Output: "FAIL package example", Metadata: json.RawMessage(`{"exit":1}`)}}}}
	tool.Info.Time.Created = now - 40
	tool.Info.Time.Completed = now - 20
	final := opencode.Message{Info: opencode.MessageInfo{ID: "msg_final", SessionID: id, ParentID: parent, Role: "assistant", Finish: "stop"}, Parts: []opencode.Part{{Type: "text", Text: "Model says all tests passed"}}}
	final.Info.Time.Created = now - 19
	final.Info.Time.Completed = now
	f.messages[id] = append(messages, tool, final)
	delete(f.statuses, id)
}
func (f *fakeNative) broadcast(event any) {
	b, _ := json.Marshal(event)
	f.mu.Lock()
	defer f.mu.Unlock()
	for ch := range f.events {
		ch <- string(b)
	}
}
func (f *fakeNative) disconnect() {
	f.mu.Lock()
	defer f.mu.Unlock()
	for ch := range f.events {
		ch <- "disconnect"
	}
}
func configFor(t *testing.T, f *fakeNative) Config {
	return Config{Token: "test-bearer-32-characters-long-key", StateDir: t.TempDir(), Projects: map[string]string{"example": f.workspace}, OpenCodeURL: f.server.URL, HTTPClient: &http.Client{Timeout: 500 * time.Millisecond}, PollInterval: 15 * time.Millisecond}
}
func startNode(t *testing.T, cfg Config) *Server {
	h, err := New(cfg)
	if err != nil {
		t.Fatal(err)
	}
	s := h.(*Server)
	t.Cleanup(func() { _ = s.Close() })
	return s
}
func call(t *testing.T, s *Server, method, path string, body any) (int, Job) {
	t.Helper()
	b, _ := json.Marshal(body)
	r := httptest.NewRequest(method, path, bytes.NewReader(b))
	r.RemoteAddr = "127.0.0.1:1234"
	r.Header.Set("Authorization", "Bearer test-bearer-32-characters-long-key")
	w := httptest.NewRecorder()
	s.ServeHTTP(w, r)
	var job Job
	if w.Code < 300 && path != "/v1/health" {
		if err := json.Unmarshal(w.Body.Bytes(), &job); err != nil {
			t.Fatalf("decode %s: %v", w.Body.String(), err)
		}
	}
	return w.Code, job
}
func req(id string) JobRequest {
	return JobRequest{RequestID: id, TaskID: "task-1", ProjectID: "example", Repository: "example/repository", Branch: "awf/test", Plan: "Run test", Prompt: "Implement the approved change", TimeoutSeconds: 60}
}
func waitJob(t *testing.T, s *Server, id string, predicate func(Job) bool) Job {
	t.Helper()
	deadline := time.Now().Add(4 * time.Second)
	var last Job
	for time.Now().Before(deadline) {
		code, j := call(t, s, "GET", "/v1/jobs/"+id, nil)
		if code != 200 {
			t.Fatalf("get job: %d", code)
		}
		last = j
		if predicate(j) {
			return j
		}
		time.Sleep(15 * time.Millisecond)
	}
	t.Fatalf("job did not reach expected state: %+v", last)
	return last
}
func TestDispatchIdempotencyEvidenceAndRestart(t *testing.T) {
	f := newNative(t, t.TempDir())
	cfg := configFor(t, f)
	s := startNode(t, cfg)
	code, job := call(t, s, "POST", "/v1/jobs", req("one"))
	if code != 202 || job.ID != JobID("one") {
		t.Fatalf("submit %d: %+v", code, job)
	}
	job = waitJob(t, s, job.ID, func(j Job) bool { return j.NativeStatus == "busy" })
	code, again := call(t, s, "POST", "/v1/jobs", req("one"))
	if code != 200 || again.SessionID != job.SessionID {
		t.Fatal("duplicate did not return same job")
	}
	altered := req("one")
	altered.Prompt = "different"
	if code, _ = call(t, s, "POST", "/v1/jobs", altered); code != 409 {
		t.Fatalf("conflict got %d", code)
	}
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	f.complete(job.SessionID)
	restarted := startNode(t, cfg)
	final := waitJob(t, restarted, job.ID, func(j Job) bool { return j.Status == "completed" })
	if final.SessionID != job.SessionID || final.MessageID != job.MessageID {
		t.Fatal("identity changed after restart")
	}
	if len(final.Evidence) != 1 || final.Evidence[0].Verified || final.Evidence[0].Output != "FAIL package example" {
		t.Fatalf("lost unverified tool evidence: %+v", final.Evidence)
	}
	if !strings.Contains(final.Summary, "Model says") || final.ExecutionSeconds <= 0 {
		t.Fatalf("missing summary/runtime: %+v", final)
	}
	c, p, _ := f.counts()
	if c != 1 || p != 1 {
		t.Fatalf("duplicated native work create=%d prompt=%d", c, p)
	}
}
func TestLostPromptResponseNeverReplays(t *testing.T) {
	f := newNative(t, t.TempDir())
	f.dropPrompt = true
	cfg := configFor(t, f)
	s := startNode(t, cfg)
	_, job := call(t, s, "POST", "/v1/jobs", req("lost"))
	job = waitJob(t, s, job.ID, func(j Job) bool { return j.NativeStatus == "busy" })
	_ = s.Close()
	s = startNode(t, cfg)
	for i := 0; i < 4; i++ {
		call(t, s, "POST", "/v1/jobs", req("lost"))
		call(t, s, "GET", "/v1/jobs/"+job.ID, nil)
	}
	_, p, _ := f.counts()
	if p != 1 {
		t.Fatalf("uncertain prompt replayed %d times", p)
	}
	f.complete(job.SessionID)
	waitJob(t, s, job.ID, func(j Job) bool { return j.Status == "completed" })
}
func TestLostCreateResponseRecoversUniqueSession(t *testing.T) {
	f := newNative(t, t.TempDir())
	f.dropCreate = true
	s := startNode(t, configFor(t, f))
	_, job := call(t, s, "POST", "/v1/jobs", req("create-loss"))
	waitJob(t, s, job.ID, func(j Job) bool { return j.NativeStatus == "busy" })
	c, p, _ := f.counts()
	if c != 1 || p != 1 {
		t.Fatalf("creation replayed: %d/%d", c, p)
	}
}
func TestAcceptedIdleIsNotCompletionOrRetry(t *testing.T) {
	f := newNative(t, t.TempDir())
	f.emptyPrompt = true
	cfg := configFor(t, f)
	s := startNode(t, cfg)
	_, job := call(t, s, "POST", "/v1/jobs", req("accepted"))
	job = waitJob(t, s, job.ID, func(j Job) bool { return j.SubmissionState == "submitted" && j.Status == "uncertain" })
	_ = s.Close()
	s = startNode(t, cfg)
	time.Sleep(75 * time.Millisecond)
	_, job = call(t, s, "GET", "/v1/jobs/"+job.ID, nil)
	if job.Status != "uncertain" {
		t.Fatalf("idle promoted: %+v", job)
	}
	_, p, _ := f.counts()
	if p != 1 {
		t.Fatal("accepted prompt retried")
	}
}
func TestProjectSerializationAndCancellation(t *testing.T) {
	f := newNative(t, t.TempDir())
	s := startNode(t, configFor(t, f))
	_, first := call(t, s, "POST", "/v1/jobs", req("first"))
	first = waitJob(t, s, first.ID, func(j Job) bool { return j.NativeStatus == "busy" })
	secondReq := req("second")
	secondReq.TaskID = "task-2"
	_, second := call(t, s, "POST", "/v1/jobs", secondReq)
	time.Sleep(50 * time.Millisecond)
	_, p, _ := f.counts()
	if p != 1 {
		t.Fatal("project ran concurrently")
	}
	code, cancelled := call(t, s, "POST", "/v1/jobs/"+first.ID+"/cancel", map[string]string{"requestId": "cancel-first"})
	if code != 200 || cancelled.Status != "cancelled" || !cancelled.AbortConfirmed {
		t.Fatalf("cancel unconfirmed: %d %+v", code, cancelled)
	}
	call(t, s, "POST", "/v1/jobs/"+first.ID+"/cancel", map[string]string{"requestId": "cancel-first"})
	waitJob(t, s, second.ID, func(j Job) bool { return j.NativeStatus == "busy" })
	_, p, a := f.counts()
	if p != 2 || a != 1 {
		t.Fatalf("prompt=%d abort=%d", p, a)
	}
}
func TestCancelAlreadyCompletedPreservesOutcome(t *testing.T) {
	f := newNative(t, t.TempDir())
	s := startNode(t, configFor(t, f))
	_, job := call(t, s, "POST", "/v1/jobs", req("done-before-cancel"))
	job = waitJob(t, s, job.ID, func(j Job) bool { return j.NativeStatus == "busy" })
	f.complete(job.SessionID)
	code, _ := call(t, s, "POST", "/v1/jobs/"+job.ID+"/cancel", map[string]string{"requestId": "cancel-late"})
	if code != 200 && code != 409 {
		t.Fatal("unexpected late cancellation response", code)
	}
	_, job = call(t, s, "GET", "/v1/jobs/"+job.ID, nil)
	if job.Status != "completed" || job.AbortConfirmed {
		t.Fatalf("fabricated cancellation: %+v", job)
	}
	_, _, a := f.counts()
	if a != 0 {
		t.Fatal("aborted completed native turn")
	}
}
func TestSessionReuseMustBelongToTask(t *testing.T) {
	f := newNative(t, t.TempDir())
	s := startNode(t, configFor(t, f))
	r := req("unknown")
	r.SessionID = "ses_other"
	if code, _ := call(t, s, "POST", "/v1/jobs", r); code != 409 {
		t.Fatalf("foreign session accepted: %d", code)
	}
	_, job := call(t, s, "POST", "/v1/jobs", req("owner"))
	job = waitJob(t, s, job.ID, func(j Job) bool { return j.NativeStatus == "busy" })
	f.complete(job.SessionID)
	waitJob(t, s, job.ID, func(j Job) bool { return j.Status == "completed" })
	if code, _ := call(t, s, "POST", "/v1/jobs", req("forgot-session")); code != 409 {
		t.Fatal("same-task rework silently created a fresh session")
	}
	changed := req("changed-branch")
	changed.SessionID = job.SessionID
	changed.Branch = "other"
	if code, _ := call(t, s, "POST", "/v1/jobs", changed); code != 409 {
		t.Fatal("same-task rework changed branch")
	}
	r = req("rework")
	r.SessionID = job.SessionID
	_, rework := call(t, s, "POST", "/v1/jobs", r)
	rework = waitJob(t, s, rework.ID, func(j Job) bool { return j.NativeStatus == "busy" })
	if rework.SessionID != job.SessionID || rework.MessageID == job.MessageID {
		t.Fatal("rework identities incorrect")
	}
	c, p, _ := f.counts()
	if c != 1 || p != 2 {
		t.Fatal("rework did not reuse native session")
	}
}
func TestAuthenticationAllowlistLockAndCorruption(t *testing.T) {
	f := newNative(t, t.TempDir())
	cfg := configFor(t, f)
	s := startNode(t, cfg)
	w := httptest.NewRecorder()
	r := httptest.NewRequest("GET", "/v1/health", nil)
	r.RemoteAddr = "127.0.0.1:1234"
	s.ServeHTTP(w, r)
	if w.Code != 401 {
		t.Fatal("unauthenticated health access")
	}
	bad := req("denied")
	bad.ProjectID = "elsewhere"
	if code, _ := call(t, s, "POST", "/v1/jobs", bad); code != 403 {
		t.Fatal("workspace allowlist bypass")
	}
	if _, err := New(cfg); err == nil {
		t.Fatal("same state opened concurrently")
	}
	_ = s.Close()
	if err := os.WriteFile(filepath.Join(cfg.StateDir, "jobs", "job_corrupt.json"), []byte(`{broken`), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := New(cfg); err == nil {
		t.Fatal("corrupt state discarded")
	}
}
func TestWaitSnapshotSurvivesRestartAndReconnect(t *testing.T) {
	f := newNative(t, t.TempDir())
	cfg := configFor(t, f)
	s := startNode(t, cfg)
	_, job := call(t, s, "POST", "/v1/jobs", req("waiting"))
	job = waitJob(t, s, job.ID, func(j Job) bool { return j.NativeStatus == "busy" })
	permission := json.RawMessage(fmt.Sprintf(`{"id":"per_one","sessionID":%q,"permission":"external_directory"}`, job.SessionID))
	question := json.RawMessage(fmt.Sprintf(`{"id":"que_one","sessionID":%q,"questions":[]}`, job.SessionID))
	f.mu.Lock()
	f.permissions = []json.RawMessage{permission}
	f.questions = []json.RawMessage{question}
	f.mu.Unlock()
	job = waitJob(t, s, job.ID, func(j Job) bool { return len(j.PendingPermissions) == 1 && len(j.PendingQuestions) == 1 })
	before := job.ExecutionSeconds
	time.Sleep(60 * time.Millisecond)
	_, job = call(t, s, "GET", "/v1/jobs/"+job.ID, nil)
	if job.ExecutionSeconds != before {
		t.Fatalf("user wait charged: %f -> %f", before, job.ExecutionSeconds)
	}
	_ = s.Close()
	f.mu.Lock()
	f.permissions = nil
	f.questions = nil
	f.mu.Unlock()
	s = startNode(t, cfg)
	waitJob(t, s, job.ID, func(j Job) bool {
		return len(j.PendingPermissions) == 0 && len(j.PendingQuestions) == 0 && j.NativeStatus == "busy"
	})
	f.mu.Lock()
	streams := f.streams
	f.mu.Unlock()
	f.disconnect()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		f.mu.Lock()
		reconnected := f.streams > streams
		f.mu.Unlock()
		if reconnected {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatal("event stream did not reconnect")
}
func TestNativeAsyncErrorIsVisible(t *testing.T) {
	f := newNative(t, t.TempDir())
	f.emptyPrompt = true
	s := startNode(t, configFor(t, f))
	_, job := call(t, s, "POST", "/v1/jobs", req("native-error"))
	job = waitJob(t, s, job.ID, func(j Job) bool { return j.Status == "uncertain" && j.SubmissionState == "submitted" })
	f.broadcast(map[string]any{"type": "session.error", "properties": map[string]any{"sessionID": job.SessionID, "error": map[string]string{"name": "ProviderAuthError", "message": "missing provider auth"}}})
	job = waitJob(t, s, job.ID, func(j Job) bool { return j.Status == "failed" })
	if !strings.Contains(job.Error, "ProviderAuthError") {
		t.Fatalf("native error hidden: %+v", job)
	}
}
func TestTimeoutAbortsNativeWork(t *testing.T) {
	f := newNative(t, t.TempDir())
	s := startNode(t, configFor(t, f))
	r := req("timeout")
	r.TimeoutSeconds = 1
	_, job := call(t, s, "POST", "/v1/jobs", r)
	job = waitJob(t, s, job.ID, func(j Job) bool { return j.Status == "cancelled" })
	if !job.TimedOut || !job.AbortConfirmed || job.ExecutionSeconds < 1 {
		t.Fatalf("timeout not enforced: %+v", job)
	}
}

func TestCancelBeforePromptDoesNotNeedNativeAbort(t *testing.T) {
	f := newNative(t, t.TempDir())
	f.failCreate = true
	s := startNode(t, configFor(t, f))
	_, job := call(t, s, "POST", "/v1/jobs", req("never-dispatched"))
	job = waitJob(t, s, job.ID, func(j Job) bool { return j.SubmissionState == "creating" && j.Status == "uncertain" })
	_, job = call(t, s, "POST", "/v1/jobs/"+job.ID+"/cancel", map[string]string{"requestId": "cancel-no-prompt"})
	if job.Status != "cancelled" || job.AbortConfirmed {
		t.Fatalf("pre-dispatch cancellation incorrect: %+v", job)
	}
	c, p, a := f.counts()
	if c != 1 || p != 0 || a != 0 {
		t.Fatalf("unexpected native operation create=%d prompt=%d abort=%d", c, p, a)
	}
}
func TestConfiguredModelSnapshotAndInvalidShape(t *testing.T) {
	f := newNative(t, t.TempDir())
	cfg := configFor(t, f)
	cfg.OpenCodeModel = &opencode.ModelSelection{ProviderID: "provider", ModelID: "model-a"}
	h, err := New(cfg)
	if err != nil {
		t.Fatal(err)
	}
	s := h.(*Server)
	defer s.Close()
	cfg.OpenCodeModel.ModelID = "mutated"
	if s.cfg.OpenCodeModel.ModelID != "model-a" {
		t.Fatal("caller mutated node model config")
	}

	code, job := call(t, s, "POST", "/v1/jobs", req("configured-model"))
	if code != 202 {
		t.Fatalf("submit: %d", code)
	}
	job = waitJob(t, s, job.ID, func(job Job) bool { return job.Status == "running" })
	if job.Model == nil || job.Model.ModelID != "model-a" {
		t.Fatal("accepted model snapshot missing")
	}
	f.mu.Lock()
	actual := f.lastModel
	f.mu.Unlock()
	if actual == nil || actual.ProviderID != "provider" || actual.ModelID != "model-a" {
		t.Fatal("configured model was not forwarded to native prompt")
	}
	_ = s.Close()
	cfg.OpenCodeModel = &opencode.ModelSelection{ProviderID: "provider", ModelID: "model-b"}
	h, err = New(cfg)
	if err != nil {
		t.Fatal(err)
	}
	restarted := h.(*Server)
	defer restarted.Close()
	_, restored := call(t, restarted, "GET", "/v1/jobs/"+job.ID, nil)
	if restored.Model == nil || restored.Model.ModelID != "model-a" {
		t.Fatal("restart changed an accepted job's model")
	}
	override := map[string]any{"requestId": "override", "taskId": "different", "projectId": "example", "prompt": "work", "model": map[string]string{"providerID": "other", "modelID": "other"}}
	code, _ = call(t, restarted, "POST", "/v1/jobs", override)
	if code != 400 {
		t.Fatalf("caller model override accepted: %d", code)
	}
	for _, model := range []*opencode.ModelSelection{{}, {ProviderID: "provider"}, {ModelID: "model"}, {ProviderID: " provider", ModelID: "model"}} {
		bad := cfg
		bad.OpenCodeModel = model
		handler, err := New(bad)
		if err == nil {
			handler.(*Server).Close()
			t.Fatalf("invalid model accepted: %+v", model)
		}
	}
	for _, raw := range []string{`{"openCodeModel":"provider/model"}`, `{"openCodeModel":{"providerID":1,"modelID":"model"}}`} {
		var invalid Config
		if json.Unmarshal([]byte(raw), &invalid) == nil {
			t.Fatal("invalid model JSON shape accepted")
		}
	}
}

func TestProjectCatalogIsReadOnlyAndPathFree(t *testing.T) {
	f := newNative(t, t.TempDir())
	cfg := configFor(t, f)
	s := startNode(t, cfg)
	read := func() *httptest.ResponseRecorder {
		r := httptest.NewRequest("GET", "/v1/projects", nil)
		r.RemoteAddr = "127.0.0.1:1234"
		r.Header.Set("Authorization", "Bearer "+cfg.Token)
		w := httptest.NewRecorder()
		s.ServeHTTP(w, r)
		return w
	}
	w := read()
	if w.Code != 200 || strings.Contains(w.Body.String(), f.workspace) || strings.Contains(w.Body.String(), cfg.Token) || !strings.Contains(w.Body.String(), `"projectId":"example"`) || !strings.Contains(w.Body.String(), `"ready":true`) {
		t.Fatalf("catalog: %s", w.Body.String())
	}
	if creates, prompts, aborts := f.counts(); creates != 0 || prompts != 0 || aborts != 0 {
		t.Fatal("catalog mutated native state")
	}
	if err := os.Remove(f.workspace); err != nil {
		t.Fatal(err)
	}
	if w = read(); w.Code != 200 || strings.Contains(w.Body.String(), `"ready":true`) {
		t.Fatal("missing workspace advertised ready")
	}
}
