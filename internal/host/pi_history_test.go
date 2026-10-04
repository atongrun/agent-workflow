package host

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/atongrun/agent-workflow/internal/core"
)

func nativeHistoryFixture(t *testing.T, s *Server, task *core.Task, content string) string {
	t.Helper()
	dir := filepath.Join(s.cfg.DataDir, "sessions", task.ID, "architect")
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "native.jsonl")
	if err := os.WriteFile(path, []byte(content), 0600); err != nil {
		t.Fatal(err)
	}
	if err := s.store.Update(func(st *core.State) error {
		r := st.Tasks[task.ID].Sessions["architect"]
		r.File = path
		r.Persisted = true
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestHistoryGETDoesNotActivateOrEvictCancelledTask(t *testing.T) {
	s, active, _, log, _ := piControlFixture(t, "")
	cancelled := createTask(t, s, "old-cancelled")
	if err := s.store.Update(func(st *core.State) error { st.Tasks[cancelled.ID].Status = "cancelled"; return nil }); err != nil {
		t.Fatal(err)
	}
	before := s.store.Snapshot()
	initialLog, _ := os.ReadFile(log)
	for i := 0; i < 5; i++ {
		w := call(t, s, "GET", "/v1/tasks/"+cancelled.ID+"/messages?role=architect", nil)
		if w.Code != 200 {
			t.Fatal(w.Code, w.Body.String())
		}
	}
	after := s.store.Snapshot()
	finalLog, _ := os.ReadFile(log)
	if !reflect.DeepEqual(before.Tasks, after.Tasks) || string(initialLog) != string(finalLog) {
		t.Fatal("history GET changed native generation, state or RPC log")
	}
	if !after.Tasks[active.ID].Sessions["architect"].Available {
		t.Fatal("cancelled history evicted active conversation")
	}
}

func TestOfflineNativeHistoryUsesOnlySelectedBranchAndNeverWrites(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "offline-tree")
	content := string(mustJSON(map[string]any{"type": "session", "version": 3, "id": task.Sessions["architect"].ID})) + "\n" +
		`{"type":"message","id":"root","parentId":null,"message":{"role":"user","content":[{"type":"text","text":"goal"}]}}` + "\n" +
		`{"type":"message","id":"abandoned","parentId":"root","message":{"role":"assistant","content":[{"type":"text","text":"old branch"}]}}` + "\n" +
		`{"type":"message","id":"selected","parentId":"root","message":{"role":"assistant","content":[{"type":"text","text":"current branch"}]}}` + "\n"
	path := nativeHistoryFixture(t, s, task, content)
	before := s.store.Snapshot()
	w := call(t, s, "GET", "/v1/tasks/"+task.ID+"/messages?role=architect", nil)
	if w.Code != 200 {
		t.Fatal(w.Code, w.Body.String())
	}
	var out struct {
		Messages []json.RawMessage `json:"messages"`
		Source   string            `json:"historySource"`
		Status   string            `json:"historyStatus"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &out); err != nil {
		t.Fatal(err)
	}
	if out.Source != "persisted" || out.Status != "complete" || len(out.Messages) != 2 {
		t.Fatal(w.Body.String())
	}
	data, _ := os.ReadFile(path)
	if string(data) != content || !reflect.DeepEqual(before.Tasks, s.store.Snapshot().Tasks) {
		t.Fatal("read mutated native or Host state")
	}
}

func TestReportingVerdictSessionCannotBeEvictedForAnotherTask(t *testing.T) {
	s, task, _, _, _ := piControlFixture(t, "")
	if err := s.store.Update(func(st *core.State) error {
		x := st.Tasks[task.ID]
		x.Status = "reporting"
		x.Execution = &core.Execution{Status: "completed", RequestID: "finished", ResultReview: &core.ResultReview{Status: "awaiting_verdict"}}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	other := createTask(t, s, "other-explicit")
	if _, err := s.client(other.ID, "architect"); err == nil {
		t.Fatal("another task evicted pending verdict session")
	}
	got, _ := s.task(task.ID)
	if !got.Sessions["architect"].Available {
		t.Fatal("awaiting-verdict process lost")
	}
}

func TestPersistedHistoryProtocolBoundsAndSafeErrors(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "history-protocol")
	header := string(mustJSON(map[string]any{"type": "session", "version": 3, "id": task.Sessions["architect"].ID})) + "\n"
	root := `{"type":"message","id":"root","parentId":null,"message":{"role":"user","content":[]}}` + "\n"
	rows := []struct {
		name, data, status, source string
		count                      int
	}{
		{"header-only", header, "complete", "persisted", 0},
		{"v2", strings.Replace(header, `"version":3`, `"version":2`, 1) + root, "complete", "persisted", 1},
		{"v1", strings.Replace(header, `"version":3`, `"version":1`, 1), "unavailable", "none", 0},
		{"wrong-session", strings.Replace(header, task.Sessions["architect"].ID, "foreign", 1) + root, "unavailable", "none", 0},
		{"partial-tail", header + root + `{"private":"hidden-secret`, "incomplete", "persisted", 1},
		{"corrupt-record", header + root + "hidden-secret\n", "incomplete", "persisted", 1},
		{"foreign-parent", header + root + `{"type":"message","id":"other","parentId":"missing","message":{"role":"assistant"}}` + "\n", "incomplete", "persisted", 1},
		{"duplicate", header + root + root, "incomplete", "persisted", 1},
		{"primitive-message", header + `{"type":"message","id":"bad","parentId":null,"message":"hidden-secret"}` + "\n", "incomplete", "persisted", 0},
		{"custom-and-branch-summary", header + root + `{"type":"custom_message","id":"custom","parentId":"root","customType":"note","content":"native custom content","display":true}` + "\n" + `{"type":"branch_summary","id":"summary","parentId":"custom","fromId":"root","summary":"branch context"}` + "\n", "complete", "persisted", 1},
		{"compaction", header + root + `{"type":"compaction","id":"compact","parentId":"root","summary":"native summary","firstKeptEntryId":"root"}` + "\n" + `{"type":"message","id":"after","parentId":"compact","message":{"role":"assistant","content":[]}}` + "\n", "complete", "persisted", 2},
	}
	for _, row := range rows {
		t.Run(row.name, func(t *testing.T) {
			path := nativeHistoryFixture(t, s, task, row.data)
			w := call(t, s, "GET", "/v1/tasks/"+task.ID+"/messages?role=architect", nil)
			var out historyResponse
			if w.Code != 200 || json.Unmarshal(w.Body.Bytes(), &out) != nil || out.Status != row.status || out.Source != row.source || len(out.Messages) != row.count {
				t.Fatal(w.Code, w.Body.String())
			}
			if strings.Contains(out.Error, "hidden-secret") || strings.Contains(out.Error, s.cfg.DataDir) || strings.Contains(out.Error, path) {
				t.Fatal("history error leaked input/path")
			}
			after, _ := os.ReadFile(path)
			if string(after) != row.data {
				t.Fatal("history parser wrote native file")
			}
		})
	}
}

func TestPersistedHistoryRejectsForeignSymlinkAndOversizedFile(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "history-security")
	header := string(mustJSON(map[string]any{"type": "session", "version": 3, "id": task.Sessions["architect"].ID})) + "\n"
	managed := nativeHistoryFixture(t, s, task, header)
	foreign := filepath.Join(t.TempDir(), "private-secret.jsonl")
	if err := os.WriteFile(foreign, []byte(header), 0600); err != nil {
		t.Fatal(err)
	}
	for _, kind := range []string{"foreign", "symlink", "oversize"} {
		t.Run(kind, func(t *testing.T) {
			path := managed
			switch kind {
			case "foreign":
				path = foreign
			case "symlink":
				path = filepath.Join(filepath.Dir(managed), "linked.jsonl")
				if err := os.Symlink(foreign, path); err != nil {
					t.Skip(err)
				}
			case "oversize":
				f, err := os.OpenFile(managed, os.O_WRONLY, 0600)
				if err != nil {
					t.Fatal(err)
				}
				if err = f.Truncate(maxNativeHistoryBytes + 1); err != nil {
					t.Fatal(err)
				}
				f.Close()
			}
			if err := s.store.Update(func(st *core.State) error { st.Tasks[task.ID].Sessions["architect"].File = path; return nil }); err != nil {
				t.Fatal(err)
			}
			w := call(t, s, "GET", "/v1/tasks/"+task.ID+"/messages", nil)
			var out historyResponse
			if w.Code != 200 || json.Unmarshal(w.Body.Bytes(), &out) != nil || out.Status != "unavailable" || len(out.Messages) != 0 || strings.Contains(out.Error, "private-secret") {
				t.Fatal(w.Body.String())
			}
		})
	}
}

func TestHistoryGETAlternatesCancelledAndReportingWithoutProcessThrash(t *testing.T) {
	s, reporting, _, log, _ := piControlFixture(t, "")
	cancelled := createTask(t, s, "cancelled-history")
	if err := s.store.Update(func(st *core.State) error {
		st.Tasks[reporting.ID].Status = "reporting"
		st.Tasks[cancelled.ID].Status = "cancelled"
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	before := s.store.Snapshot().Tasks
	for i := 0; i < 10; i++ {
		for _, id := range []string{cancelled.ID, reporting.ID} {
			w := call(t, s, "GET", "/v1/tasks/"+id+"/messages?role=architect", nil)
			if w.Code != 200 {
				t.Fatal(w.Code, w.Body.String())
			}
		}
	}
	after := s.store.Snapshot().Tasks
	if !reflect.DeepEqual(before, after) || methodCount(t, log, "abort") != 0 || methodCount(t, log, "prompt") != 0 {
		t.Fatal("history pressure changed generation or lifecycle")
	}
	if methodCount(t, log, "get_messages") != 10 {
		t.Fatal("offline GET contacted native process")
	}
}

func TestHistoryGETRejectsUnsupportedQueryWithoutStateChange(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "history-query")
	before := s.store.Snapshot()
	for _, q := range []string{"?activate=true", "?role=architect&role=reviewer", "?role=architect&unknown=true"} {
		if w := call(t, s, "GET", "/v1/tasks/"+task.ID+"/messages"+q, nil); w.Code != 400 {
			t.Fatal(q, w.Code)
		}
	}
	if !reflect.DeepEqual(before.Tasks, s.store.Snapshot().Tasks) || len(s.clients) != 0 {
		t.Fatal("invalid GET changed state")
	}
}
