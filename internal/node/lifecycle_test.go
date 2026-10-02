package node

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func offlineFixture(t *testing.T) (Config, *record, string) {
	t.Helper()
	root := t.TempDir()
	workspace := filepath.Join(root, "workspace")
	if err := os.MkdirAll(workspace, 0700); err != nil {
		t.Fatal(err)
	}
	workspace, err := filepath.EvalSymlinks(workspace)
	if err != nil {
		t.Fatal(err)
	}
	state := filepath.Join(root, "state")
	if err = os.MkdirAll(filepath.Join(state, "jobs"), 0700); err != nil {
		t.Fatal(err)
	}
	cfg := Config{StateDir: state, Projects: map[string]string{"project": workspace}}
	req := JobRequest{RequestID: "offline-fixture", TaskID: "task", ProjectID: "project", Repository: "fixture", Branch: "main", Prompt: "inert fixture"}
	r := &record{Version: 1, Request: req, Fingerprint: fingerprint(req), Job: Job{ID: JobID(req.RequestID), RequestID: req.RequestID, TaskID: req.TaskID, ProjectID: req.ProjectID, Workspace: workspace, MessageID: "msg_fixture", Status: "completed", SubmissionState: "submitted"}}
	return cfg, r, filepath.Join(state, "jobs", r.Job.ID+".json")
}
func writeOfflineFixture(t *testing.T, path string, r *record) []byte {
	t.Helper()
	b, err := json.Marshal(r)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(path, b, 0600); err != nil {
		t.Fatal(err)
	}
	return b
}
func assertOfflineBlocked(t *testing.T, cfg Config) {
	t.Helper()
	lock, err := OfflineIdle(cfg)
	if lock != nil {
		lock.Close()
		t.Error("blocked state returned a held lock")
	}
	if err == nil {
		t.Fatal("busy or unknown durable job state accepted")
	}
	// Failure must release ownership so an explicit recovery can proceed later.
	recovery, err := lockState(filepath.Join(cfg.StateDir, "node.lock"))
	if err != nil {
		t.Fatalf("failed inspection leaked ownership lock: %v", err)
	}
	recovery.Close()
}

func TestOfflineIdleBlocksNonterminalAndUnknownJobState(t *testing.T) {
	for _, status := range []string{"queued", "running", "uncertain", "cancelling", "", "unknown", "Completed"} {
		t.Run(status, func(t *testing.T) {
			cfg, r, path := offlineFixture(t)
			r.Job.Status = status
			before := writeOfflineFixture(t, path, r)
			assertOfflineBlocked(t, cfg)
			after, err := os.ReadFile(path)
			if err != nil || !bytes.Equal(before, after) {
				t.Fatalf("inspection rewrote job: %v", err)
			}
		})
	}
}

func TestOfflineIdleAcceptsTerminalJobsAndHoldsOwnership(t *testing.T) {
	for _, status := range []string{"completed", "failed", "cancelled", "empty"} {
		t.Run(status, func(t *testing.T) {
			cfg, r, path := offlineFixture(t)
			if status != "empty" {
				r.Job.Status = status
				writeOfflineFixture(t, path, r)
			}
			lock, err := OfflineIdle(cfg)
			if err != nil {
				t.Fatal(err)
			}
			defer lock.Close()
			other, err := lockState(filepath.Join(cfg.StateDir, "node.lock"))
			if err == nil {
				other.Close()
				t.Fatal("offline gate did not hold the native node writer lock")
			}
			if err = lock.Close(); err != nil {
				t.Fatal(err)
			}
			released, err := lockState(filepath.Join(cfg.StateDir, "node.lock"))
			if err != nil {
				t.Fatalf("ownership lock not released: %v", err)
			}
			released.Close()
		})
	}
}

func TestOfflineIdleRejectsInvalidDurableIdentity(t *testing.T) {
	cases := []struct {
		name   string
		mutate func(*record)
	}{
		{"unknown schema", func(r *record) { r.Version = 2 }},
		{"missing identity", func(r *record) { r.Job.ID = "" }},
		{"request identity mismatch", func(r *record) { r.Job.RequestID = "different" }},
		{"fingerprint mismatch", func(r *record) { r.Fingerprint = "different" }},
		{"foreign project", func(r *record) {
			r.Job.ProjectID = "other"
			r.Request.ProjectID = "other"
			r.Fingerprint = fingerprint(r.Request)
		}},
		{"foreign workspace", func(r *record) { r.Job.Workspace = filepath.Dir(r.Job.Workspace) }},
		{"task mismatch", func(r *record) { r.Job.TaskID = "other" }},
		{"invalid message identity", func(r *record) { r.Job.MessageID = "other" }},
		{"unknown submission state", func(r *record) { r.Job.SubmissionState = "unknown" }},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			cfg, r, path := offlineFixture(t)
			tc.mutate(r)
			writeOfflineFixture(t, path, r)
			assertOfflineBlocked(t, cfg)
		})
	}
}

