package node

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
)

// Idle reports whether all durable AWF jobs have known terminal outcomes.
// Callers must close admission before relying on this to stop a runtime.
func (s *Server) Idle() error {
	if s.fault() != nil {
		return errors.New("node storage is unhealthy; job state is unknown")
	}
	ids := make([]string, 0, len(s.projects))
	for id := range s.projects {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	for _, id := range ids {
		if !s.projects[id].mu.TryLock() {
			return fmt.Errorf("project %s is busy reconciling native work; retry stop/update after it becomes idle", id)
		}
		defer s.projects[id].mu.Unlock()
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, r := range s.jobs {
		if len(r.Job.PendingQuestions) > 0 || r.Job.QuestionCleanupState != "" && r.Job.QuestionCleanupState != "cleared" {
			return fmt.Errorf("job %s cancellation question state is unresolved", r.Job.ID)
		}
		for _, receipt := range r.Job.QuestionCleanup {
			if receipt == nil || receipt.Status != "cleared" {
				return fmt.Errorf("job %s question cleanup is unresolved", r.Job.ID)
			}
		}
		if !terminal(r.Job.Status) {
			return fmt.Errorf("job %s is %s; wait for or resolve it before stopping/updating", r.Job.ID, r.Job.Status)
		}
	}
	return nil
}

// OfflineIdle holds the same native node writer lock during inspection. Missing,
// corrupt, foreign-workspace, busy, and unknown records all block an upgrade.
// The returned release must stay open until the offline switch is finished.
func OfflineIdle(cfg Config) (*os.File, error) {
	st, e := os.Stat(filepath.Join(cfg.StateDir, "jobs"))
	if e != nil || !st.IsDir() {
		return nil, errors.New("node job storage is missing or unreadable; update state is unknown")
	}
	lock, e := lockState(filepath.Join(cfg.StateDir, "node.lock"))
	if e != nil {
		return nil, e
	}
	s := &Server{cfg: cfg, jobsDir: filepath.Join(cfg.StateDir, "jobs"), jobs: map[string]*record{}, projects: map[string]*project{}}
	fail := func(e error) (*os.File, error) { lock.Close(); return nil, e }
	for id, p := range cfg.Projects {
		clean, e := filepath.EvalSymlinks(filepath.Clean(p))
		if e != nil {
			return fail(e)
		}
		s.projects[id] = &project{id: id, workspace: clean}
	}
	entries, e := os.ReadDir(s.jobsDir)
	if e != nil {
		return fail(e)
	}
	for _, entry := range entries {
		info, err := entry.Info()
		if err != nil || !info.Mode().IsRegular() || info.Size() > 128<<20 {
			return fail(errors.New("durable job is not a bounded regular file; update state is unknown"))
		}
		if entry.IsDir() || entry.Type()&os.ModeSymlink != 0 || filepath.Ext(entry.Name()) != ".json" {
			return fail(errors.New("unexpected entry in durable job storage; update state is unknown"))
		}
	}
	if e = s.load(); e != nil {
		return fail(e)
	}
	if e = s.Idle(); e != nil {
		return fail(e)
	}
	return lock, nil
}
