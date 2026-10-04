package node

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"sync"
	"testing"
	"time"

	"github.com/atongrun/agent-workflow/internal/opencode"
)

func cancelledQuestionFixture(t *testing.T) (*Server, *fakeNative, Config, Job, string) {
	t.Helper()
	s, f, cfg, job, _, qid := questionFixture(t)
	f.mu.Lock()
	f.statuses[job.SessionID] = opencode.Status{Type: "idle"}
	f.messages[job.SessionID][1].Parts[0].State.Status = "error"
	f.permissions = []json.RawMessage{json.RawMessage(`{"id":"per_preserved","sessionID":"ses_other"}`)}
	f.mu.Unlock()
	rec, p := s.lookup(job.ID)
	p.mu.Lock()
	rec.Job.Status = "cancelled"
	rec.Job.CancelRequested = true
	rec.Job.AbortConfirmed = true
	rec.CancelPhase = "confirmed"
	rec.CancelRequestID = "cancel-original"
	now := time.Now().UTC()
	rec.Job.CompletedAt = &now
	rec.Job.ExecutionSeconds = 42
	rec.Job.Summary = "preserve cancelled history"
	rec.Job.Error = "original cancellation"
	if err := s.persist(rec); err != nil {
		t.Fatal(err)
	}
	job = rec.Job
	p.mu.Unlock()
	return s, f, cfg, job, qid
}
func cleanupCall(t *testing.T, s *Server, job Job, request string) int {
	t.Helper()
	return questionCall(t, s, "POST", "/v1/jobs/"+job.ID+"/cancel", map[string]string{"requestId": request}).Code
}
func TestCancelledQuestionCleanupConcurrentExactScope(t *testing.T) {
	s, f, _, job, qid := cancelledQuestionFixture(t)
	f.mu.Lock()
	other := opencode.Question{ID: "que_other", SessionID: "ses_other"}
	raw, _ := json.Marshal(other)
	f.questions = append(f.questions, raw)
	f.mu.Unlock()
	var wg sync.WaitGroup
	for range 12 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if code := cleanupCall(t, s, job, "cancel-retry"); code != 200 {
				t.Errorf("cancel retry %d", code)
			}
		}()
	}
	wg.Wait()
	rec, p := s.lookup(job.ID)
	p.mu.Lock()
	got := rec.Job
	receipt := got.QuestionCleanup[qid]
	if receipt == nil || receipt.Status != "cleared" || !receipt.Acknowledged || receipt.CancelRequestID != "cancel-original" || rec.CancelRequestID != "cancel-original" {
		t.Fatal("cleanup lost authority or receipt", receipt)
	}
	got.QuestionCleanup = nil
	got.QuestionCleanupState = ""
	if !reflect.DeepEqual(got, job) { // Only wait projection and update timestamp may change.
		got.UpdatedAt = job.UpdatedAt
		got.PendingQuestions = job.PendingQuestions
		if !reflect.DeepEqual(got, job) {
			t.Fatal("cleanup changed cancelled history/counters")
		}
	}
	p.mu.Unlock()
	f.mu.Lock()
	rejects := f.questionRejects
	replies := f.questionReplies
	remaining := f.questions
	permissions := f.permissions
	prompts, creates, aborts := f.prompts, f.creates, f.aborts
	f.mu.Unlock()
	if rejects != 1 || replies != 0 || len(remaining) != 1 || len(permissions) != 1 || prompts != 1 || creates != 1 || aborts != 0 {
		t.Fatal("cleanup broadened scope", rejects, replies)
	}
	awaitCleanupIdle(t, s)
}
func TestCancelledQuestionCleanupLostACKAndRestartNoReplay(t *testing.T) {
	s, f, cfg, job, qid := cancelledQuestionFixture(t)
	f.mu.Lock()
	f.dropQuestionReject = true
	f.afterQuestionReject = func() { f.questionReadStatus = 503 }
	f.mu.Unlock()
	if code := cleanupCall(t, s, job, "cancel-original"); code != 409 {
		t.Fatal(code)
	}
	if err := s.Idle(); err == nil {
		t.Fatal("unverified cleanup allowed lifecycle")
	}
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	f.mu.Lock()
	f.questionReadStatus = 0
	f.afterQuestionReject = nil
	f.mu.Unlock()
	reopened := startNode(t, cfg)
	if code := cleanupCall(t, reopened, job, "cancel-original"); code != 200 {
		t.Fatal(code)
	}
	rec, p := reopened.lookup(job.ID)
	p.mu.Lock()
	receipt := *rec.Job.QuestionCleanup[qid]
	p.mu.Unlock()
	if receipt.Status != "cleared" || receipt.Acknowledged {
		t.Fatal("invented native ACK", receipt)
	}
	f.mu.Lock()
	count := f.questionRejects
	f.mu.Unlock()
	if count != 1 {
		t.Fatal("restart resent reject", count)
	}
	awaitCleanupIdle(t, reopened)
}
func TestCancelledQuestionCleanupPendingNeverResends(t *testing.T) {
	s, f, _, job, qid := cancelledQuestionFixture(t)
	f.mu.Lock()
	f.retainQuestionOnReject = true
	f.mu.Unlock()
	for range 2 {
		if code := cleanupCall(t, s, job, "cancel-original"); code != 409 {
			t.Fatal(code)
		}
	}
	f.mu.Lock()
	count := f.questionRejects
	f.mu.Unlock()
	if count != 1 {
		t.Fatal("resent pending reject", count)
	}
	rec, p := s.lookup(job.ID)
	p.mu.Lock()
	receipt := *rec.Job.QuestionCleanup[qid]
	p.mu.Unlock()
	if !receipt.Acknowledged || receipt.Status != "needs_verification" {
		t.Fatal(receipt)
	}
	if err := s.Idle(); err == nil {
		t.Fatal("pending native question allowed stop")
	}
}

