package workbuddy

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestClientRejectsNonLoopbackAndUnsafeModes(t *testing.T) {
	if _, err := New(Config{URL: "http://100.64.0.1:8321", Password: "password1"}); err == nil {
		t.Fatal("accepted a tailnet WorkBuddy URL")
	}
	if _, err := New(Config{URL: "http://127.0.0.1:8321", Password: "short"}); err == nil {
		t.Fatal("accepted a short password")
	}
	if _, err := New(Config{URL: "http://127.0.0.1:8321", Password: "password1", PermissionMode: "bypassPermissions"}); err == nil {
		t.Fatal("accepted bypassPermissions")
	}
}

func TestClientDispatchReplyAndStop(t *testing.T) {
	var saw map[string]any
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-CodeBuddy-Request") != "1" || r.Header.Get("Authorization") != "Bearer password1" {
			http.Error(w, "auth", 401)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		switch {
		case r.Method == "GET" && r.URL.Path == "/api/v1/health":
			_, _ = io.WriteString(w, `{"data":{"status":"ok","version":"2.137.0"}}`)
		case r.Method == "POST" && r.URL.Path == "/api/v1/jobs":
			if err := json.NewDecoder(r.Body).Decode(&saw); err != nil {
				t.Error(err)
			}
			_, _ = io.WriteString(w, `{"data":{"id":"job_1","name":"wbabc","cwd":"/work","state":"working","status":"busy"}}`)
		case r.Method == "POST" && r.URL.Path == "/api/v1/jobs/job_1/reply":
			body, _ := io.ReadAll(r.Body)
			if !strings.Contains(string(body), `"text":"use the tests"`) {
				t.Errorf("reply body %s", body)
			}
			_, _ = io.WriteString(w, `{"data":{"ok":true}}`)
		case r.Method == "POST" && r.URL.Path == "/api/v1/jobs/job_1/stop":
			_, _ = io.WriteString(w, `{"data":{"stopped":true}}`)
		case r.Method == "GET" && r.URL.Path == "/api/v1/jobs":
			_, _ = io.WriteString(w, `{"data":{"jobs":[{"id":"job_1","name":"wbabc","cwd":"/work","state":"blocked","status":"waiting","question":"Which file?"}]}}`)
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()
	client, err := New(Config{URL: srv.URL, Password: "password1", HTTPClient: srv.Client()})
	if err != nil {
		t.Fatal(err)
	}
	ok, version, err := client.Health(context.Background())
	if err != nil || !ok || version != "2.137.0" {
		t.Fatalf("health %v %s %v", ok, version, err)
	}
	job, err := client.Dispatch(context.Background(), Dispatch{Prompt: "fix the test", CWD: "/work", Name: "wbabc"})
	if err != nil {
		t.Fatal(err)
	}
	if job.ID != "job_1" || saw["bgIsolation"] != "worktree" || saw["permissionMode"] != "acceptEdits" || saw["bash"] != nil {
		t.Fatalf("dispatch %#v body %#v", job, saw)
	}
	if err := client.Reply(context.Background(), job.ID, "use the tests"); err != nil {
		t.Fatal(err)
	}
	if err := client.Stop(context.Background(), job.ID); err != nil {
		t.Fatal(err)
	}
	jobs, err := client.List(context.Background(), "/work")
	if err != nil || len(jobs) != 1 || jobs[0].Question != "Which file?" {
		t.Fatalf("list %#v %v", jobs, err)
	}
}
