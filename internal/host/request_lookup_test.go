package host

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"testing"

	"github.com/atongrun/agent-workflow/internal/core"
)

func TestExactRequestLookupPreservesLedgerWithoutCurrentDependencies(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "lookup-task")
	revision := 0
	in := targetInput{RequestID: "original-target", ExpectedTargetRevision: &revision, Repository: "example/repo", RepositoryID: "123", ProjectID: "p", NodeID: "n"}
	if w := call(t, s, "PATCH", "/v1/tasks/"+task.ID+"/target", in); w.Code != 202 {
		t.Fatalf("bind: %d %s", w.Code, w.Body.String())
	}
	// A receipt survives removed config, disconnected nodes and no Pi process.
	s.cfg.Projects = nil
	s.cfg.Nodes = nil
	before := s.store.Snapshot()
	path := "/v1/tasks/" + task.ID + "/requests/" + in.RequestID
	w := call(t, s, "POST", path, map[string]any{"requestId": in.RequestID, "operation": "target", "payload": in})
	if w.Code != 200 {
		t.Fatalf("lookup: %d %s", w.Code, w.Body.String())
	}
	var got struct {
		Request core.Request `json:"request"`
		Task    core.Task    `json:"task"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &got); err != nil {
		t.Fatal(err)
	}
	if got.Request.ID != in.RequestID || got.Request.Operation != "target" || got.Request.Status != "completed" || got.Task.ID != task.ID {
		t.Fatal("lookup did not return the exact durable receipt")
	}
	if !reflect.DeepEqual(before, s.store.Snapshot()) || len(s.clients) != 0 {
		t.Fatal("read-only reconciliation changed durable or native state")
	}
	changed := in
	changed.Repository = "example/other"
	if w = call(t, s, "POST", path, map[string]any{"requestId": in.RequestID, "operation": "target", "payload": changed}); w.Code != 409 {
		t.Fatalf("changed payload: %d", w.Code)
	}
}

func TestExactRequestLookupRetainsLegacyActionHashAndUncertainStatus(t *testing.T) {
	for _, op := range []string{"start", "rework"} {
		t.Run(op, func(t *testing.T) {
			s := testServer(t)
			task := createTask(t, s, "lookup-"+op)
			original := actionInput{RequestID: "original-" + op, Role: "architect", Revision: 3}
			if op == "rework" {
				original.ExecutionRequestID = "earlier-run"
			}
			_, err := s.reserve(original.RequestID, task.ID, op, original, func(*core.State) error { return nil })
			if err != nil {
				t.Fatal(err)
			}
			s.requestDone(original.RequestID, "needs_verification", nil)
			payload := map[string]any{"requestId": original.RequestID, "revision": 3}
			if op == "rework" {
				payload["executionRequestId"] = "earlier-run"
			}
			before := s.store.Snapshot()
			w := call(t, s, "POST", "/v1/tasks/"+task.ID+"/requests/"+original.RequestID, map[string]any{"requestId": original.RequestID, "operation": op, "payload": payload})
			if w.Code != 200 || !strings.Contains(w.Body.String(), `"status":"needs_verification"`) {
				t.Fatalf("legacy hash/default role: %d %s", w.Code, w.Body.String())
			}
			if !reflect.DeepEqual(before, s.store.Snapshot()) {
				t.Fatal("lookup modified an uncertain operation")
			}
		})
	}
}

func TestExactRequestLookupRejectsCrossTaskInvalidIDsAndUnknownFields(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "lookup-validation")
	other := createTask(t, s, "lookup-other")
	original := actionInput{RequestID: "original-start", Role: "architect", Revision: 1}
	_, _ = s.reserve(original.RequestID, task.ID, "start", original, func(*core.State) error { return nil })
	path := "/v1/tasks/" + task.ID + "/requests/" + original.RequestID
	base := map[string]any{"requestId": original.RequestID, "operation": "start", "payload": map[string]any{"requestId": original.RequestID, "revision": 1}}
	before := s.store.Snapshot()
	for name, sample := range map[string]struct {
		path   string
		body   any
		status int
	}{
		"cross task":    {"/v1/tasks/" + other.ID + "/requests/" + original.RequestID, base, 404},
		"missing":       {"/v1/tasks/" + task.ID + "/requests/missing", map[string]any{"requestId": "missing", "operation": "start", "payload": map[string]any{"requestId": "missing", "revision": 1}}, 404},
		"path id":       {path, map[string]any{"requestId": "other", "operation": "start", "payload": original}, 400},
		"payload id":    {path, map[string]any{"requestId": original.RequestID, "operation": "start", "payload": map[string]any{"requestId": "other", "revision": 1}}, 400},
		"operation":     {path, map[string]any{"requestId": original.RequestID, "operation": "bash", "payload": original}, 400},
		"mismatch":      {path, map[string]any{"requestId": original.RequestID, "operation": "rework", "payload": original}, 409},
		"unknown field": {path, map[string]any{"requestId": original.RequestID, "operation": "start", "payload": map[string]any{"requestId": original.RequestID, "revision": 1, "url": "https://evil.invalid"}}, 400},
		"null":          {path, map[string]any{"requestId": original.RequestID, "operation": "start", "payload": nil}, 400},
		"query":         {path + "?role=architect", base, 400},
	} {
		t.Run(name, func(t *testing.T) {
			if w := call(t, s, "POST", sample.path, sample.body); w.Code != sample.status {
				t.Fatalf("got %d, expected %d: %s", w.Code, sample.status, w.Body.String())
			}
		})
	}
	if !reflect.DeepEqual(before, s.store.Snapshot()) {
		t.Fatal("failed lookup reserved or changed a request")
	}
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, httptest.NewRequest(http.MethodPost, path, strings.NewReader(`{}`)))
	if w.Code != http.StatusUnauthorized {
		t.Fatal("lookup bypassed Host authentication")
	}
}