func TestCancelledQuestionCleanup404RequiresAuthoritativeAbsence(t *testing.T) {
	for _, pending := range []bool{false, true} {
		t.Run(fmt.Sprint(pending), func(t *testing.T) {
			s, f, _, job, qid := cancelledQuestionFixture(t)
			f.mu.Lock()
			f.questionRejectStatus = 404
			f.retainQuestionOnReject = pending
			f.mu.Unlock()
			wantCode := 200
			wantState := "cleared"
			if pending {
				wantCode = 409
				wantState = "needs_verification"
			}
			for range 2 {
				if code := cleanupCall(t, s, job, "cancel-original"); code != wantCode {
					t.Fatal("404 reconciliation", code)
				}
			}
			rec, p := s.lookup(job.ID)
			p.mu.Lock()
			receipt := *rec.Job.QuestionCleanup[qid]
			state := rec.Job.QuestionCleanupState
			p.mu.Unlock()
			f.mu.Lock()
			calls := f.questionRejects
			f.mu.Unlock()
			if receipt.Acknowledged || receipt.Status != wantState || state != wantState || calls != 1 {
				t.Fatal("404 invented ACK or replayed rejection", receipt, state, calls)
			}
			if pending {
				if err := s.Idle(); err == nil {
					t.Fatal("404 with a pending question allowed idle")
				}
			} else {
				awaitCleanupIdle(t, s)
			}
		})
	}
}
func TestCancelledQuestionCleanupRefusesUnprovenTurn(t *testing.T) {
	for _, mode := range []string{"unknown_status", "later_user", "unmatched_tool", "malformed", "no_cancel_authority", "completed", "unknown_tool"} {
		t.Run(mode, func(t *testing.T) {
			s, f, _, job, _ := cancelledQuestionFixture(t)
			f.mu.Lock()
			switch mode {
			case "unknown_status":
				f.statuses[job.SessionID] = opencode.Status{Type: "unknown"}
			case "missing_status":
				delete(f.statuses, job.SessionID)
			case "later_user":
				m := opencode.Message{Info: opencode.MessageInfo{ID: "msg_later", SessionID: job.SessionID, Role: "user"}}
				m.Info.Time.Created = time.Now().UnixMilli() + 100
				f.messages[job.SessionID] = append(f.messages[job.SessionID], m)
			case "unmatched_tool":
				f.messages[job.SessionID][1].Parts[0].CallID = "other"
			case "unknown_tool":
				f.messages[job.SessionID][1].Parts[0].State.Status = "unknown"
			case "malformed":
				f.questions = []json.RawMessage{json.RawMessage(`{"id":"que_invalid"}`)}
			}
			f.mu.Unlock()
			rec, p := s.lookup(job.ID)
			p.mu.Lock()
			if mode == "no_cancel_authority" {
				rec.CancelRequestID = ""
			}
			if mode == "completed" {
				rec.Job.Status = "completed"
			}
			p.mu.Unlock()
			code := cleanupCall(t, s, job, "cancel-new")
			if mode != "no_cancel_authority" && mode != "completed" && code != 409 {
				t.Fatal(code)
			}
			f.mu.Lock()
			count := f.questionRejects
			f.mu.Unlock()
			if count != 0 {
				t.Fatal("unproven question rejected")
			}
			if mode != "no_cancel_authority" && mode != "completed" && s.Idle() == nil {
				t.Fatal("unproven cleanup allowed lifecycle")
			}

		})
	}
}
func TestCancelledQuestionCleanupOutcomePersistenceFailure(t *testing.T) {
	s, f, cfg, job, qid := cancelledQuestionFixture(t)
	destination := filepath.Join(s.jobsDir, job.ID+".json")
	backup := destination + "-saved"
	f.mu.Lock()
	f.afterQuestionReject = func() {
		if err := os.Rename(destination, backup); err != nil {
			t.Error(err)
		}
		if err := os.Mkdir(destination, 0700); err != nil {
			t.Error(err)
		}
	}
	f.mu.Unlock()
	if code := cleanupCall(t, s, job, "cancel-original"); code != 409 {
		t.Fatal(code)
	}
	rec, p := s.lookup(job.ID)
	p.mu.Lock()
	receipt := *rec.Job.QuestionCleanup[qid]
	p.mu.Unlock()
	if receipt.Acknowledged || receipt.Status != "needs_verification" {
		t.Fatal("undurable outcome exposed success", receipt)
	}
	if err := s.Idle(); err == nil {
		t.Fatal("faulted node allowed stop")
	}
	s.Close()
	if err := os.Remove(destination); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(backup, destination); err != nil {
		t.Fatal(err)
	}
	f.mu.Lock()
	f.afterQuestionReject = nil
	f.mu.Unlock()
	reopened := startNode(t, cfg)
	if code := cleanupCall(t, reopened, job, "cancel-original"); code != 200 {
		t.Fatal(code)
	}
	f.mu.Lock()
	count := f.questionRejects
	f.mu.Unlock()
	if count != 1 {
		t.Fatal("failure/restart resent reject")
	}
}

