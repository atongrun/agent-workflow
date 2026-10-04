package node

import (
	"context"
	"encoding/json"
	"fmt"
	"path/filepath"
	"runtime"
	"strings"
	"time"

	"github.com/atongrun/agent-workflow/internal/opencode"
)

func sameWorkspace(a, b string) bool {
	a = filepath.Clean(a)
	b = filepath.Clean(b)
	if runtime.GOOS == "windows" {
		return strings.EqualFold(a, b)
	}
	return a == b
}
func (s *Server) uncertain(r *record, err error) {
	r.Job.Status = "uncertain"
	r.Job.Error = err.Error()
	r.lastBusy = time.Time{}
	_ = s.persist(r)
}
func (s *Server) finish(r *record, status string) {
	r.Job.Status = status
	now := time.Now().UTC()
	r.Job.CompletedAt = &now
	r.lastBusy = time.Time{}
}
func (s *Server) advance(ctx context.Context, p *project, r *record) {
	if r.Job.CancelRequested {
		if r.Job.SubmissionState == "queued" || r.Job.SubmissionState == "creating" || r.Job.SubmissionState == "ready" {
			s.finish(r, "cancelled")
			_ = s.persist(r)
			s.wake(p)
			return
		}
		s.reconcile(ctx, p, r)
		if !terminal(r.Job.Status) {
			s.abort(ctx, p, r)
		}
		_ = s.cleanupCancelledQuestions(ctx, p, r)
		return
	}
	if r.Job.SubmissionState == "queued" {
		r.Job.Status = "running"
		r.Job.Error = ""
		if r.Job.SessionID == "" {
			r.Job.SubmissionState = "creating"
			if s.persist(r) != nil {
				return
			}
			session, err := s.native.CreateSession(ctx, p.workspace, r.SessionTitle)
			if err != nil {
				s.uncertain(r, fmt.Errorf("native session creation outcome is unknown; no automatic retry: %w", err))
				return
			}
			// Keep the native ID even if its returned scope is invalid, for diagnosis.
			r.Job.SessionID = session.ID
			if !sameWorkspace(session.Directory, p.workspace) {
				s.uncertain(r, fmt.Errorf("native session returned a different workspace"))
				return
			}
		}
		r.Job.SubmissionState = "ready"
		if s.persist(r) != nil {
			return
		}
	}
	if r.Job.SubmissionState == "creating" {
		s.recoverSession(ctx, p, r)
		if r.Job.SubmissionState != "ready" {
			return
		}
	}
	if r.Job.SubmissionState == "ready" {
		session, err := s.native.Session(ctx, p.workspace, r.Job.SessionID)
		if err != nil {
			s.uncertain(r, err)
			return
		}
		if session.ID != r.Job.SessionID || !sameWorkspace(session.Directory, p.workspace) {
			s.uncertain(r, fmt.Errorf("native session scope does not match recorded workspace"))
			return
		}
		statuses, err := s.native.Statuses(ctx, p.workspace)
		if err != nil {
			s.uncertain(r, err)
			return
		}
		if state, ok := statuses[r.Job.SessionID]; ok && state.Type != "idle" {
			s.uncertain(r, fmt.Errorf("native session is already %s; refusing overlapping prompt", state.Type))
			return
		}
		if err = s.ensureEvents(p); err != nil {
			s.uncertain(r, fmt.Errorf("native event connection unavailable before dispatch: %w", err))
			return
		}
		r.Job.SubmissionState = "dispatching"
		r.Job.Status = "running"
		r.Job.Error = ""
		now := time.Now().UTC()
		r.Job.StartedAt = &now
		if s.persist(r) != nil {
			return
		}
		// NEVER repeat this POST, including after EOF, timeout, an HTTP error or crash.
		err = s.native.PromptAsync(ctx, p.workspace, r.Job.SessionID, r.Job.MessageID, executionPrompt(r.Request), r.Job.Model)
		if err != nil {
			s.uncertain(r, fmt.Errorf("native prompt outcome is unknown; reconcile original session, do not resubmit: %w", err))
			return
		}
		r.Job.SubmissionState = "submitted"
		if s.persist(r) != nil {
			return
		}
	}
	// Event recovery is best-effort for an already-submitted prompt. Polling the
	// original session remains authoritative and never causes a re-prompt.
	if r.Job.SubmissionState == "dispatching" || r.Job.SubmissionState == "submitted" {
		_ = s.ensureEvents(p)
	}
	s.reconcile(ctx, p, r)
}
func executionPrompt(req JobRequest) string {
	body, _ := json.MarshalIndent(struct {
		TaskID     string `json:"taskId"`
		Repository string `json:"repository"`
		Branch     string `json:"branch"`
		Plan       string `json:"approvedPlan"`
		Prompt     string `json:"instructions"`
	}{req.TaskID, req.Repository, req.Branch, req.Plan, req.Prompt}, "", "  ")
	return "Execute this approved coding request in the current configured workspace. Repository and branch are task metadata; perform any required Git operations yourself using native tools. Follow the approved plan and instructions. Report changes and actual validation results; do not claim tests or commits without tool evidence. Do not grant permissions or expand access on behalf of the user.\n\n" + string(body)
}
func (s *Server) recoverSession(ctx context.Context, p *project, r *record) {
	if r.Job.SessionID != "" {
		session, err := s.native.Session(ctx, p.workspace, r.Job.SessionID)
		if err != nil {
			s.uncertain(r, err)
			return
		}
		if session.ID != r.Job.SessionID || !sameWorkspace(session.Directory, p.workspace) {
			s.uncertain(r, fmt.Errorf("native session scope does not match recorded workspace"))
			return
		}
		r.Job.SubmissionState = "ready"
		r.Job.Error = ""
		_ = s.persist(r)
		return
	}
	sessions, err := s.native.Sessions(ctx, p.workspace)
	if err != nil {
		s.uncertain(r, err)
		return
	}
	var matches []opencode.Session
	for _, session := range sessions {
		if session.Title == r.SessionTitle && sameWorkspace(session.Directory, p.workspace) {
			matches = append(matches, session)
		}
	}
	if len(matches) != 1 {
		s.uncertain(r, fmt.Errorf("native session creation is unresolved (%d matching sessions); automatic creation is disabled", len(matches)))
		return
	}
	r.Job.SessionID = matches[0].ID
	r.Job.SubmissionState = "ready"
	r.Job.Error = ""
	_ = s.persist(r)
}
func (s *Server) reconcile(ctx context.Context, p *project, r *record) {
	if terminal(r.Job.Status) || s.fault() != nil {
		return
	}
	if r.Job.SubmissionState == "creating" {
		s.recoverSession(ctx, p, r)
		return
	}
	if r.Job.SubmissionState == "queued" || r.Job.SubmissionState == "ready" {
		return
	}
	if r.Job.SessionID == "" {
		s.uncertain(r, fmt.Errorf("native session identity is unknown"))
		return
	}
	session, err := s.native.Session(ctx, p.workspace, r.Job.SessionID)
	if err != nil {
		s.uncertain(r, err)
		return
	}
	if session.ID != r.Job.SessionID || !sameWorkspace(session.Directory, p.workspace) {
		s.uncertain(r, fmt.Errorf("native session scope does not match recorded workspace"))
		return
	}
	messages, err := s.native.Messages(ctx, p.workspace, r.Job.SessionID)
	if err != nil {
		s.uncertain(r, err)
		return
	}
	permissions, err := s.native.PendingPermissions(ctx, p.workspace)
	if err != nil {
		s.uncertain(r, fmt.Errorf("native permission recovery: %w", err))
		return
	}
	questions, err := s.native.PendingQuestions(ctx, p.workspace)
	if err != nil {
		s.uncertain(r, fmt.Errorf("native question recovery: %w", err))
		return
	}
	r.Job.PendingPermissions = matchingSession(permissions, r.Job.SessionID)
	r.Job.PendingQuestions = matchingSession(questions, r.Job.SessionID)
	if len(r.Job.PendingPermissions)+len(r.Job.PendingQuestions) > 0 {
		r.HadWait = true
	}
	statuses, err := s.native.Statuses(ctx, p.workspace)
	if err != nil {
		s.uncertain(r, err)
		return
	}
	status, active := statuses[r.Job.SessionID]
	if active && status.Type == "idle" {
		active = false
	}
	r.Job.NativeStatus = status.Type
	if !active {
		r.Job.NativeStatus = "idle"
	}
	now := time.Now().UTC()
	if active && (status.Type == "busy" || status.Type == "retry") && len(r.Job.PendingPermissions)+len(r.Job.PendingQuestions) == 0 {
		if !r.lastBusy.IsZero() {
			r.Job.ExecutionSeconds += now.Sub(r.lastBusy).Seconds()
		}
		r.lastBusy = now
	} else {
		if !r.lastBusy.IsZero() && len(r.Job.PendingPermissions)+len(r.Job.PendingQuestions) == 0 {
			r.Job.ExecutionSeconds += now.Sub(r.lastBusy).Seconds()
		}
		r.lastBusy = time.Time{}
	}
	seenUser := false
	var last *opencode.Message
	var evidence []Evidence
	var summary []string
	pending := false
	nativeSeconds := float64(0)
	for i := range messages {
		m := &messages[i]
		if m.Info.Role == "user" && m.Info.ID == r.Job.MessageID && m.Info.SessionID == r.Job.SessionID {
			seenUser = true
		}
		if m.Info.Role != "assistant" || m.Info.ParentID != r.Job.MessageID || m.Info.SessionID != r.Job.SessionID {
			continue
		}
		if m.Info.Time.Completed > m.Info.Time.Created && m.Info.Time.Created > 0 {
			nativeSeconds += float64(m.Info.Time.Completed-m.Info.Time.Created) / 1000
		}
		if last == nil || m.Info.Time.Created > last.Info.Time.Created || (m.Info.Time.Created == last.Info.Time.Created && m.Info.ID > last.Info.ID) {
			last = m
		}
		for _, part := range m.Parts {
			if part.Type == "text" && part.Text != "" {
				summary = append(summary, part.Text)
			}
			if part.Type != "tool" {
				continue
			}
			raw, _ := json.Marshal(part)
			evidence = append(evidence, Evidence{Kind: "tool", Source: "opencode:" + r.Job.SessionID + ":" + m.Info.ID + ":" + part.ID, Content: string(raw), Tool: part.Tool, Status: part.State.Status, CallID: part.CallID, MessageID: m.Info.ID, Input: part.State.Input, Output: part.State.Output, Error: part.State.Error, Metadata: part.State.Metadata, Verified: false})
			if part.State.Status == "pending" || part.State.Status == "running" {
				pending = true
			}
		}
	}
	if evidence == nil {
		evidence = []Evidence{}
	}
	r.Job.Evidence = evidence
	r.Job.Summary = strings.Join(summary, "\n\n")
	if seenUser {
		r.Job.SubmissionState = "submitted"
	}
	r.Job.Error = ""
	if r.Job.CancelRequested {
		r.Job.Status = "cancelling"
		if !active && !pending {
			if seenUser && terminalAssistant(last) {
				s.finish(r, "completed")
				r.Job.Error = "native turn completed before cancellation took effect"
			} else if r.Job.AbortConfirmed {
				s.finish(r, "cancelled")
				if r.Job.TimedOut {
					r.Job.Error = "execution time budget exhausted; native abort confirmed"
				}
			} else if seenUser && last != nil && hasError(last.Info.Error) {
				s.finish(r, "failed")
				r.Job.Error = string(last.Info.Error)
			}
		}
	} else if active {
		r.Job.Status = "running"
		if status.Message != "" {
			r.Job.Error = status.Message
		}
	} else if seenUser && last != nil && hasError(last.Info.Error) && !pending {
		s.finish(r, "failed")
		r.Job.Error = string(last.Info.Error)
	} else if seenUser && terminalAssistant(last) && !pending {
		s.finish(r, "completed")
	} else if r.Job.NativeError != "" && !active {
		s.finish(r, "failed")
		r.Job.Error = r.Job.NativeError
	} else {
		r.Job.Status = "uncertain"
		r.Job.Error = "native turn has no verifiable terminal response; idle or acceptance is not completion"
	}
	if terminal(r.Job.Status) && !r.HadWait && r.Job.ExecutionSeconds == 0 {
		r.Job.ExecutionSeconds = nativeSeconds
	}
	if !terminal(r.Job.Status) && r.Job.ExecutionSeconds >= float64(r.Job.TimeoutSeconds) {
		r.Job.TimedOut = true
		r.Job.CancelRequested = true
		r.CancelPhase = "pending"
		r.Job.Status = "cancelling"
		r.Job.Error = "execution time budget exhausted; awaiting native abort"
	}
	if s.persist(r) != nil {
		return
	}
	if terminal(r.Job.Status) {
		s.wake(p)
	}
}
func hasError(raw json.RawMessage) bool {
	return len(raw) > 0 && string(raw) != "null" && string(raw) != "{}"
}
func terminalAssistant(m *opencode.Message) bool {
	if m == nil || m.Info.Time.Completed == 0 || m.Info.Finish == "" || m.Info.Finish == "tool-calls" || m.Info.Finish == "unknown" || hasError(m.Info.Error) {
		return false
	}
	// A completed tool invocation is evidence, but a tool-bearing assistant can
	// still cause another model iteration even when its provider reported stop.
	for _, p := range m.Parts {
		if p.Type == "tool" {
			var meta struct {
				ProviderExecuted bool `json:"providerExecuted"`
			}
			_ = json.Unmarshal(p.Metadata, &meta)
			if !meta.ProviderExecuted {
				return false
			}
		}
	}
	return true
}
func (s *Server) abort(ctx context.Context, p *project, r *record) {
	if terminal(r.Job.Status) || s.fault() != nil {
		return
	}
	if r.Job.SessionID == "" {
		s.uncertain(r, fmt.Errorf("cannot confirm cancellation until native session identity is recovered"))
		return
	}
	// Once a receipt is durable, polling is enough; never abort a subsequent turn.
	if r.Job.AbortConfirmed {
		return
	}
	session, err := s.native.Session(ctx, p.workspace, r.Job.SessionID)
	if err != nil {
		s.uncertain(r, err)
		return
	}
	if session.ID != r.Job.SessionID || !sameWorkspace(session.Directory, p.workspace) {
		s.uncertain(r, fmt.Errorf("refusing abort: native workspace mismatch"))
		return
	}
	r.CancelPhase = "dispatching"
	r.Job.Status = "cancelling"
	if s.persist(r) != nil {
		return
	}
	ok, err := s.native.Abort(ctx, p.workspace, r.Job.SessionID)
	if err != nil {
		s.uncertain(r, fmt.Errorf("native abort outcome unknown: %w", err))
		return
	}
	if !ok {
		s.uncertain(r, fmt.Errorf("native server did not confirm abort"))
		return
	}
	r.CancelPhase = "confirmed"
	r.Job.AbortConfirmed = true
	if s.persist(r) != nil {
		return
	}
	s.reconcile(ctx, p, r)
}

func matchingSession(input []json.RawMessage, id string) []json.RawMessage {
	var out []json.RawMessage
	for _, raw := range input {
		var item struct {
			SessionID string `json:"sessionID"`
		}
		if json.Unmarshal(raw, &item) == nil && item.SessionID == id {
			out = append(out, raw)
		}
	}
	return out
}
