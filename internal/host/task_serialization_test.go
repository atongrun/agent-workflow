package host

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"github.com/atongrun/agent-workflow/internal/core"
)

func TestReportingTaskWireRevisionCanBindResume(t *testing.T) {
	for _, revision := range []int{0, 2} {
		t.Run(fmt.Sprint(revision), func(t *testing.T) {
			s := testServer(t)
			task := createTask(t, s, "wire-lifecycle")
			if err := s.store.Update(func(st *core.State) error {
				current := st.Tasks[task.ID]
				current.Status = "reporting"
				current.LifecycleRevision = revision
				current.Sessions["architect"].ProcessID = "previous-native-process"
				return nil
			}); err != nil {
				t.Fatal(err)
			}
			w := call(t, s, "GET", "/v1/tasks/"+task.ID, nil)
			var out struct {
				Task struct {
					LifecycleRevision *int                     `json:"lifecycleRevision"`
					Sessions          map[string]*core.Session `json:"sessions"`
				} `json:"task"`
			}
			if w.Code != 200 || json.Unmarshal(w.Body.Bytes(), &out) != nil {
				t.Fatal(w.Code, w.Body.String())
			}
			if out.Task.LifecycleRevision == nil || *out.Task.LifecycleRevision != revision {
				t.Fatalf("Host omitted or changed authoritative lifecycle revision: %s", w.Body.String())
			}
			history := call(t, s, "GET", "/v1/tasks/"+task.ID+"/messages?role=architect", nil)
			var conversation historyResponse
			if history.Code != 200 || json.Unmarshal(history.Body.Bytes(), &conversation) != nil || conversation.Session.ID != out.Task.Sessions["architect"].ID || conversation.Session.ProcessID != out.Task.Sessions["architect"].ProcessID {
				t.Fatal(history.Code, history.Body.String())
			}
			// Bind from the wire Task, without inferring a missing revision.
			in := map[string]any{"requestId": "wire-resume", "role": "architect", "expectedLifecycleRevision": *out.Task.LifecycleRevision, "expectedSessionId": conversation.Session.ID, "expectedProcessId": conversation.Session.ProcessID}
			resume := call(t, s, "POST", "/v1/tasks/"+task.ID+"/pi/resume", in)
			if resume.Code != 202 {
				t.Fatal(resume.Code, resume.Body.String())
			}
			// No catalog is provisioned, so no native startup is attempted.
			req := awaitPiRequest(t, s, "wire-resume", "failed")
			if req.Dispatched || len(s.clients) != 0 {
				t.Fatal("wire fixture attempted native startup")
			}

		})
	}
}

func TestTaskListSerializesZeroAndNonzeroLifecycle(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "wire-list")
	for _, revision := range []int{0, 2} {
		if err := s.store.Update(func(st *core.State) error { st.Tasks[task.ID].LifecycleRevision = revision; return nil }); err != nil {
			t.Fatal(err)
		}
		w := call(t, s, "GET", "/v1/tasks", nil)
		var out struct {
			Tasks []struct {
				LifecycleRevision *int `json:"lifecycleRevision"`
			} `json:"tasks"`
		}
		if w.Code != 200 || json.Unmarshal(w.Body.Bytes(), &out) != nil || len(out.Tasks) != 1 || out.Tasks[0].LifecycleRevision == nil || *out.Tasks[0].LifecycleRevision != revision {
			t.Fatal(revision, w.Code, w.Body.String())
		}
	}
}

func TestLegacyPersistedTaskWithoutLifecycleReadsExplicitZero(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "legacy-lifecycle-file")
	if err := s.store.Update(func(st *core.State) error {
		current := st.Tasks[task.ID]
		current.Status = "blocked"
		current.Budget.TaskSeconds = 37
		current.Budget.Reworks = 1
		current.Sessions["architect"].ProcessID = "retained-original-process"
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	before := s.store.Snapshot()
	// Construct an old-format file exclusively in the isolated local fixture.
	var legacy map[string]json.RawMessage
	if err := json.Unmarshal(mustJSON(before), &legacy); err != nil {
		t.Fatal(err)
	}
	var tasks map[string]map[string]json.RawMessage
	if err := json.Unmarshal(legacy["tasks"], &tasks); err != nil {
		t.Fatal(err)
	}
	delete(tasks[task.ID], "lifecycleRevision")
	legacy["tasks"] = mustJSON(tasks)
	oldFile := mustJSON(legacy)
	s.Close()
	statePath := filepath.Join(s.cfg.DataDir, "state.json")
	if err := os.WriteFile(statePath, oldFile, 0600); err != nil {
		t.Fatal(err)
	}
	reopened, err := New(s.cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	w := call(t, reopened, "GET", "/v1/tasks/"+task.ID, nil)
	var wire struct {
		Task struct {
			LifecycleRevision *int `json:"lifecycleRevision"`
		} `json:"task"`
	}
	if w.Code != 200 || json.Unmarshal(w.Body.Bytes(), &wire) != nil || wire.Task.LifecycleRevision == nil || *wire.Task.LifecycleRevision != 0 {
		t.Fatal(w.Code, w.Body.String())
	}
	var typed struct {
		Task *core.Task `json:"task"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &typed); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(typed.Task, before.Tasks[task.ID]) || !reflect.DeepEqual(reopened.store.Snapshot().Requests, before.Requests) {
		t.Fatal("legacy loading changed task semantics or receipts")
	}
	after, err := os.ReadFile(statePath)
	if err != nil || !reflect.DeepEqual([]byte(oldFile), after) {
		t.Fatal("read compatibility rewrote legacy persisted state", err)
	}
	if len(reopened.clients) != 0 {
		t.Fatal("legacy reading started Pi")
	}
}