func TestCancelledQuestionCleanupNativeIdleMapOmitsSession(t *testing.T) {
	s, f, _, job, _ := cancelledQuestionFixture(t)
	f.mu.Lock()
	delete(f.statuses, job.SessionID)
	f.mu.Unlock()
	if code := cleanupCall(t, s, job, "cancel-original"); code != 200 {
		t.Fatal(code)
	}
}

func TestCancelledQuestionCleanupStopsBeforeSecondRejectOnNativeChange(t *testing.T) {
	s, f, _, job, _ := cancelledQuestionFixture(t)
	f.mu.Lock()
	var q opencode.Question
	json.Unmarshal(f.questions[0], &q)
	q.ID = "que_second"
	q.Tool.CallID = "call_second"
	raw, _ := json.Marshal(q)
	f.questions = append(f.questions, raw)
	part := f.messages[job.SessionID][1].Parts[0]
	part.ID = "part_second"
	part.CallID = "call_second"
	f.messages[job.SessionID][1].Parts = append(f.messages[job.SessionID][1].Parts, part)
	f.afterQuestionReject = func() { f.statuses[job.SessionID] = opencode.Status{Type: "busy"} }
	f.mu.Unlock()
	if code := cleanupCall(t, s, job, "cancel-original"); code != 409 {
		t.Fatal(code)
	}
	f.mu.Lock()
	count := f.questionRejects
	remaining := len(f.questions)
	f.mu.Unlock()
	if count != 1 || remaining != 1 {
		t.Fatal("cleanup continued after native turn changed", count, remaining)
	}
	if s.Idle() == nil {
		t.Fatal("native change allowed lifecycle")
	}
}
func TestCancelledQuestionCleanupPredispatchFailure(t *testing.T) {
	s, f, _, job, _ := cancelledQuestionFixture(t)
	destination := filepath.Join(s.jobsDir, job.ID+".json")
	backup := destination + "-saved"
	if err := os.Rename(destination, backup); err != nil {
		t.Fatal(err)
	}
	defer func() {
		if err := os.Remove(destination); err != nil {
			t.Error(err)
		}
		if err := os.Rename(backup, destination); err != nil {
			t.Error(err)
		}
	}()
	if err := os.Mkdir(destination, 0700); err != nil {
		t.Fatal(err)
	}
	if code := cleanupCall(t, s, job, "cancel-original"); code != 409 {
		t.Fatal(code)
	}
	f.mu.Lock()
	count := f.questionRejects
	f.mu.Unlock()
	if count != 0 {
		t.Fatal("rejected before durable fence")
	}
	if s.Idle() == nil {
		t.Fatal("faulted cleanup allowed lifecycle")
	}
}
func TestCancelledQuestionCleanupOfflineGateAndInvalidReceipt(t *testing.T) {
	for _, invalid := range []bool{false, true} {
		t.Run(fmt.Sprint(invalid), func(t *testing.T) {
			s, f, cfg, job, qid := cancelledQuestionFixture(t)
			f.mu.Lock()
			f.retainQuestionOnReject = true
			f.mu.Unlock()
			if code := cleanupCall(t, s, job, "cancel-original"); code != 409 {
				t.Fatal(code)
			}
			s.Close()
			if lock, err := OfflineIdle(cfg); err == nil {
				lock.Close()
				t.Fatal("offline gate accepted pending cleanup")
			}
			if invalid {
				path := filepath.Join(cfg.StateDir, "jobs", job.ID+".json")
				b, err := os.ReadFile(path)
				if err != nil {
					t.Fatal(err)
				}
				var rec record
				if err := json.Unmarshal(b, &rec); err != nil {
					t.Fatal(err)
				}
				rec.Job.QuestionCleanup[qid].SessionID = "ses_foreign"
				b, _ = json.Marshal(rec)
				if err := os.WriteFile(path, b, 0600); err != nil {
					t.Fatal(err)
				}
				if node, err := New(cfg); err == nil {
					node.(*Server).Close()
					t.Fatal("corrupt cleanup receipt loaded")
				}
				return
			}
			f.mu.Lock()
			f.questions = []json.RawMessage{}
			f.mu.Unlock()
			reopened := startNode(t, cfg)
			if code := cleanupCall(t, reopened, job, "cancel-original"); code != 200 {
				t.Fatal(code)
			}
			reopened.Close()
			lock, err := OfflineIdle(cfg)
			if err != nil {
				t.Fatal(err)
			}
			lock.Close()
		})
	}
}

