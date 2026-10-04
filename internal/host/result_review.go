package host

import (
	"net/http"
	"regexp"
	"strings"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
)

func resultTerminal(t *core.Task) bool {
	return t.Execution != nil && (t.Execution.Status == "completed" || t.Execution.Status == "failed" || t.Execution.Status == "cancelled")
}
func unknownEvidenceChecks() []core.EvidenceCheck {
	return []core.EvidenceCheck{{Kind: "diff", Status: "unknown", Sources: []string{}, Notes: "No sufficient traced native output has been assessed"}, {Kind: "tests", Status: "unknown", Sources: []string{}, Notes: "No sufficient traced native output has been assessed"}, {Kind: "remote_sha", Status: "unknown", Sources: []string{}, Notes: "No sufficient traced native output has been assessed"}}
}
func newResultReview(t *core.Task) *core.ResultReview {
	sessionID := ""
	if ref := t.Sessions["architect"]; ref != nil {
		sessionID = ref.ID
	}
	return &core.ResultReview{RequestID: "result-" + t.Execution.RequestID, ExecutionRequestID: t.Execution.RequestID, SessionID: sessionID, NativeSessionID: t.Execution.SessionID, Status: "queued", EvidenceChecks: unknownEvidenceChecks()}
}

// This scheduler only delivers an existing native terminal result to the same
// Pi conversation. It never authorizes another executor run or retries a prompt
// that crossed the JSONL write fence.
func (s *Server) watchExecutionResults() {
	ticker := time.NewTicker(300 * time.Millisecond)
	defer ticker.Stop()
	for {
		for id, t := range s.store.Snapshot().Tasks {
			if t.DeletedAt == nil && resultTerminal(t) && (t.Status == "reporting" || t.Status == "review") {
				s.beginExecutionSummary(id)
			}
		}
		select {
		case <-s.stop:
			return
		case <-ticker.C:
		}
	}
}
func (s *Server) beginExecutionSummary(id string) {
	t, err := s.task(id)
	if err != nil || t.DeletedAt != nil || !resultTerminal(t) || (t.Status != "reporting" && t.Status != "review") {
		return
	}
	if t.Settings.Reviewer == "pi" {
		if t.Execution.Status == "completed" {
			s.beginAutomaticReview(id)
		}
		return
	}
	requestID := "result-" + t.Execution.RequestID
	// Queue even while busy. A restart can safely resume a queued, undispatched
	// receipt; ambiguous/already-sent receipts remain manual verification gates.
	_, err = s.reserveRequest(requestID, id, "execution_result", map[string]string{"executionRequestId": t.Execution.RequestID}, func(st *core.State, req *core.Request) error {
		cur := st.Tasks[id]
		if cur.LifecycleRevision != t.LifecycleRevision || cur.Execution == nil || cur.Execution.RequestID != t.Execution.RequestID || !resultTerminal(cur) || cur.Status != "reporting" {
			return fail("stale_execution", "terminal execution changed", 409)
		}
		if cur.Sessions["architect"] == nil {
			return fail("session_unavailable", "original Pi session missing", 409)
		}
		if cur.Execution.ResultReview == nil {
			cur.Execution.ResultReview = newResultReview(cur)
		}
		req.Status = "queued"
		req.Role = "architect"
		req.SessionID = cur.Execution.ResultReview.SessionID
		core.Changed(st, cur)
		return nil
	})
	if err != nil {
		return
	}
	dispatch := false
	err = s.store.Update(func(st *core.State) error {
		cur := st.Tasks[id]
		req := st.Requests[requestID]
		if cur.DeletedAt != nil || cur.Execution == nil || cur.Execution.RequestID != t.Execution.RequestID || cur.Status != "reporting" || req == nil {
			return nil
		}
		review := cur.Execution.ResultReview
		if review == nil {
			review = newResultReview(cur)
			cur.Execution.ResultReview = review
		}
		switch req.Status {
		case "queued":
			if req.Dispatched {
				req.Status = "needs_verification"
				review.Status = "needs_verification"
				review.Error = "sent result cannot be requeued; inspect the original receipt"
				core.Changed(st, cur)
				return nil
			}
			if remainingSeconds(cur) <= 0 {
				req.Status = "failed"
				req.Error = "budget exhausted before same-Pi result review"
				review.Status = "blocked"
				review.Error = req.Error
				cur.Status = "blocked"
				core.Changed(st, cur)
				return nil
			}
			if !taskPiIdle(cur) {
				return nil
			}
			ref := cur.Sessions["architect"]
			if ref == nil || ref.ID != review.SessionID {
				req.Status = "needs_verification"
				review.Status = "needs_verification"
				review.Error = "original Pi session binding changed"
				core.Changed(st, cur)
				return nil
			}
			req.Status = "accepted"
			req.SessionID = ref.ID
			req.ProcessID = ""
			ref.PendingCommands = append(ref.PendingCommands, requestID)
			refreshPending(ref)
			review.Status = "dispatching"
			dispatch = true
			core.Changed(st, cur)
		case "accepted_native", "settled":
			if review.Status != "awaiting_verdict" {
				review.Status = "awaiting_verdict"
				core.Changed(st, cur)
			}
		case "needs_verification", "failed", "cancelled":
			if review.Status != "needs_verification" {
				review.Status = "needs_verification"
				review.Error = "inspect the original Pi result receipt; automatic replay is disabled"
				core.Changed(st, cur)
			}
		}
		return nil
	})
	if err != nil || !dispatch {
		return
	}
	latest, _ := s.task(id)
	payload := map[string]any{"task": latest.Title, "goal": latest.Goal, "acceptanceCriteria": latest.AcceptanceCriteria, "plan": latest.Plan, "execution": latest.Execution, "branch": latest.Branch}
	text := "The authorized native execution has a terminal receipt. Review its actual diff, test results and remote branch SHA using the traced native tool evidence below. Continue this same Pi session. Push acceptance alone is not Done. Tool evidence is observed and verified:false, never independent proof. For each evidenceChecks kind diff/tests/remote_sha, cite the exact native evidence source values. observed is your assessment of cited native receipts, not machine verification or a successful exit. You must judge the actual changes, test outcomes and remote branch/SHA correspondence yourself. The Host checks schema, receipt identity and legal transitions; it does not interpret shell commands or output. Empty/truncated output, missing or failed exit data and masked exits require your explicit assessment of uncertainty; use unknown with a reason when evidence is insufficient. A native turn ending or a tool exit zero is not acceptance. Call awf_finish with this executionRequestId. Use needs_changes if any required evidence is unknown or the execution failed/cancelled. Do not invent evidence, claim independent verification, or start another execution. All Git remains agent-owned.\n" + string(mustJSON(payload))
	s.launch(func() { s.prompt(requestID, id, "architect", text) })
}

