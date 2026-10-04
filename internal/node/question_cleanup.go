package node

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"time"

	"github.com/atongrun/agent-workflow/internal/opencode"
)

// Cleared records an observed absence, independently of whether the native
// reject acknowledgement was received. A dispatch fence is never replayed.
type QuestionCleanup struct {
	QuestionID         string    `json:"questionId"`
	TaskID             string    `json:"taskId"`
	JobID              string    `json:"jobId"`
	ExecutionRequestID string    `json:"executionRequestId"`
	SessionID          string    `json:"sessionId"`
	MessageID          string    `json:"messageId"`
	CallID             string    `json:"callId"`
	PartID             string    `json:"partId"`
	CancelRequestID    string    `json:"cancelRequestId"`
	Status             string    `json:"status"`
	Acknowledged       bool      `json:"acknowledged"`
	Error              string    `json:"error,omitempty"`
	CreatedAt          time.Time `json:"createdAt"`
}

var errQuestionCleanup = errors.New("cancelled question cleanup requires original turn verification; retry original cancellation, never answer the cancelled turn")

func cleanupAuthority(r *record) bool {
	return r.Job.CancelRequested && r.Job.AbortConfirmed && r.CancelPhase == "confirmed" && strings.TrimSpace(r.CancelRequestID) != "" && len(r.CancelRequestID) <= 256 && (r.Job.SubmissionState == "dispatching" || r.Job.SubmissionState == "submitted")
}
func cleanupAuthorized(r *record) bool {
	return cleanupAuthority(r) && (r.Job.Status == "cancelled" || r.Job.Status == "cancelling" || r.Job.Status == "uncertain")
}
func cleanupBinding(r *record, c *QuestionCleanup) bool {
	return c != nil && opencode.ValidQuestionID(c.QuestionID) && c.TaskID == r.Job.TaskID && c.JobID == r.Job.ID && c.ExecutionRequestID == r.Job.RequestID && c.SessionID == r.Job.SessionID && c.CancelRequestID == r.CancelRequestID && c.MessageID != "" && c.CallID != "" && c.PartID != "" && !c.CreatedAt.IsZero()
}
func questionToolPart(q opencode.Question, messages []opencode.Message, r *record) *opencode.Part {
	if !opencode.ValidQuestionID(q.ID) || q.SessionID != r.Job.SessionID || q.Tool == nil || q.Tool.MessageID == "" || q.Tool.CallID == "" {
		return nil
	}
	var found *opencode.Part
	for _, m := range messages {
		if m.Info.Role != "assistant" || m.Info.SessionID != r.Job.SessionID || m.Info.ParentID != r.Job.MessageID || m.Info.ID != q.Tool.MessageID {
			continue
		}
		for _, part := range m.Parts {
			if part.Type != "tool" || part.ID == "" || part.SessionID != r.Job.SessionID || part.MessageID != m.Info.ID || part.Tool != "question" || part.CallID != q.Tool.CallID {
				continue
			}
			switch part.State.Status {
			case "pending", "running", "completed", "error":
			default:
				return nil
			}
			if found != nil {
				return nil
			}
			copy := part
			found = &copy
		}
	}
	return found
}

// Native ownership is rechecked before each rejection; project locking alone
// cannot fence someone using a separate native interface.
func (s *Server) cleanupTurn(ctx context.Context, p *project, r *record) ([]opencode.Message, error) {
	session, err := s.native.Session(ctx, p.workspace, r.Job.SessionID)
	if err != nil || session.ID != r.Job.SessionID || !sameWorkspace(session.Directory, p.workspace) {
		return nil, errQuestionCleanup
	}
	statuses, err := s.native.Statuses(ctx, p.workspace)
	if err != nil || statuses == nil {
		return nil, errQuestionCleanup
	}
	// OpenCode v1.18.34 status.set deletes idle entries. Missing is idle only
	// after a successful non-null map read and a separately verified Session.
	if status, ok := statuses[r.Job.SessionID]; ok && status.Type != "idle" {
		return nil, errQuestionCleanup
	}
	messages, err := s.native.Messages(ctx, p.workspace, r.Job.SessionID)
	if err != nil {
		return nil, errQuestionCleanup
	}
	// The original user turn must be uniquely present and have no later user turn.
	var user *opencode.MessageInfo
	for _, m := range messages {
		if m.Info.Role == "user" && m.Info.SessionID == r.Job.SessionID && m.Info.ID == r.Job.MessageID {
			if user != nil {
				return nil, errQuestionCleanup
			}
			copy := m.Info
			user = &copy
		}
	}
	if user == nil || user.Time.Created <= 0 {
		return nil, errQuestionCleanup
	}
	for _, m := range messages {
		if m.Info.Role == "user" && m.Info.SessionID == r.Job.SessionID && m.Info.ID != r.Job.MessageID && (m.Info.Time.Created <= 0 || m.Info.Time.Created >= user.Time.Created) {
			return nil, errQuestionCleanup
		}
	}
	return messages, nil
}

