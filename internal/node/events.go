package node

import (
	"encoding/json"
	"strings"
	"time"
)

func (s *Server) ensureEvents(p *project) error {
	if p.events != nil {
		return nil
	}
	stream, err := s.native.OpenEvents(s.ctx, p.workspace)
	if err != nil {
		return err
	}
	p.events = stream
	s.wg.Add(1)
	go func() {
		defer s.wg.Done()
		defer stream.Close()
		defer func() {
			p.mu.Lock()
			if p.events == stream {
				p.events = nil
			}
			p.mu.Unlock()
		}()
		for {
			event, err := stream.Next()
			if err != nil {
				return
			}
			if event.Type != "session.error" && !strings.HasPrefix(event.Type, "permission.") && !strings.HasPrefix(event.Type, "question.") {
				continue
			}
			var info struct {
				SessionID string          `json:"sessionID"`
				ID        string          `json:"id"`
				RequestID string          `json:"requestID"`
				Error     json.RawMessage `json:"error"`
			}
			if json.Unmarshal(event.Properties, &info) != nil || info.SessionID == "" {
				continue
			}
			p.mu.Lock()
			s.mu.Lock()
			var rec *record
			for _, r := range s.jobs {
				if r.Job.ProjectID == p.id && r.Job.SessionID == info.SessionID && !terminal(r.Job.Status) && (r.Job.SubmissionState == "dispatching" || r.Job.SubmissionState == "submitted") {
					rec = r
					break
				}
			}
			s.mu.Unlock()
			if rec != nil && s.fault() == nil {
				if event.Type == "session.error" {
					rec.Job.NativeError = string(info.Error)
					rec.Job.Error = string(info.Error)
				}
				if event.Type == "permission.asked" {
					rec.Job.PendingPermissions = append(rec.Job.PendingPermissions, event.Properties)
				}
				if event.Type == "question.asked" {
					rec.Job.PendingQuestions = append(rec.Job.PendingQuestions, event.Properties)
				}
				if event.Type == "question.replied" || event.Type == "question.rejected" {
					var keep []json.RawMessage
					for _, raw := range rec.Job.PendingQuestions {
						var old struct {
							ID string `json:"id"`
						}
						_ = json.Unmarshal(raw, &old)
						if old.ID != info.RequestID && old.ID != info.ID {
							keep = append(keep, raw)
						}
					}
					rec.Job.PendingQuestions = keep
				}
				if event.Type == "permission.replied" {
					var keep []json.RawMessage
					for _, raw := range rec.Job.PendingPermissions {
						var old struct {
							ID string `json:"id"`
						}
						_ = json.Unmarshal(raw, &old)
						if old.ID != info.RequestID && old.ID != info.ID {
							keep = append(keep, raw)
						}
					}
					rec.Job.PendingPermissions = keep
				}
				if len(rec.Job.PendingPermissions)+len(rec.Job.PendingQuestions) > 0 {
					rec.HadWait = true
					if !rec.lastBusy.IsZero() {
						rec.Job.ExecutionSeconds += time.Since(rec.lastBusy).Seconds()
						rec.lastBusy = time.Time{}
					}
				}
				_ = s.persist(rec)
				s.wake(p)
			}
			p.mu.Unlock()
		}
	}()
	return nil
}
