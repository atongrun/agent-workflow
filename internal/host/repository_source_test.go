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

func TestApprovedSourceFreezesExecutionAndRejectsDrift(t *testing.T) {
	task := &core.Task{ID: "task", RepositoryID: "123", Repository: "example/repository", NodeID: "n", ProjectID: "managed", Branch: "awf/task", TargetRevision: 2, RepositorySource: &core.RepositorySource{BaseRef: "main", BaseSHA: strings.Repeat("a", 40), Files: map[string]string{"README.md": "baseline"}}, Plan: &core.Plan{Revision: 3, Content: "Implement approved plan"}}
	a, err := approveInput(task)
	if err != nil {
		t.Fatal(err)
	}
	task.Plan.Approved = a
	if err := verifyApproval(task); err != nil {
		t.Fatal(err)
	}
	task.Execution = &core.Execution{Approved: a, RequestID: "run", TimeoutSeconds: 60, Target: &core.ExecutionTarget{ProjectID: task.ProjectID, Repository: task.Repository}}
	original := (&Server{}).jobRequest(task)
	task.Plan.Content = "unapproved change"
	task.Repository = "example/other"
	frozen := (&Server{}).jobRequest(task)
	if original.Plan != frozen.Plan || original.Repository != frozen.Repository || frozen.WorkspaceInput.BaseSHA != a.BaseSHA {
		t.Fatal("dispatch read mutable input")
	}
	if verifyApproval(task) == nil {
		t.Fatal("changed plan/target approval accepted")
	}
}
func TestRepositoryToolReadsOnlyBoundSourceAndNoMutation(t *testing.T) {
	s := testServer(t)
	task := draftTask(t, s, "source-tool")
	source := &core.RepositorySource{BaseRef: "main", BaseSHA: strings.Repeat("a", 40), Files: map[string]string{"README.md": "untrusted repository text"}}
	if err := s.store.Update(func(st *core.State) error { st.Tasks[task.ID].RepositorySource = source; return nil }); err != nil {
		t.Fatal(err)
	}
	read := func(name, role string, lifecycle int) *httptest.ResponseRecorder {
		body, _ := json.Marshal(extensionInput{RequestID: "source-read", Path: name, LifecycleRevision: lifecycle})
		r := httptest.NewRequest("POST", "/internal/tasks/"+task.ID+"/repository", bytes.NewReader(body))
		r.Header.Set("Authorization", "Bearer "+s.scopedToken(task.ID, role))
		r.Header.Set("X-AWF-Role", role)
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, r)
		return w
	}
	if w := read("README.md", "architect", 0); w.Code != http.StatusOK || !strings.Contains(w.Body.String(), "untrusted repository text") {
		t.Fatal(w.Body.String())
	}
	if w := read("../private", "architect", 0); w.Code != 404 {
		t.Fatalf("missing file %d", w.Code)
	}
	if w := read("README.md", "reviewer", 0); w.Code != 409 {
		t.Fatal("wrong role read accepted")
	}
	if w := read("README.md", "architect", 1); w.Code != 409 {
		t.Fatal("stale lifecycle read accepted")
	}
	if len(s.store.Snapshot().Requests) != 1 {
		t.Fatal("read tool created new mutation receipts")
	}
}
func TestManagedCatalogNeedsNoHostCheckout(t *testing.T) {
	s := testServer(t)
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]any{"available": true, "reachable": true, "projects": []map[string]any{{"projectId": "managed", "ready": true, "managed": true}}})
	}))
	defer remote.Close()
	s.cfg.Nodes["n"] = NodeConfig{URL: remote.URL, TokenEnv: "TEST_NODE_TOKEN"}
	found, status := s.targetCatalog(t.Context(), "n")
	if status != "online" || len(found) != 1 || !found[0].Ready || !found[0].Managed {
		t.Fatalf("catalog %+v %s", found, status)
	}
	task := draftTask(t, s, "managed-bind")
	input := targetInput{RequestID: "managed-target", ExpectedTargetRevision: ptr(0), Repository: "example/repository", RepositoryID: "123", ProjectID: "managed", NodeID: "n", RepositorySource: &core.RepositorySource{BaseRef: "main", BaseSHA: strings.Repeat("a", 40), Files: map[string]string{"README.md": "source"}}}
	if w := call(t, s, "PATCH", "/v1/tasks/"+task.ID+"/target", input); w.Code != 202 {
		t.Fatal(w.Body.String())
	}
	planFixture(t, s, task.ID, false)
	if w := call(t, s, "POST", "/v1/tasks/"+task.ID+"/plan/confirm", actionInput{RequestID: "managed-confirm", Revision: 1}); w.Code != 202 {
		t.Fatal(w.Body.String())
	}
	got, _ := s.task(task.ID)
	if got.Plan.Approved == nil || got.Plan.Approved.BaseSHA != input.RepositorySource.BaseSHA {
		t.Fatal("confirmation did not freeze baseline")
	}
}