// Caller holds project mutex. No terminal histories are scanned automatically;
// only the explicitly cancelled original job can acquire rejection authority.
func (s *Server) cleanupCancelledQuestions(ctx context.Context, p *project, r *record) error {
	if !cleanupAuthorized(r) {
		return nil
	}
	if s.fault() != nil {
		return errQuestionCleanup
	}
	// Persist the verification gate even if native binding cannot yet be read.
	if r.Job.QuestionCleanupState != "needs_verification" {
		r.Job.QuestionCleanupState = "needs_verification"
		if s.persist(r) != nil {
			return errQuestionCleanup
		}
	}
	s.mu.Lock()
	reused := false
	for _, other := range s.jobs {
		if other != r && other.Job.ProjectID == p.id && other.Job.SessionID == r.Job.SessionID && !other.Job.CreatedAt.Before(r.Job.CreatedAt) {
			reused = true
		}
	}
	s.mu.Unlock()
	if reused {
		return errQuestionCleanup
	}
	messages, err := s.cleanupTurn(ctx, p, r)
	if err != nil {
		return err
	}
	raw, err := s.native.PendingQuestions(ctx, p.workspace)
	if err != nil || raw == nil {
		return errQuestionCleanup
	}
	questions := map[string]opencode.Question{}
	parts := map[string]*opencode.Part{}
	for _, v := range raw {
		var q opencode.Question
		if json.Unmarshal(v, &q) != nil || q.ID == "" || q.SessionID == "" {
			return errQuestionCleanup
		}
		if q.SessionID != r.Job.SessionID {
			continue
		}
		part := questionToolPart(q, messages, r)
		if part == nil {
			return errQuestionCleanup
		}
		if _, exists := questions[q.ID]; exists {
			return errQuestionCleanup
		}
		questions[q.ID] = q
		parts[q.ID] = part
	}
	total := len(r.Job.QuestionCleanup)
	for id := range questions {
		if r.Job.QuestionCleanup[id] == nil {
			total++
		}
	}
	if total > 128 {
		return errQuestionCleanup
	}
	if r.Job.QuestionCleanup == nil {
		r.Job.QuestionCleanup = map[string]*QuestionCleanup{}
	}
	for id, q := range questions {
		if previous := r.Job.QuestionCleanup[id]; previous != nil {
			if !cleanupBinding(r, previous) || previous.MessageID != q.Tool.MessageID || previous.CallID != q.Tool.CallID || previous.PartID != parts[id].ID {
				return errQuestionCleanup
			}
			// Even a previously cleared ID must not acquire another dispatch fence.
			previous.Status = "needs_verification"
			previous.Error = "native question is still pending; reject will not be resent"
			continue
		}
		fresh, err := s.cleanupTurn(ctx, p, r)
		if err != nil || questionToolPart(q, fresh, r) == nil {
			return errQuestionCleanup
		}
		// Question IDs are native immutable identities. Recheck the actual
		// request binding immediately before creating its dispatch fence.
		current, err := s.native.PendingQuestions(ctx, p.workspace)
		if err != nil || current == nil {
			return errQuestionCleanup
		}
		matches := 0
		for _, v := range current {
			var live opencode.Question
			if json.Unmarshal(v, &live) != nil || live.ID == "" || live.SessionID == "" {
				return errQuestionCleanup
			}
			if live.ID == id {
				part := questionToolPart(live, fresh, r)
				if part == nil || part.ID != parts[id].ID || live.Tool.MessageID != q.Tool.MessageID || live.Tool.CallID != q.Tool.CallID {
					return errQuestionCleanup
				}
				matches++
			}
		}
		if matches != 1 {
			return errQuestionCleanup
		}
		receipt := &QuestionCleanup{QuestionID: id, TaskID: r.Job.TaskID, JobID: r.Job.ID, ExecutionRequestID: r.Job.RequestID, SessionID: r.Job.SessionID, MessageID: q.Tool.MessageID, CallID: q.Tool.CallID, PartID: parts[id].ID, CancelRequestID: r.CancelRequestID, Status: "dispatching", CreatedAt: time.Now().UTC()}
		r.Job.QuestionCleanup[id] = receipt
		if s.persist(r) != nil {
			receipt.Status = "needs_verification"
			return errQuestionCleanup
		}
		err = s.native.RejectQuestion(ctx, p.workspace, id)
		receipt.Status = "needs_verification"
		receipt.Acknowledged = err == nil
		if err != nil {
			receipt.Error = "native reject acknowledgement is unknown; never resend"
		}
		if s.persist(r) != nil {
			receipt.Acknowledged = false
			receipt.Error = "native reject outcome was not durably recorded"
			return errQuestionCleanup
		}
	}
	// A fresh authoritative list resolves the wait, never invents an ACK or resets
	// execution/cancellation state. Unrelated native sessions are not mutated.
	current, err := s.native.PendingQuestions(ctx, p.workspace)
	if err != nil || current == nil {
		return errQuestionCleanup
	}
	pending := map[string]bool{}
	for _, v := range current {
		var q opencode.Question
		if json.Unmarshal(v, &q) != nil || q.ID == "" || q.SessionID == "" {
			return errQuestionCleanup
		}
		pending[q.ID] = true
	}
	// Recheck turn ownership after reject before projecting cleared state.
	if _, err := s.cleanupTurn(ctx, p, r); err != nil {
		return err
	}
	unresolved := false
	for id, receipt := range r.Job.QuestionCleanup {
		if !cleanupBinding(r, receipt) {
			return errQuestionCleanup
		}
		if pending[id] {
			receipt.Status = "needs_verification"
			unresolved = true
		} else {
			receipt.Status = "cleared"
		}
	}
	r.Job.PendingQuestions = matchingSession(current, r.Job.SessionID)
	if len(r.Job.PendingQuestions) != 0 {
		unresolved = true
	}
	r.Job.QuestionCleanupState = "cleared"
	if unresolved {
		r.Job.QuestionCleanupState = "needs_verification"
	}
	if s.persist(r) != nil {
		r.Job.QuestionCleanupState = "needs_verification"
		for _, receipt := range r.Job.QuestionCleanup {
			receipt.Status = "needs_verification"
		}
		return errQuestionCleanup
	}
	if unresolved {
		return errQuestionCleanup
	}
	return nil
}