var remoteSHAPattern = regexp.MustCompile(`^[a-fA-F0-9]{40}([a-fA-F0-9]{24})?$`)

// observedCheck validates receipt identity and reference availability only.
// Pi judges the contents; a referenced tool's exit is not task approval.
func observedCheck(t *core.Task, check core.EvidenceCheck) bool {
	if t.Execution.SessionID == "" || len(check.Sources) == 0 || len(check.Sources) > 100 {
		return false
	}
	seen := map[string]bool{}
	for _, source := range check.Sources {
		if source == "" || seen[source] {
			return false
		}
		seen[source] = true
		var evidence *core.Evidence
		for i := range t.Execution.Evidence {
			e := &t.Execution.Evidence[i]
			if e.Source == source {
				if evidence != nil {
					return false
				}
				evidence = e
			}
		}
		if evidence == nil || evidence.Kind != "tool" || evidence.Tool == "" || evidence.Status != "completed" || evidence.SessionID != t.Execution.SessionID || evidence.MessageID == "" || evidence.CallID == "" {
			return false
		}
	}
	return true
}
func validateEvidenceChecks(t *core.Task, checks []core.EvidenceCheck, done bool) error {
	if len(checks) == 0 && !done {
		return nil
	}
	if len(checks) != 3 {
		return fail("evidence_unknown", "diff, tests and remote_sha assessments are required", http.StatusConflict)
	}
	seen := map[string]bool{}
	for _, check := range checks {
		if check.Kind != "diff" && check.Kind != "tests" && check.Kind != "remote_sha" || seen[check.Kind] {
			return fail("invalid_evidence_checks", "each known evidence kind must appear once", 400)
		}
		seen[check.Kind] = true
		switch check.Status {
		case "unknown":
			if done || strings.TrimSpace(check.Notes) == "" || len(check.Sources) != 0 || check.RemoteSHA != "" {
				return fail("evidence_unknown", "unknown evidence requires a reason and cannot authorize Done", 409)
			}
		case "observed":
			if check.Kind == "remote_sha" && !remoteSHAPattern.MatchString(check.RemoteSHA) {
				return fail("invalid_evidence_checks", "remoteSha must be a 40 or 64 character hexadecimal assessment value", 400)
			}
			if !observedCheck(t, check) {
				return fail("evidence_unknown", "assessment must reference unique completed native tool receipts from this execution session", 409)
			}
		default:
			return fail("invalid_evidence_checks", "status must be observed or unknown", 400)
		}
	}
	return nil
}
