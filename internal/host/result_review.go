package host

import (
	"encoding/json"
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
	text := "The authorized native execution has a terminal receipt. Review its actual diff, test results and remote branch SHA using the traced native tool evidence below. Continue this same Pi session. Push acceptance alone is not Done. Tool evidence is observed and verified:false, never independent proof. For each evidenceChecks kind diff/tests/remote_sha, cite native evidence sources and use observed only when actual output is available; otherwise use unknown with a reason. tests requires successful recorded exit metadata; remote_sha requires git ls-remote output matching the work branch and SHA. Call awf_finish with this executionRequestId. Use needs_changes if any required evidence is unknown or the execution failed/cancelled. Do not invent evidence, claim independent verification, or start another execution. All Git remains agent-owned.\n" + string(mustJSON(payload))
	s.launch(func() { s.prompt(requestID, id, "architect", text) })
}

var remoteSHAPattern = regexp.MustCompile(`^[a-fA-F0-9]{40}([a-fA-F0-9]{24})?$`)

func observedCheck(t *core.Task, check core.EvidenceCheck) bool {
	if len(check.Sources) == 0 || len(check.Sources) > 100 {
		return false
	}
	found := false
	for _, source := range check.Sources {
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
		if evidence == nil || evidence.Kind != "tool" || evidence.Tool != "bash" || evidence.Status != "completed" || evidence.SessionID != t.Execution.SessionID || evidence.MessageID == "" || evidence.CallID == "" || evidence.Output == "" || evidence.Truncated {
			return false
		}
		var input struct {
			Command string `json:"command"`
		}
		if json.Unmarshal(evidence.Input, &input) != nil || input.Command == "" {
			return false
		}
		var meta struct {
			Exit      *int `json:"exit"`
			ExitCode  *int `json:"exitCode"`
			Truncated bool `json:"truncated"`
		}
		if len(evidence.Metadata) > 0 && json.Unmarshal(evidence.Metadata, &meta) != nil {
			return false
		}
		if meta.Truncated {
			return false
		}
		exit := meta.Exit
		if exit == nil {
			exit = meta.ExitCode
		}
		if exit == nil || *exit != 0 || meta.Exit != nil && meta.ExitCode != nil && *meta.Exit != *meta.ExitCode {
			return false
		}
		command, commandOK := observedCommand(input.Command)
		if !commandOK {
			return false
		}
		switch check.Kind {
		case "diff":
			found = found || ((strings.HasPrefix(command, "git diff ") || strings.HasPrefix(command, "git show ") || command == "git diff" || command == "git show") && strings.Contains(evidence.Output, "diff --git "))
		case "tests":
			for _, test := range []string{"go test", "npm test", "npm run test", "pnpm test", "pnpm run test", "yarn test", "pytest", "cargo test", "node --test", "ctest", "dotnet test"} {
				found = found || command == test || strings.HasPrefix(command, test+" ") || strings.HasPrefix(command, test+":")
			}
		case "remote_sha":
			if !remoteSHAPattern.MatchString(check.RemoteSHA) || !strings.HasPrefix(command, "git ls-remote ") {
				return false
			}
			for _, line := range strings.Split(evidence.Output, "\n") {
				fields := strings.Fields(line)
				if len(fields) == 2 && strings.EqualFold(fields[0], check.RemoteSHA) && fields[1] == "refs/heads/"+t.Branch {
					found = true
				}
			}
		}
	}
	return found
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
			if !observedCheck(t, check) {
				return fail("evidence_unknown", "assessment does not reference sufficient actual native tool output", 409)
			}
		default:
			return fail("invalid_evidence_checks", "status must be observed or unknown", 400)
		}
	}
	return nil
}

// Conservative command attribution, not a shell interpreter or independent
// verifier. Masked exits, pipelines and multiple commands remain unknown.
func observedCommand(command string) (string, bool) {
	command = strings.TrimSpace(strings.ToLower(command))
	if strings.ContainsAny(command, ";|\n\r`") || strings.Contains(command, "$(") || strings.Contains(strings.ReplaceAll(command, "&&", ""), "&") {
		return "", false
	}
	parts := strings.Split(command, "&&")
	for _, prefix := range parts[:len(parts)-1] {
		if !strings.HasPrefix(strings.TrimSpace(prefix), "cd ") {
			return "", false
		}
	}
	return strings.TrimSpace(parts[len(parts)-1]), true
}
