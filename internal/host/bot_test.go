package host

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
)

func boolPtr(v bool) *bool { return &v }

func botServer(t *testing.T, posts *atomic.Int32, listen string, allowed []string) *Server {
	t.Helper()
	t.Setenv("TEST_HOST_TOKEN", strings.Repeat("h", 32))
	t.Setenv("TEST_EXTENSION_TOKEN", strings.Repeat("e", 32))
	t.Setenv("TEST_NODE_TOKEN", strings.Repeat("n", 32))
	t.Setenv("TEST_BOT_TOKEN", strings.Repeat("b", 32))
	t.Setenv("TEST_OTHER_TOKEN", strings.Repeat("o", 32))
	nodeHTTP := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/v1/projects" {
			writeJSON(w, 200, map[string]any{"available": true, "reachable": true, "projects": []map[string]any{{"projectId": "p", "label": "p", "ready": true}, {"projectId": "manual", "label": "manual", "ready": true}}})
			return
		}
		if r.Method == "POST" && r.URL.Path == "/v1/jobs" {
			posts.Add(1)
			http.Error(w, "unknown outcome", 500)
			return
		}
		http.NotFound(w, r)
	}))
	t.Cleanup(nodeHTTP.Close)
	dir := t.TempDir()
	s, err := New(Config{
		DataDir: dir, TokenEnv: "TEST_HOST_TOKEN", ExtensionTokenEnv: "TEST_EXTENSION_TOKEN", InternalURL: "http://127.0.0.1:7070",
		Projects: map[string]string{"p": dir, "manual": t.TempDir()},
		Nodes:    map[string]NodeConfig{"n": {URL: nodeHTTP.URL, TokenEnv: "TEST_NODE_TOKEN"}},
		Bot: &BotConfig{Listen: listen, AllowedSourceIPs: allowed, Callers: map[string]BotCallerConfig{
			"grokbot": {TokenEnv: "TEST_BOT_TOKEN", Projects: map[string]BotProjectConfig{"manual": {AutoStart: boolPtr(false)}}},
			"other":   {TokenEnv: "TEST_OTHER_TOKEN"},
		}},
	})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(s.Close)
	return s
}

func botCall(t *testing.T, s *Server, token, method, path, remote string, payload any) *httptest.ResponseRecorder {
	t.Helper()
	var body io.Reader
	if payload != nil {
		b, _ := json.Marshal(payload)
		body = bytes.NewReader(b)
	}
	req := httptest.NewRequest(method, path, body)
	req.RemoteAddr = remote
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	if method == "GET" && strings.Contains(path, "/events") && !strings.Contains(path, "view=") {
		req.Header.Set("Accept", "application/json")
	}
	w := httptest.NewRecorder()
	s.BotHandler().ServeHTTP(w, req)
	return w
}