// Live Idle intentionally refuses a project while its poller owns the mutex.
// Wait for that transient ownership to settle without weakening state checks.
func awaitCleanupIdle(t *testing.T, s *Server) {
	t.Helper()
	deadline := time.Now().Add(time.Second)
	var last error
	for time.Now().Before(deadline) {
		last = s.Idle()
		if last == nil {
			return
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatal(last)
}
func TestCancelledQuestionCleanupAlreadyAbsentNeedsNoReject(t *testing.T) {
	s, f, _, job, _ := cancelledQuestionFixture(t)
	f.mu.Lock()
	old := append([]json.RawMessage(nil), f.questions...)
	f.questions = []json.RawMessage{}
	f.mu.Unlock()
	rec, p := s.lookup(job.ID)
	p.mu.Lock()
	rec.Job.PendingQuestions = old
	if err := s.persist(rec); err != nil {
		t.Fatal(err)
	}
	p.mu.Unlock()
	if code := cleanupCall(t, s, job, "cancel-original"); code != 200 {
		t.Fatal(code)
	}
	rec, p = s.lookup(job.ID)
	p.mu.Lock()
	state := rec.Job.QuestionCleanupState
	receipts := len(rec.Job.QuestionCleanup)
	pending := len(rec.Job.PendingQuestions)
	p.mu.Unlock()
	f.mu.Lock()
	rejects := f.questionRejects
	f.mu.Unlock()
	if state != "cleared" || receipts != 0 || pending != 0 || rejects != 0 {
		t.Fatal("already absent question invented reject or stayed blocked")
	}
	awaitCleanupIdle(t, s)
}
