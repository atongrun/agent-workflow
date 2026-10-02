package core

import (
	"errors"
	"os"
	"path/filepath"
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
