package node

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestWorkBuddyExecutorCompletesWithoutReplay(t *testing.T) {
	workspace, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	var mu sync.Mutex
	var posts atomic.Int32
	state := "working"
	sessionName := ""
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-CodeBuddy-Request") != "1" || r.Header.Get("Authorization") != "Bearer password1" {
			http.Error(w, `{"error":{"code":"AUTH_REQUIRED","message":"Authentication required"}}`, 401)
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
		status := "busy"
		if state == "done" {
			status = "idle"
		}
		payload, _ := json.Marshal(map[string]string{"id": "job_1", "name": sessionName, "cwd": workspace, "state": state, "status": status, "summary": "edited README"})
		switch {
		case r.Method == "GET" && r.URL.Path == "/api/v1/health":
			_, _ = io.WriteString(w, `{"data":{"status":"ok","version":"test"}}`)
		case r.Method == "POST" && r.URL.Path == "/api/v1/jobs":
			var body map[string]string
			if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
				t.Errorf("body: %v", err)
			}
			if body["bgIsolation"] != "worktree" || body["cwd"] != workspace || body["permissionMode"] != "acceptEdits" {
				t.Errorf("dispatch %#v", body)
			}
			posts.Add(1)
			sessionName = body["name"]
			payload, _ = json.Marshal(map[string]string{"id": "job_1", "name": sessionName, "cwd": workspace, "state": state, "status": status, "summary": "edited README"})
			_, _ = w.Write([]byte(`{"data":` + string(payload) + `}`))
		case r.Method == "GET" && r.URL.Path == "/api/v1/jobs":
			if sessionName == "" {
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
	cfg := Config{Token: "test-bearer-32-characters-long-key", StateDir: t.TempDir(), Projects: map[string]string{"example": workspace}, Executor: "workbuddy", WorkBuddyURL: srv.URL, WorkBuddyPassword: "password1", HTTPClient: srv.Client(), PollInterval: 15 * time.Millisecond}
	s := startNode(t, cfg)
	code, job := call(t, s, "POST", "/v1/jobs", req("wb-one"))
	if code != 202 {
		t.Fatalf("submit %d", code)
	}
	job = waitJob(t, s, job.ID, func(j Job) bool {
		return j.NativeStatus == "busy" || j.Status == "failed" || j.Status == "uncertain" || j.Status == "completed"
	})
	if job.Status == "failed" || job.Status == "uncertain" {
		t.Fatalf("dispatch did not run: %s", job.Error)
	}
	mu.Lock()
	state = "done"
	mu.Unlock()
	job = waitJob(t, s, job.ID, func(j Job) bool {
		return j.Status == "completed" || j.Status == "failed" || j.Status == "uncertain"
	})
	if job.Status != "completed" || job.Summary == "" {
		t.Fatalf("completion %+v", job)
	}
	if code, again := call(t, s, "POST", "/v1/jobs", req("wb-one")); code != 200 || again.ID != job.ID {
		t.Fatalf("replay %d %+v", code, again)
	}
	if posts.Load() != 1 {
		t.Fatalf("daemon dispatch count %d", posts.Load())
	}
	w := httptest.NewRecorder()
	r := httptest.NewRequest("GET", "/v1/health", nil)
	r.RemoteAddr = "127.0.0.1:9"
	r.Header.Set("Authorization", "Bearer test-bearer-32-characters-long-key")
	s.ServeHTTP(w, r)
	if w.Code != 200 || !strings.Contains(w.Body.String(), `"executor":"workbuddy"`) {
		t.Fatalf("health %d %s", w.Code, w.Body.String())
	}
}
