package host

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
	"github.com/atongrun/agent-workflow/internal/node"
)

func (s *Server) nodeCall(ctx context.Context, nodeID, method, path string, payload any, out any) (int, error) {
	cfg, ok := s.cfg.Nodes[nodeID]
	if !ok {
		return 0, fmt.Errorf("node not configured")
	}
	var body io.Reader
	if payload != nil {
		body = bytes.NewReader(mustJSON(payload))
	}
	req, err := http.NewRequestWithContext(ctx, method, strings.TrimRight(cfg.URL, "/")+path, body)
	if err != nil {
		return 0, err
	}
	req.Header.Set("Authorization", "Bearer "+os.Getenv(cfg.TokenEnv))
	req.Header.Set("Content-Type", "application/json")
	res, err := s.http.Do(req)
	if err != nil {
		return 0, err
	}
	defer res.Body.Close()
	data, err := io.ReadAll(io.LimitReader(res.Body, 16*1024*1024))
	if err != nil {
		return res.StatusCode, err
	}
	if res.StatusCode < 200 || res.StatusCode >= 300 {
		return res.StatusCode, &nodeHTTPError{Status: res.StatusCode, Body: strings.TrimSpace(string(data))}
	}
	if out != nil {
		if err = json.Unmarshal(data, out); err != nil {
			return res.StatusCode, err
		}
	}
	return res.StatusCode, nil
}

type nodeHTTPError struct {
	Status int
	Body   string
}

