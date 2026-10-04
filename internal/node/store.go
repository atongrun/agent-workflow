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

		switch r.Job.QuestionCleanupState {
		case "", "cleared", "needs_verification":
		default:
			return fmt.Errorf("durable job %s has unknown cleanup state", r.Job.ID)
		}
		if (r.Job.QuestionCleanupState != "" || len(r.Job.QuestionCleanup) > 0) && !cleanupAuthority(&r) {
			return fmt.Errorf("durable job %s has unauthorized cleanup state", r.Job.ID)
		}
		if r.Job.QuestionCleanupState == "cleared" && len(r.Job.PendingQuestions) > 0 {
			return fmt.Errorf("durable job %s has inconsistent cleanup state", r.Job.ID)
		}

		if len(r.Job.QuestionCleanup) > 0 && r.Job.QuestionCleanupState == "" {
			return fmt.Errorf("durable job %s has missing cleanup state", r.Job.ID)
		}
		if len(r.Job.QuestionCleanup) > 128 {
			return fmt.Errorf("durable job %s exceeds cleanup receipt limit", r.Job.ID)
		}
		for id, receipt := range r.Job.QuestionCleanup {
			if id != receiptQuestionID(receipt) || !cleanupAuthority(&r) || !cleanupBinding(&r, receipt) {
				return fmt.Errorf("durable job %s has invalid cleanup receipt", r.Job.ID)
			}
			if r.Job.QuestionCleanupState == "cleared" && receipt.Status != "cleared" {
				return fmt.Errorf("durable job %s has inconsistent cleanup receipt", r.Job.ID)
			}
			switch receipt.Status {
			case "cleared", "needs_verification":
			case "dispatching":
				receipt.Status = "needs_verification"
				receipt.Acknowledged = false
				receipt.Error = "node restarted during question rejection; never resend"
			default:
				return fmt.Errorf("durable job %s has unknown cleanup receipt state", r.Job.ID)
			}
		}
		if len(r.QuestionReplies) > 128 {
			return fmt.Errorf("durable job %s exceeds question receipt limit", r.Job.ID)
		}
		for key, receipt := range r.QuestionReplies {
			if !validQuestionReceipt(receipt) || key != receipt.Reply.RequestID || !questionRequestPattern.MatchString(key) || receipt.Hash == "" || receipt.Reply.JobID != r.Job.ID || receipt.Reply.TaskID != r.Job.TaskID || receipt.Reply.ExecutionRequestID != r.Job.RequestID || receipt.Reply.SessionID != r.Job.SessionID {
				return fmt.Errorf("durable job %s has invalid question receipt", r.Job.ID)
			}
			switch receipt.Reply.Status {
			case "completed", "needs_verification":
			case "failed":
				if receipt.Reply.HTTPStatus != 400 && receipt.Reply.HTTPStatus != 409 {
					return fmt.Errorf("durable job %s has invalid question failure receipt", r.Job.ID)
				}
			case "dispatching":
				receipt.Reply.Status = "needs_verification"
				receipt.Reply.Error = "node restarted during native reply; do not resend"
			default:
				return fmt.Errorf("durable job %s has unknown question receipt state", r.Job.ID)
			}
		}
		s.jobs[r.Job.ID] = &r
	}
	return nil
}

func receiptQuestionID(r *QuestionCleanup) string {
	if r == nil {
		return ""
	}
	return r.QuestionID
}
