package host

import (
	"bytes"
	"encoding/json"
	"github.com/atongrun/agent-workflow/internal/core"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func bridgeTask(t *testing.T, s *Server) *core.Task {
	task := draftTask(t, s, "bridge-task")
	if err := s.store.Update(func(st *core.State) error {
		v := st.Tasks[task.ID]
		v.RepositoryID = "123"
		v.Repository = "example/repository"
		v.ProjectID = "managed"
		v.NodeID = "n"
		v.TargetRevision = 1
		v.RepositorySource = &core.RepositorySource{BaseRef: "main", BaseSHA: strings.Repeat("a", 40), Files: map[string]string{}, Truncated: true}
		v.Plan = &core.Plan{Revision: 1, Content: "Inspect source then implement"}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	task, _ = s.task(task.ID)
	return task
}
func TestTruncatedConfirmationFailsClosedAndLeavesStateUntouched(t *testing.T) {
	t.Setenv("AWF_REPOSITORY_READ_URL", "")
	s := testServer(t)
	task := bridgeTask(t, s)
	before := len(s.store.Snapshot().Requests)
	w := call(t, s, "POST", "/v1/tasks/"+task.ID+"/plan/confirm", actionInput{RequestID: "incomplete-confirm", Revision: 1})
	if w.Code != 409 || !strings.Contains(w.Body.String(), "repository_source_incomplete") {
		t.Fatal(w.Body.String())
	}
	got, _ := s.task(task.ID)
	if got.Plan.ConfirmedAt != nil || got.Plan.Approved != nil || len(s.store.Snapshot().Requests) != before {
		t.Fatal("failed confirmation mutated task or admitted receipt")
	}
}
func TestBridgeReadConfirmationReplayAndScopeChecks(t *testing.T) {
	for _, mode := range []string{"success", "identity-mismatch", "target-change", "denied", "incomplete-tree", "missing-truncated", "string-truncated", "missing-entries", "stale-response-revision"} {
		t.Run(mode, func(t *testing.T) {
			s := testServer(t)
			task := bridgeTask(t, s)
			calls := 0
			reader := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls++
				if r.Header.Get("Authorization") != "Bearer "+s.token {
					t.Error("existing Host bearer missing")
				}
				var input map[string]any
				if json.NewDecoder(r.Body).Decode(&input) != nil || input["taskId"] != task.ID || input["targetRevision"] != float64(1) {
					t.Error("unbound read request")
				}
				if mode == "denied" {
					w.WriteHeader(403)
					return
				}
				result := map[string]any{"repositoryId": task.RepositoryID, "repository": task.Repository, "baseSha": task.RepositorySource.BaseSHA, "operation": input["operation"], "path": input["path"], "content": "file not in original bundle", "nextCursor": nil, "targetRevision": task.TargetRevision, "truncated": false, "entries": []map[string]any{}, "startLine": float64(1)}
				if mode == "missing-truncated" {
					delete(result, "truncated")
				}
				if mode == "string-truncated" {
					result["truncated"] = "false"
				}
				if mode == "missing-entries" {
					delete(result, "entries")
				}
				if mode == "stale-response-revision" {
					result["targetRevision"] = 999
				}
				if mode == "incomplete-tree" {
					result["truncated"] = true
				}
				if mode == "identity-mismatch" {
					result["baseSha"] = strings.Repeat("b", 40)
				}
				if mode == "target-change" {
					_ = s.store.Update(func(st *core.State) error { st.Tasks[task.ID].TargetRevision++; return nil })
				}
				writeJSON(w, 200, result)
			}))
			defer reader.Close()
			t.Setenv("AWF_REPOSITORY_READ_URL", reader.URL+"/api/awf/repository-read")
			input := actionInput{RequestID: "bridge-confirm", Revision: 1}
			w := call(t, s, "POST", "/v1/tasks/"+task.ID+"/plan/confirm", input)
			if mode != "success" {
				if w.Code != 409 {
					t.Fatalf("unsafe confirmation accepted: %d %s", w.Code, w.Body.String())
				}
				got, _ := s.task(task.ID)
				if got.Plan.ConfirmedAt != nil {
					t.Fatal("failed bridge confirmed plan")
				}
				return
			}
			if w.Code != 202 {
				t.Fatal(w.Body.String())
			}
			got, _ := s.task(task.ID)
			if got.Plan.Approved == nil || !got.Plan.Approved.RepositoryReadVerified || verifyApproval(got) != nil {
				t.Fatal("reader not included in approval")
			}
			if w := call(t, s, "POST", "/v1/tasks/"+task.ID+"/plan/confirm", input); w.Code != 202 || calls != 1 {
				t.Fatal("receipt retry repeated bridge preflight")
			}
			body, _ := json.Marshal(extensionInput{RequestID: "read-missing", Path: "src/deep.ts"})
			req := httptest.NewRequest("POST", "/internal/tasks/"+task.ID+"/repository", bytes.NewReader(body))
			req.Header.Set("Authorization", "Bearer "+s.scopedToken(task.ID, "architect"))
			req.Header.Set("X-AWF-Role", "architect")
			out := httptest.NewRecorder()
			s.Handler().ServeHTTP(out, req)
			if out.Code != 200 || !strings.Contains(out.Body.String(), "file not in original bundle") {
				t.Fatal(out.Body.String())
			}
		})
	}
}

func TestSourcePreflightCannotCrossDeleteRestoreLifecycle(t *testing.T) {
	task := &core.Task{TargetRevision: 2, LifecycleRevision: 4, RepositorySource: &core.RepositorySource{BaseSHA: strings.Repeat("a", 40), Truncated: true}}
	if !sourcePreflightMatches(task, task.RepositorySource.BaseSHA, 2, 4) {
		t.Fatal("current bound probe rejected")
	}
	// A completed delete/restore retains repo+SHA+target, but has a new lifecycle.
	task.LifecycleRevision += 2
	if sourcePreflightMatches(task, task.RepositorySource.BaseSHA, 2, 4) {
		t.Fatal("old lifecycle probe could confirm restored task")
	}
}
func TestBoundSourceRejectsSensitivePaths(t *testing.T) {
	for _, name := range []string{"secret.json", "credentials.json", "auth.json", ".env", ".ENV.json"} {
		source := &core.RepositorySource{BaseRef: "main", BaseSHA: strings.Repeat("a", 40), Files: map[string]string{name: "synthetic-value"}}
		if validateRepositorySource(source) == nil {
			t.Fatalf("sensitive source path accepted: %s", name)
		}
	}
}
