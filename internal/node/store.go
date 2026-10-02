package node

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

func (s *Server) persist(r *record) error {
	r.Job.UpdatedAt = time.Now().UTC()
	b, err := json.MarshalIndent(r, "", "  ")
	if err == nil {
		var f *os.File
		f, err = os.CreateTemp(s.jobsDir, ".job-*")
		if err == nil {
			name := f.Name()
			defer os.Remove(name)
			if err = f.Chmod(0600); err == nil {
				_, err = f.Write(b)
			}
			if err == nil {
				err = f.Sync()
			}
			closeErr := f.Close()
			if err == nil {
				err = closeErr
			}
			if err == nil {
				err = os.Rename(name, filepath.Join(s.jobsDir, r.Job.ID+".json"))
			}
			if err == nil {
				err = syncDirectory(s.jobsDir)
			}
		}
	}
	if err != nil {
		s.faultMu.Lock()
		s.storageError = fmt.Errorf("persist job: %w", err)
		s.faultMu.Unlock()
		r.Job.Status = "uncertain"
		r.Job.Error = "Node persistence failed; dispatch is paused until repaired and restarted"
	}
	return err
}
func (s *Server) load() error {
	files, err := filepath.Glob(filepath.Join(s.jobsDir, "*.json"))
	if err != nil {
		return err
	}
	for _, path := range files {
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		var r record
		if err = json.Unmarshal(data, &r); err != nil {
			return fmt.Errorf("invalid durable node job %s: %w", filepath.Base(path), err)
		}
		if err := r.Job.Model.Validate(); err != nil {
			return fmt.Errorf("durable job %s has invalid model selection: %w", r.Job.ID, err)
		}
		if r.Version != 1 || r.Job.ID == "" || filepath.Base(path) != r.Job.ID+".json" || r.Job.ID != JobID(r.Request.RequestID) || r.Fingerprint != fingerprint(r.Request) || r.Job.ProjectID != r.Request.ProjectID || r.Job.TaskID != r.Request.TaskID || r.Job.RequestID != r.Request.RequestID || !strings.HasPrefix(r.Job.MessageID, "msg_") {
			return fmt.Errorf("durable job %s has invalid identity", filepath.Base(path))
		}
		p, ok := s.projects[r.Job.ProjectID]
		if !ok || p.workspace != r.Job.Workspace {
			return fmt.Errorf("durable job %s requires its original configured workspace", r.Job.ID)
		}
		switch r.Job.Status {
		case "queued", "running", "uncertain", "cancelling", "completed", "failed", "cancelled":
		default:
			return fmt.Errorf("durable job %s has unknown status", r.Job.ID)
		}
		switch r.Job.SubmissionState {
		case "queued", "creating", "ready", "dispatching", "submitted":
		default:
			return fmt.Errorf("durable job %s has unknown submission state", r.Job.ID)
		}
		s.jobs[r.Job.ID] = &r
	}
	return nil
}
