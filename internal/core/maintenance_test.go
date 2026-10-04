package core

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestMaintenancePersistedValidationAndSealedNormalization(t *testing.T) {
	dir := t.TempDir()
	s, err := Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC()
	if err := s.Update(func(st *State) error {
		st.Maintenance = &Maintenance{Revision: 1, Phase: "sealed", OwnerRequestID: "lease", TargetManifestSHA256: strings.Repeat("a", 64), BeganAt: &now}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	if err := s.Update(func(st *State) error { st.Maintenance = nil; return nil }); err == nil {
		t.Fatal("lease reset admitted")
	}
	if err := s.Update(func(st *State) error { st.Maintenance.Phase = "draining"; return nil }); err == nil {
		t.Fatal("sealed downgrade admitted")
	}
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	data, _ := os.ReadFile(filepath.Join(dir, "state.json"))
	var state State
	if json.Unmarshal(data, &state) != nil {
		t.Fatal("state unreadable")
	}
	// A compatible historical/noncanonical aggregate must not be repaired by
	// an otherwise read-only retry while sealed.
	state.Tasks["legacy"] = &Task{ID: "legacy", Budget: Budget{TaskSeconds: 3, PlanSeconds: 99}}
	data, _ = json.Marshal(state)
	if os.WriteFile(filepath.Join(dir, "state.json"), data, 0600) != nil {
		t.Fatal("fixture write")
	}
	s, err = Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	if err = s.Update(func(*State) error { return nil }); err == nil {
		t.Fatal("sealed aggregate normalization admitted")
	}
	if s.Snapshot().Tasks["legacy"].Budget.PlanSeconds != 99 {
		t.Fatal("failed update changed counters")
	}
	s.Close()
	state.Maintenance.Phase = "future"
	data, _ = json.Marshal(state)
	os.WriteFile(filepath.Join(dir, "state.json"), data, 0600)
	if reopened, err := Open(dir); err == nil {
		reopened.Close()
		t.Fatal("unknown lease phase admitted")
	}
}
