package core

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestStoreRollbackAndRecovery(t *testing.T) {
	dir := t.TempDir()
	s, err := Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	if err = s.Update(func(st *State) error { st.Tasks["keep"] = &Task{ID: "keep", Title: "old"}; return nil }); err != nil {
		t.Fatal(err)
	}
	sentinel := errors.New("reject")
	err = s.Update(func(st *State) error {
		delete(st.Tasks, "keep")
		st.Tasks["new"] = &Task{ID: "new"}
		st.Requests["new"] = &Request{ID: "new"}
		return sentinel
	})
	if !errors.Is(err, sentinel) {
		t.Fatal(err)
	}
	got := s.Snapshot()
	if got.Tasks["keep"] == nil || got.Tasks["new"] != nil || got.Requests["new"] != nil {
		t.Fatalf("rollback failed: %+v", got)
	}
	if _, err = Open(dir); err == nil {
		t.Fatal("second writer accepted")
	}
	_ = s.Close()
	s, err = Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	if s.Snapshot().Tasks["keep"] == nil {
		t.Fatal("durable task lost")
	}
}
func TestStorePersistenceFailureFailsClosed(t *testing.T) {
	s, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	s.path = filepath.Join(t.TempDir(), "missing", "state.json")
	err = s.Update(func(st *State) error { st.Tasks["new"] = &Task{ID: "new"}; return nil })
	if err == nil {
		t.Fatal("expected write failure")
	}
	if s.Snapshot().Tasks["new"] != nil {
		t.Fatal("unpersisted mutation visible")
	}
	if err = s.Update(func(st *State) error { return nil }); err == nil {
		t.Fatal("writes continued after uncertain persistence")
	}
}
func TestStatePermissions(t *testing.T) {
	dir := t.TempDir()
	s, err := Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	info, err := os.Stat(filepath.Join(dir, "state.json"))
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm()&0077 != 0 {
		t.Fatalf("state too broadly readable: %v", info.Mode())
	}
}
func TestEventProjectionBoundedAndPlanBudgetShared(t *testing.T) {
	s, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	chunk := make([]byte, 8192)
	for i := range chunk {
		chunk[i] = 'a'
	}
	for range 1000 {
		s.Event("task", "pi.event", string(chunk))
	}
	st := s.Snapshot()
	bytes := 0
	for _, e := range st.Events {
		bytes += len(e.Data) + 128
	}
	if bytes > 4*1024*1024 {
		t.Fatalf("event projection grew to %d", bytes)
	}
	err = s.Update(func(st *State) error {
		st.Tasks["a"] = &Task{ID: "a", PlanID: "plan", Budget: Budget{TaskSeconds: 80}}
		st.Tasks["b"] = &Task{ID: "b", PlanID: "plan", Budget: Budget{TaskSeconds: 120}}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	st = s.Snapshot()
	if st.Tasks["a"].Budget.PlanSeconds != 200 || st.Tasks["b"].Budget.PlanSeconds != 200 {
		t.Fatal("plan budget reset across tasks")
	}
}

func TestOptionalPlanningAndTargetFieldsPreserveLegacyState(t *testing.T) {
	// A version-1 fixture intentionally predates planningProfile/targetRevision.
	raw := `{"version":1,"settings":{},"tasks":{"legacy":{"id":"legacy","planId":"plan","title":"Existing task","repository":"legacy repository metadata","branch":"work/existing","sessions":{"architect":{"id":"native-id","file":"native-history.jsonl","persisted":true}},"execution":{"requestId":"old-job","jobId":"durable-job","sessionId":"native-executor","status":"completed"},"executionHistory":[{"requestId":"previous","status":"completed"}],"budget":{"taskSeconds":17,"planSeconds":17,"reworks":1}}},"requests":{"original":{"id":"original","taskId":"legacy","operation":"create","hash":"keep-exact-hash","status":"completed"}},"events":[],"sequence":0}`
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "state.json"), []byte(raw), 0600); err != nil {
		t.Fatal(err)
	}
	var before State
	if err := json.Unmarshal([]byte(raw), &before); err != nil {
		t.Fatal(err)
	}
	s, err := Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	legacy := s.Snapshot().Tasks["legacy"]
	if legacy.PlanningProfile != "" || legacy.TargetRevision != 0 || legacy.Execution.Target != nil {
		t.Fatal("legacy authority/identity was inferred")
	}
	if err := s.Update(func(st *State) error {
		st.Tasks["draft"] = &Task{ID: "draft", PlanID: "new-plan", PlanningProfile: RestrictedPlanning, TargetRevision: 1, RepositoryID: "123", Sessions: map[string]*Session{"architect": {ID: "new-native"}}}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	s.Close()
	s, err = Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	after := s.Snapshot()
	if !reflect.DeepEqual(before.Tasks["legacy"], after.Tasks["legacy"]) || !reflect.DeepEqual(before.Requests["original"], after.Requests["original"]) {
		t.Fatal("saving new fields rewrote old sessions, execution, budgets, or request hashes")
	}
	if after.Version != 1 || after.Tasks["draft"].PlanningProfile != RestrictedPlanning || after.Tasks["draft"].RepositoryID != "123" {
		t.Fatal("new profile/identity fields did not persist")
	}
}