func (e *nodeHTTPError) Error() string { return fmt.Sprintf("node HTTP %d: %s", e.Status, e.Body) }
func executionNodeID(t *core.Task) string {
	if t.Execution != nil && t.Execution.Target != nil {
		return t.Execution.Target.NodeID
	}
	return t.NodeID
}
func (s *Server) jobRequest(t *core.Task) node.JobRequest {
	// Existing executions have no target snapshot and retain their original
	// serialization. Never add new fields to the node's durable job fingerprint.
	if t.Execution.Target != nil {
		copy := *t
		copy.ProjectID = t.Execution.Target.ProjectID
		copy.Repository = t.Execution.Target.Repository
		t = &copy
	}
	reviewContext := ""
	if t.Settings.Reviewer != "pi" && t.Completion != nil {
		reviewContext = "\n\nPrior Pi execution findings for this explicitly authorized rework:\n" + string(mustJSON(t.Completion))
	} else if len(t.ReviewHistory) > 0 {
		reviewContext = "\n\nPrior review findings for this explicitly authorized rework:\n" + string(mustJSON(t.ReviewHistory[len(t.ReviewHistory)-1]))
	}
	return node.JobRequest{RequestID: t.Execution.RequestID, TaskID: t.ID, ProjectID: t.ProjectID, Repository: t.Repository, Branch: t.Branch, Plan: t.Plan.Content, Prompt: fmt.Sprintf("Implement only this explicitly confirmed task.\nTitle: %s\nGoal: %s\nAcceptance criteria: %s\nRepository: %s\nBase branch: %s\nWork branch: %s\n\nConfirmed plan:\n%s\n\nYou own all Git operations via your native tools. Preserve existing work. Run relevant checks and report actual artifacts, commit references, command output and failures. Capture the actual code diff with git diff or git show, test command output/exit status, and remote branch SHA with git ls-remote, using separate native tool calls with unmasked exit codes. Missing evidence must be reported as unknown. Do not claim tests, pushes or commits that did not happen.", t.Title, t.Goal, t.AcceptanceCriteria, t.Repository, t.Settings.DefaultBranch, t.Branch, t.Plan.Content) + reviewContext, TimeoutSeconds: t.Execution.TimeoutSeconds, SessionID: t.Execution.OriginalSessionID}
}
func (s *Server) recoverExecutions() {
	for _, t := range s.store.Snapshot().Tasks {
		if t.DeletedAt != nil {
			continue
		}
		if executionActive(t) {
			s.monitor(t.ID)
		} else if t.Execution != nil && resultTerminal(t) && (t.Status == "reporting" || t.Status == "review") {
			id := t.ID
			s.launch(func() { s.beginExecutionSummary(id) })
		}
	}
}
func (s *Server) monitor(id string) {
	s.mu.Lock()
	if s.monitors[id] {
		s.mu.Unlock()
		return
	}
	s.monitors[id] = true
	s.mu.Unlock()
	s.launch(func() {
		defer func() { s.mu.Lock(); delete(s.monitors, id); s.mu.Unlock() }()
		ticker := time.NewTicker(2 * time.Second)
		defer ticker.Stop()
		for {
			t, err := s.task(id)
			if err != nil || !executionActive(t) {
				return
			}
			observedRevision := t.LifecycleRevision
			var job node.Job
			ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
			status, err := s.nodeCall(ctx, executionNodeID(t), "GET", "/v1/jobs/"+t.Execution.JobID, nil, &job)
			cancel()
			if status == 404 {
				if t.Execution.CancelRequested && !t.Execution.DispatchAttempted {
					_ = s.store.Update(func(st *core.State) error {
						cur := st.Tasks[id]
						if cur.DeletedAt == nil && cur.LifecycleRevision == t.LifecycleRevision && cur.Execution.RequestID == t.Execution.RequestID && !cur.Execution.DispatchAttempted {
							cur.Execution.Status = "cancelled"
							cur.Status = "cancelled"
							core.Changed(st, cur)
						}
						return nil
					})
					return
				}
				if t.Execution.DispatchAttempted {
					err = fmt.Errorf("node no longer has the durable job; verify native session and workspace before any retry")
				} else {
					marked := false
					var dispatchRequest node.JobRequest
					markErr := s.store.Update(func(st *core.State) error {
						cur := st.Tasks[id]
						if cur.DeletedAt != nil || cur.LifecycleRevision != t.LifecycleRevision || cur.Execution.RequestID != t.Execution.RequestID || cur.Execution.DispatchAttempted || cur.Execution.CancelRequested {
							return nil
						}
						// Newly reserved runs must revalidate after queueing/restart,
						// immediately before the first durable dispatch attempt. Never
						// retrofit old jobs or modify an already-dispatched fingerprint.
						if target := cur.Execution.Target; target != nil {
							bound := *cur
							bound.ProjectID, bound.NodeID = target.ProjectID, target.NodeID
							bound.Repository, bound.RepositoryID = target.Repository, target.RepositoryID
							if err := s.validateTarget(&bound); err != nil {
								return err
							}
						}
						// Shared-plan consumption can change while this task is queued.
						left := remainingSeconds(cur)
						if left <= 0 || cur.Execution.TimeoutSeconds <= 0 {
							return fail("budget_exhausted", "execution budget exhausted before dispatch", 409)
						}
						if left < cur.Execution.TimeoutSeconds {
							cur.Execution.TimeoutSeconds = left
						}
						cur.Execution.DispatchAttempted = true
						cur.Execution.Status = "dispatching"
						marked = true
						// Submit exactly the fingerprint persisted by this reservation.
						dispatchRequest = s.jobRequest(cur)
						core.Changed(st, cur)
						return nil
					})
					if markErr != nil {
						err = markErr
					} else if !marked {
						continue
					} else {
						ctx, cancel = context.WithTimeout(context.Background(), 15*time.Second)
						_, err = s.nodeCall(ctx, executionNodeID(t), "POST", "/v1/jobs", dispatchRequest, &job)
						cancel()
					}
				}
			}
			if err != nil {
				_ = s.store.Update(func(st *core.State) error {
					t := st.Tasks[id]
					if t.LifecycleRevision != observedRevision || !executionActive(t) {
						return nil
					}
					message := "Node unavailable or outcome unknown: " + err.Error()
					if t.Status == "needs_verification" && t.Execution.Error == message {
						return nil
					}
					t.Status = "needs_verification"
					t.Execution.Error = message
					core.Changed(st, t)
					return nil
				})
			} else if job.ID != t.Execution.JobID || job.TaskID != id || job.RequestID != t.Execution.RequestID {
				_ = s.store.Update(func(st *core.State) error {
					t := st.Tasks[id]
					if t.DeletedAt != nil || t.LifecycleRevision != observedRevision {
						return nil
					}
					t.Status = "needs_verification"
					t.LastError = "Node returned mismatched execution identity"
					core.Changed(st, t)
					return nil
				})
				return
			} else {
				s.applyJob(id, &job, t.LifecycleRevision)
				latest, _ := s.task(id)
				if latest.DeletedAt != nil || latest.LifecycleRevision != t.LifecycleRevision {
					return
				}
				if remainingSeconds(latest) <= 0 {
					s.stopForBudget(id)
				}
				if t.Execution.CancelRequested && !job.CancelRequested {
					s.launch(func() {
						s.cancelExecution("cancel-reconcile-"+t.Execution.RequestID, id, t.Execution.RequestID, t.LifecycleRevision)
					})
				}
				if job.Status == "completed" || job.Status == "failed" || job.Status == "cancelled" {
					s.beginExecutionSummary(id)
					return
				}
			}
			select {
			case <-s.stop:
				return
			case <-ticker.C:
			}
		}
	})
}
func (s *Server) applyJob(id string, job *node.Job, lifecycleRevision int) {
	_ = s.store.Update(func(st *core.State) error {
		t := st.Tasks[id]
		if t == nil || t.DeletedAt != nil || t.LifecycleRevision != lifecycleRevision {
			return nil
		}
		before := string(mustJSON(t))
		e := t.Execution
		if e == nil || e.JobID != job.ID || e.RequestID != job.RequestID || t.ID != job.TaskID {
			return nil
		}
		// Native terminal receipts are absorbing. Late polling never reopens
		// a reviewed execution or regresses it back to running/uncertain.
		wasTerminal := e.Status == "completed" || e.Status == "failed" || e.Status == "cancelled"
		if wasTerminal {
			// A cancelled job may clear an orphaned native question later.
			// Refresh only waits proven cleared by that original cancellation;
			// terminal outcome, verdict, evidence and accrued counters absorb polls.
			if e.Status == "cancelled" && job.Status == "cancelled" && e.CancelRequested && job.CancelRequested && job.AbortConfirmed && job.SessionID == e.SessionID && cancelledQuestionWaitsCleared(e, job) {
				e.PendingQuestions = job.PendingQuestions
				if before != string(mustJSON(t)) {
					core.Emit(st, id, "execution.event", e)
					core.Changed(st, t)
				}
			}
			return nil
		}
		e.SessionID = job.SessionID
		e.Status = job.Status
		e.Summary = bounded(job.Summary, 32*1024)
		e.Error = job.Error
		e.PendingPermissions = job.PendingPermissions
		e.PendingQuestions = job.PendingQuestions
		e.StartedAt = job.StartedAt
		e.FinishedAt = job.CompletedAt
		e.CancelRequested = e.CancelRequested || job.CancelRequested
		e.Evidence = []core.Evidence{}
		evidence := job.Evidence
		if len(evidence) > 100 {
			evidence = evidence[len(evidence)-100:]
		}
		for _, v := range evidence {
			source := v.Source
			if source == "" {
				source = "opencode.native:" + v.MessageID + ":" + v.CallID
			}
			truncated := len(v.Output) > 64*1024 || len(v.Input) > 64*1024 || len(v.Metadata) > 8*1024
			input, metadata := v.Input, v.Metadata
			if len(input) > 64*1024 {
				input = nil
			}
			if len(metadata) > 8*1024 {
				metadata = nil
			}
			e.Evidence = append(e.Evidence, core.Evidence{Kind: v.Kind, Content: bounded(string(mustJSON(v)), 64*1024), Source: source, Verified: false, Tool: v.Tool, Status: v.Status, MessageID: v.MessageID, CallID: v.CallID, SessionID: job.SessionID, Input: input, Output: bounded(v.Output, 64*1024), Metadata: metadata, Truncated: truncated})
		}
		elapsed := int64(job.ExecutionSeconds)
		if elapsed > e.AccountedSeconds {
			diff := elapsed - e.AccountedSeconds
			t.Budget.TaskSeconds += diff
			t.Budget.PlanSeconds += diff
			e.AccountedSeconds = elapsed
		}
		if !wasTerminal {
			switch job.Status {
			case "running":
				t.Status = "executing"
			case "queued":
				t.Status = "queued"
			case "uncertain", "cancelling":
				t.Status = "needs_verification"
			case "failed":
				t.Status = "blocked"
			case "cancelled":
				t.Status = "cancelled"
			case "completed":
				if t.Settings.Reviewer == "pi" {
					t.Status = "review"
					t.Phase = "review"
				} else {
					t.Status = "reporting"
					t.Phase = "execution"
				}
			}
		}
		if !wasTerminal && (job.Status == "completed" || job.Status == "failed" || job.Status == "cancelled") && t.Settings.Reviewer != "pi" {
			t.Status = "reporting"
			t.Phase = "execution"
			e.ResultReview = newResultReview(t)
		}
		if req := st.Requests[e.RequestID]; req != nil {
			req.Status = job.Status
		}
		if before == string(mustJSON(t)) {
			return nil
		}
		core.Emit(st, id, "execution.event", e)
		core.Changed(st, t)
		return nil
	})
}
func (s *Server) beginAutomaticReview(id string) {
	t, err := s.task(id)
	if err != nil || t.DeletedAt != nil || t.Status != "review" {
		return
	}
	if ref := t.Sessions["architect"]; ref != nil && (ref.Busy || ref.Pending) {
		return
	}
	if remainingSeconds(t) <= 0 {
		_ = s.store.Update(func(st *core.State) error {
			if st.Tasks[id].DeletedAt != nil || st.Tasks[id].LifecycleRevision != t.LifecycleRevision || st.Tasks[id].Status != t.Status {
				return nil
			}
			st.Tasks[id].Status = "blocked"
			st.Tasks[id].LastError = "Budget exhausted before independent review"
			core.Changed(st, st.Tasks[id])
			return nil
		})
		return
	}
	requestID := "review-" + t.Execution.RequestID
	duplicate, err := s.reserve(requestID, id, "auto_review", map[string]string{"executionRequestId": t.Execution.RequestID}, func(st *core.State) error {
		cur := st.Tasks[id]
		if cur.LifecycleRevision != t.LifecycleRevision || cur.Execution == nil || cur.Execution.RequestID != t.Execution.RequestID || cur.Execution.Status != "completed" || cur.Status != "review" {
			return fail("stale_execution", "automatic review target changed", 409)
		}
		if ref := cur.Sessions["architect"]; ref != nil && (ref.Busy || ref.Pending) {
			return fail("role_busy", "architect has active native work", 409)
		}
		for _, old := range cur.ReviewHistory {
			if old.ExecutionRequestID == cur.Execution.RequestID {
				return fail("review_closed", "execution already reviewed", 409)
			}
		}
		if remainingSeconds(st.Tasks[id]) <= 0 {
			st.Tasks[id].Status = "blocked"
			st.Tasks[id].LastError = "Budget exhausted before independent review"
			core.Changed(st, st.Tasks[id])
			return fail("budget_exhausted", "review requires budget", 409)
		}
		prepareReviewer(st.Tasks[id], requestID)
		core.Changed(st, st.Tasks[id])
		return nil
	})
	if err == nil && !duplicate {
		s.promptReview(requestID, id)
	}
}
func (s *Server) cancelExecution(requestID, id, targetID string, lifecycleRevision int) {
	t, err := s.task(id)
	if err != nil || t.DeletedAt != nil || t.LifecycleRevision != lifecycleRevision || t.Execution == nil {
		return
	}
	if t.Execution.RequestID != targetID {
		s.requestDone(requestID, "failed", fmt.Errorf("execution target is stale"))
		return
	}
	var job node.Job
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	_, err = s.nodeCall(ctx, executionNodeID(t), "POST", "/v1/jobs/"+t.Execution.JobID+"/cancel", map[string]string{"requestId": requestID}, &job)
	if err != nil {
		s.requestDone(requestID, "needs_verification", err)
		return
	}
	if job.ID != t.Execution.JobID {
		s.requestDone(requestID, "needs_verification", fmt.Errorf("cancel receipt identity mismatch"))
		return
	}
	s.applyJob(id, &job, t.LifecycleRevision)
	s.requestDone(requestID, "accepted_native", nil)
	s.monitor(id)
}

func bounded(text string, limit int) string {
	if len(text) <= limit {
		return text
	}
	return text[:limit] + "\n[Truncated projection; inspect the native session/message reference for complete evidence]"
}

func cancelledQuestionWaitsCleared(e *core.Execution, job *node.Job) bool {
	if len(e.PendingQuestions) == 0 || len(job.PendingQuestions) != 0 || job.QuestionCleanupState != "cleared" {
		return false
	}
	for _, raw := range e.PendingQuestions {
		var q struct {
			ID        string `json:"id"`
			SessionID string `json:"sessionID"`
		}
		if json.Unmarshal(raw, &q) != nil || q.ID == "" || q.SessionID != e.SessionID {
			return false
		}

	}
	return true
}
