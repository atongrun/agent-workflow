package workbuddy

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"

	"github.com/atongrun/agent-workflow/internal/opencode"
)

func TestPromptIsNotRetriedAndQuestionBinds(t *testing.T) {
	workspace := t.TempDir()
	var mu sync.Mutex
	posts := 0
	state := "working"
	jobName := ""
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-CodeBuddy-Request") != "1" {
			http.Error(w, "header", 403)
			return
		}
		if r.URL.Path == "/api/v1/jobs/events" {
			w.Header().Set("Content-Type", "text/event-stream")
			_, _ = io.WriteString(w, "data: {\"type\":\"snapshot\"}\n\n")
			return
		}
		mu.Lock()
		defer mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		payload, _ := json.Marshal(map[string]any{"id": "job_1", "name": jobName, "cwd": workspace, "state": state, "status": "waiting", "question": "Continue?"})
		switch {
		case r.Method == "POST" && r.URL.Path == "/api/v1/jobs":
			var body map[string]string
			if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
				t.Errorf("decode: %v", err)
			}
			posts++
			jobName = body["name"]
			state = "blocked"
			payload, _ = json.Marshal(map[string]any{"id": "job_1", "name": jobName, "cwd": workspace, "state": state, "status": "waiting", "question": "Continue?"})
			_, _ = w.Write([]byte(`{"data":` + string(payload) + `}`))
		case r.Method == "GET" && r.URL.Path == "/api/v1/jobs":
			if jobName == "" {
				_, _ = io.WriteString(w, `{"data":[]}`)
				return
			}
			_, _ = w.Write([]byte(`{"data":[` + string(payload) + `]}`))
		case r.Method == "GET" && r.URL.Path == "/api/v1/jobs/job_1":
			_, _ = w.Write([]byte(`{"data":` + string(payload) + `}`))
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()
	driver, err := Open(OpenConfig{URL: srv.URL, Password: "password1", StateDir: t.TempDir(), HTTPClient: srv.Client()})
	if err != nil {
		t.Fatal(err)
	}
	session, err := driver.CreateSession(context.Background(), workspace, "AWF job")
	if err != nil {
		t.Fatal(err)
	}
	if err := driver.PromptAsync(context.Background(), workspace, session.ID, "msg_1", "do the work"); err != nil {
		t.Fatal(err)
	}
	if err := driver.PromptAsync(context.Background(), workspace, session.ID, "msg_1", "do the work"); err == nil {
		t.Fatal("retried a dispatched prompt")
	}
	mu.Lock()
	if posts != 1 {
		t.Fatalf("posts = %d", posts)
	}
	mu.Unlock()
	raw, err := driver.PendingQuestions(context.Background(), workspace)
	if err != nil || len(raw) != 1 {
		t.Fatalf("questions %s %v", raw, err)
	}
	var q opencode.Question
	if err := json.Unmarshal(raw[0], &q); err != nil || q.Tool == nil || q.Tool.MessageID == "" || q.SessionID != session.ID {
		t.Fatalf("question %#v %v", q, err)
	}
	messages, err := driver.Messages(context.Background(), workspace, session.ID)
	if err != nil || len(messages) != 2 || messages[1].Info.ParentID != "msg_1" {
		t.Fatalf("messages %#v %v", messages, err)
	}
	found := false
	for _, part := range messages[1].Parts {
		if part.Tool == "question" && part.CallID == q.Tool.CallID && part.State.Status == "running" {
			found = true
		}
	}
	if !found {
		t.Fatal("question tool is not bound to the assistant turn")
	}
	stream, err := driver.OpenEvents(context.Background(), workspace)
	if err != nil {
		t.Fatal(err)
	}
	stream.Close()
}