func TestBotAutoStartIsIdempotentAndDoesNotReplay(t *testing.T) {
	var posts atomic.Int32
	s := botServer(t, &posts, "127.0.0.1:7072", nil)
	token := strings.Repeat("b", 32)
	body := botCreateInput{RequestID: "bot-1", Title: "Fix the test", ProjectID: "p", NodeID: "n", Repository: "example/repository", Goal: "Make the test pass", Plan: "Edit the failing test and run it"}
	w := botCall(t, s, token, "POST", "/bot/v1/tasks", "127.0.0.1:9", body)
	if w.Code != 202 {
		t.Fatalf("create %d %s", w.Code, w.Body.String())
	}
	var created struct {
		Task    *core.Task    `json:"task"`
		Request *core.Request `json:"request"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &created); err != nil {
		t.Fatal(err)
	}
	if created.Task.Dispatch != "auto" || created.Task.Caller != "grokbot" || created.Task.Execution == nil || created.Request.Status != "completed" {
		t.Fatalf("admission %+v request %+v", created.Task, created.Request)
	}
	deadline := time.Now().Add(3 * time.Second)
	for posts.Load() == 0 && time.Now().Before(deadline) {
		time.Sleep(15 * time.Millisecond)
	}
	if posts.Load() != 1 {
		t.Fatalf("dispatch posts %d", posts.Load())
	}
	again := botCall(t, s, token, "POST", "/bot/v1/tasks", "127.0.0.1:9", body)
	if again.Code != 202 {
		t.Fatalf("retry %d %s", again.Code, again.Body.String())
	}
	time.Sleep(50 * time.Millisecond)
	if posts.Load() != 1 {
		t.Fatalf("uncertain retry dispatched again: %d", posts.Load())
	}
	if len(s.store.Snapshot().Tasks) != 1 {
		t.Fatal("retry created another task")
	}
	changed := body
	changed.Title = "Different"
	if w := botCall(t, s, token, "POST", "/bot/v1/tasks", "127.0.0.1:9", changed); w.Code != 409 {
		t.Fatalf("conflict %d %s", w.Code, w.Body.String())
	}
	dash := call(t, s, "POST", "/v1/tasks", createInput{RequestID: "human", Title: "Human task"})
	if dash.Code != 202 || strings.Contains(dash.Body.String(), `"dispatch":"auto"`) {
		t.Fatalf("dashboard create changed: %s", dash.Body.String())
	}
	listed := botCall(t, s, token, "GET", "/bot/v1/tasks", "127.0.0.1:9", nil)
	if listed.Code != 200 || strings.Count(listed.Body.String(), `"caller":"grokbot"`) != 1 || strings.Contains(listed.Body.String(), "Human task") {
		t.Fatalf("list leaked tasks: %s", listed.Body.String())
	}
	if w := botCall(t, s, strings.Repeat("o", 32), "GET", "/bot/v1/tasks/"+created.Task.ID, "127.0.0.1:9", nil); w.Code != 404 {
		t.Fatalf("other caller saw the task: %d", w.Code)
	}
	if w := botCall(t, s, token, "GET", "/bot/v1/tasks/"+created.Task.ID+"/events?view=snapshot", "127.0.0.1:9", nil); w.Code != 200 || !strings.Contains(w.Body.String(), "task.updated") {
		t.Fatalf("events %d %s", w.Code, w.Body.String())
	}
	if w := botCall(t, s, token, "POST", "/bot/v1/tasks/"+created.Task.ID+"/cancel", "127.0.0.1:9", map[string]any{"requestId": "cancel-1", "executionRequestId": "missing"}); w.Code != 409 {
		t.Fatalf("cancel %d %s", w.Code, w.Body.String())
	}
	req := httptest.NewRequest("GET", "/v1/tasks", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != 401 {
		t.Fatal("bot token was accepted on /v1")
	}
}

func TestBotManualProjectAndSourceGuard(t *testing.T) {
	var posts atomic.Int32
	s := botServer(t, &posts, "100.64.0.1:7072", []string{"100.64.0.8"})
	token := strings.Repeat("b", 32)
	if w := botCall(t, s, token, "POST", "/bot/v1/tasks", "127.0.0.1:9", botCreateInput{RequestID: "loop", Title: "No"}); w.Code != 403 || !strings.Contains(w.Body.String(), "source_denied") {
		t.Fatalf("loopback %d %s", w.Code, w.Body.String())
	}
	if w := botCall(t, s, "nope", "GET", "/bot/v1/targets", "100.64.0.8:9", nil); w.Code != 401 {
		t.Fatalf("auth %d", w.Code)
	}
	manual := botCreateInput{RequestID: "manual-1", Title: "Draft", ProjectID: "manual"}
	w := botCall(t, s, token, "POST", "/bot/v1/tasks", "100.64.0.8:9", manual)
	if w.Code != 202 || strings.Contains(w.Body.String(), `"execution"`) {
		t.Fatalf("manual start %d %s", w.Code, w.Body.String())
	}
	// Replaying a manual receipt must not require a plan after the policy flips.
	for i := range s.botCallers {
		if s.botCallers[i].ID == "grokbot" {
			s.botCallers[i].Policy.Projects["manual"] = BotProjectConfig{AutoStart: boolPtr(true)}
		}
	}
	replayed := botCall(t, s, token, "POST", "/bot/v1/tasks", "100.64.0.8:9", manual)
	if replayed.Code != 202 || replayed.Body.String() != w.Body.String() {
		t.Fatalf("manual receipt replay %d %s", replayed.Code, replayed.Body.String())
	}
	time.Sleep(40 * time.Millisecond)
	if posts.Load() != 0 {
		t.Fatal("manual policy dispatched")
	}
	projects := botCall(t, s, token, "GET", "/bot/v1/projects", "100.64.0.8:9", nil)
	if projects.Code != 200 || strings.Contains(projects.Body.String(), `\\`) || strings.Contains(projects.Body.String(), "/tmp") {
		t.Fatalf("projects leaked a path: %s", projects.Body.String())
	}
	if _, err := New(Config{DataDir: t.TempDir(), TokenEnv: "TEST_HOST_TOKEN", ExtensionTokenEnv: "TEST_EXTENSION_TOKEN", InternalURL: "http://127.0.0.1:7070", Projects: map[string]string{"p": t.TempDir()}, Nodes: map[string]NodeConfig{"n": {URL: "http://127.0.0.1:9", TokenEnv: "TEST_NODE_TOKEN"}}, Bot: &BotConfig{Listen: "100.64.0.1:1", Callers: map[string]BotCallerConfig{"grokbot": {TokenEnv: "TEST_BOT_TOKEN"}}}}); err == nil {
		t.Fatal("tailscale listen without an allowlist was accepted")
	}
}

func TestBotMCPUsesTheSameAdmission(t *testing.T) {
	var posts atomic.Int32
	s := botServer(t, &posts, "127.0.0.1:7072", nil)
	token := strings.Repeat("b", 32)
	init := botMCP(t, s, token, "", "127.0.0.1:9", `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"grok","version":"1"}}}`)
	if init.Code != 200 || init.Header().Get("Mcp-Session-Id") == "" {
		t.Fatalf("initialize %d %s", init.Code, init.Body.String())
	}
	session := init.Header().Get("Mcp-Session-Id")
	if w := botMCP(t, s, token, session, "127.0.0.1:9", `{"jsonrpc":"2.0","method":"notifications/initialized"}`); w.Code != 202 {
		t.Fatalf("initialized %d", w.Code)
	}
	listed := botMCP(t, s, token, session, "127.0.0.1:9", `{"jsonrpc":"2.0","id":2,"method":"tools/list"}`)
	if listed.Code != 200 || !strings.Contains(listed.Body.String(), "create_task") || strings.Contains(listed.Body.String(), "delete") {
		t.Fatalf("tools %s", listed.Body.String())
	}
	if w := botMCP(t, s, token, "", "192.0.2.10:9", `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}`); w.Code != 403 {
		t.Fatalf("mcp source %d", w.Code)
	}
	created := botMCP(t, s, token, session, "127.0.0.1:9", `{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"create_task","arguments":{"requestId":"mcp-1","title":"From MCP","projectId":"p","nodeId":"n","repository":"example/repository","plan":"Change the file"}}}`)
	if created.Code != 200 || strings.Contains(created.Body.String(), `"isError":true`) {
		t.Fatalf("mcp create %s", created.Body.String())
	}
	deadline := time.Now().Add(3 * time.Second)
	for posts.Load() == 0 && time.Now().Before(deadline) {
		time.Sleep(15 * time.Millisecond)
	}
	if posts.Load() != 1 {
		t.Fatalf("mcp dispatch %d", posts.Load())
	}
	ctx, cancel := context.WithCancel(context.Background())
	req := httptest.NewRequest("POST", "/mcp", strings.NewReader(`{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"stream_events","arguments":{"taskId":"`+taskIDFromRequest("mcp-1")+`","after":0}}}`))
	req = req.WithContext(ctx)
	req.RemoteAddr = "127.0.0.1:9"
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Mcp-Session-Id", session)
	req.Header.Set("Accept", "application/json, text/event-stream")
	rec := &stopAfterFlush{ResponseRecorder: httptest.NewRecorder(), cancel: cancel}
	s.BotHandler().ServeHTTP(rec, req)
	if rec.Code != 200 || !strings.Contains(rec.Body.String(), "notifications/awf/event") && !strings.Contains(rec.Body.String(), `"result"`) {
		t.Fatalf("stream %d %s", rec.Code, rec.Body.String())
	}
}

func TestMCPStreamDoesNotReplayInitialEvents(t *testing.T) {
	var posts atomic.Int32
	s := botServer(t, &posts, "127.0.0.1:7072", nil)
	token := strings.Repeat("b", 32)
	created := botCall(t, s, token, "POST", "/bot/v1/tasks", "127.0.0.1:9", botCreateInput{
		RequestID: "mcp-manual", Title: "Draft", ProjectID: "manual",
	})
	if created.Code != 202 {
		t.Fatalf("create %d %s", created.Code, created.Body.String())
	}
	init := botMCP(t, s, token, "", "127.0.0.1:9", `{"jsonrpc":"2.0","id":1,"method":"initialize"}`)
	session := init.Header().Get("Mcp-Session-Id")
	if init.Code != 200 || session == "" {
		t.Fatalf("initialize %d %s", init.Code, init.Body.String())
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	req := httptest.NewRequest("POST", "/mcp", strings.NewReader(`{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"stream_events","arguments":{"taskId":"`+taskIDFromRequest("mcp-manual")+`","after":0}}}`))
	req = req.WithContext(ctx)
	req.RemoteAddr = "127.0.0.1:9"
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Mcp-Session-Id", session)
	req.Header.Set("Accept", "text/event-stream")
	rec := &stopAfterSecondFlush{ResponseRecorder: httptest.NewRecorder(), cancel: cancel}
	s.BotHandler().ServeHTTP(rec, req)
	if rec.Code != 200 || !strings.Contains(rec.Body.String(), "task.updated") || strings.Contains(rec.Body.String(), "notifications/awf/event") {
		t.Fatalf("initial events were replayed: %d %s", rec.Code, rec.Body.String())
	}
}

type stopAfterSecondFlush struct {
	*httptest.ResponseRecorder
	cancel context.CancelFunc
	flushes int
}

func (s *stopAfterSecondFlush) Flush() {
	s.ResponseRecorder.Flush()
	s.flushes++
	if s.flushes == 2 {
		s.cancel()
	}
}

type stopAfterFlush struct {
	*httptest.ResponseRecorder
	cancel context.CancelFunc
	once   sync.Once
}

func (s *stopAfterFlush) Flush() {
	s.ResponseRecorder.Flush()
	s.once.Do(s.cancel)
}

func botMCP(t *testing.T, s *Server, token, session, remote, payload string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest("POST", "/mcp", strings.NewReader(payload))
	req.RemoteAddr = remote
	req.Header.Set("Authorization", "Bearer "+token)
	if session != "" {
		req.Header.Set("Mcp-Session-Id", session)
	}
	w := httptest.NewRecorder()
	s.BotHandler().ServeHTTP(w, req)
	return w
}