func TestOfflineIdleRejectsMissingCorruptOrUnexpectedStorage(t *testing.T) {
	for _, kind := range []string{"missing jobs", "jobs regular file", "corrupt record", "trailing JSON", "unrecognized file", "nested directory", "wrong filename", "symlink record"} {
		t.Run(kind, func(t *testing.T) {
			cfg, r, path := offlineFixture(t)
			jobs := filepath.Dir(path)
			switch kind {
			case "missing jobs":
				if err := os.Remove(jobs); err != nil {
					t.Fatal(err)
				}
			case "jobs regular file":
				if err := os.Remove(jobs); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(jobs, []byte("not a directory"), 0600); err != nil {
					t.Fatal(err)
				}
			case "corrupt record":
				if err := os.WriteFile(path, []byte("{"), 0600); err != nil {
					t.Fatal(err)
				}
			case "trailing JSON":
				b := writeOfflineFixture(t, path, r)
				if err := os.WriteFile(path, append(b, []byte("{}")...), 0600); err != nil {
					t.Fatal(err)
				}
			case "unrecognized file":
				if err := os.WriteFile(filepath.Join(jobs, "orphan.tmp"), []byte("unknown"), 0600); err != nil {
					t.Fatal(err)
				}
			case "nested directory":
				if err := os.Mkdir(filepath.Join(jobs, "nested"), 0700); err != nil {
					t.Fatal(err)
				}
			case "wrong filename":
				writeOfflineFixture(t, filepath.Join(jobs, "other.json"), r)
			case "symlink record":
				target := filepath.Join(cfg.StateDir, "external-record.json")
				writeOfflineFixture(t, target, r)
				if err := os.Symlink(target, path); err != nil {
					t.Skipf("OS does not permit test symlink: %v", err)
				}
			}
			assertOfflineBlocked(t, cfg)
		})
	}
}

func TestOfflineIdleRejectsActiveStateOwner(t *testing.T) {
	cfg, _, _ := offlineFixture(t)
	owner, err := lockState(filepath.Join(cfg.StateDir, "node.lock"))
	if err != nil {
		t.Fatal(err)
	}
	defer owner.Close()
	lock, err := OfflineIdle(cfg)
	if lock != nil {
		lock.Close()
	}
	if err == nil {
		t.Fatal("offline switch allowed while node owns state")
	}
}

func TestIdleBlocksStorageFaultAndEveryNonterminalState(t *testing.T) {
	for _, status := range []string{"queued", "running", "uncertain", "cancelling", "unknown"} {
		s := &Server{projects: map[string]*project{"project": {}}, jobs: map[string]*record{"job": {Job: Job{ID: "job", Status: status}}}}
		if err := s.Idle(); err == nil {
			t.Errorf("live idle accepted %s job", status)
		}
	}
	s := &Server{storageError: errors.New("synthetic persistence fault")}
	if err := s.Idle(); err == nil {
		t.Fatal("idle accepted unhealthy storage")
	}
}

func TestIdleRefusesConcurrentReconciliationWithoutWaiting(t *testing.T) {
	first, busy := &project{id: "a"}, &project{id: "b"}
	s := &Server{projects: map[string]*project{"a": first, "b": busy}, jobs: map[string]*record{}}
	busy.mu.Lock()
	done := make(chan error, 1)
	go func() { done <- s.Idle() }()
	select {
	case err := <-done:
		busy.mu.Unlock()
		if err == nil || !strings.Contains(err.Error(), "project b is busy") {
			t.Fatalf("concurrent reconciliation not refused: %v", err)
		}
	case <-time.After(time.Second):
		busy.mu.Unlock()
		<-done
		t.Fatal("idle waited on active reconciliation instead of refusing promptly")
	}
	if !first.mu.TryLock() {
		t.Fatal("idle leaked an earlier project lock on busy refusal")
	}
	first.mu.Unlock()
	if err := s.Idle(); err != nil {
		t.Fatalf("idle stayed blocked after reconciliation released ownership: %v", err)
	}
}

func TestOfflineIdleRejectsOversizedRecordWithoutReadingIt(t *testing.T) {
	cfg, _, path := offlineFixture(t)
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	// Sparse file fixture; avoid allocating or reading a huge JSON payload.
	if err = f.Truncate((128 << 20) + 1); err != nil {
		f.Close()
		t.Fatal(err)
	}
	if err = f.Close(); err != nil {
		t.Fatal(err)
	}
	assertOfflineBlocked(t, cfg)
}
