package host

import (
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"net/http"
	"strings"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
)

func (s *Server) scopedToken(taskID, role string) string {
	h := hmac.New(sha256.New, []byte(s.extensionToken))
	_, _ = h.Write([]byte(taskID + ":" + role))
	return hex.EncodeToString(h.Sum(nil))
}
func (s *Server) internalAuth(h http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		parts := strings.Split(strings.Trim(r.URL.Path, "/"), "/")
		role := r.Header.Get("X-AWF-Role")
		if len(parts) != 4 || (role != "architect" && role != "reviewer") {
			writeError(w, fail("unauthorized", "scoped extension authentication required", 401))
			return
		}
		got := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
		want := s.scopedToken(parts[2], role)
		if !strings.HasPrefix(r.Header.Get("Authorization"), "Bearer ") || subtle.ConstantTimeCompare([]byte(got), []byte(want)) != 1 {
			writeError(w, fail("unauthorized", "invalid scoped extension token", 401))
			return
		}
		h.ServeHTTP(w, r)
	})
}

type extensionInput struct {
	RequestID          string   `json:"requestId"`
	Content            string   `json:"content,omitempty"`
	Verdict            string   `json:"verdict,omitempty"`
	Summary            string   `json:"summary,omitempty"`
	Findings           []string `json:"findings,omitempty"`
	ExecutionRequestID string   `json:"executionRequestId,omitempty"`
}

func (s *Server) internalAction(w http.ResponseWriter, r *http.Request) {
	var in extensionInput
	if err := decode(w, r, &in); err != nil {
		writeError(w, err)
		return
	}
	id, op, role := r.PathValue("id"), r.PathValue("action"), r.Header.Get("X-AWF-Role")
	_, err := s.reserve(in.RequestID, id, "extension/"+op, in, func(st *core.State) error {
		t := st.Tasks[id]
		if t == nil {
			return fail("not_found", "task not found", 404)
		}
		switch op {
		case "context":
		case "plan":
			if role != "architect" {
				return fail("wrong_role", "only architect may submit a plan", 403)
			}
			if executionActive(t) || t.Status == "review" || t.Status == "reporting" || t.Status == "done" {
				return fail("execution_active", "cannot replace a running execution's plan", 409)
			}
			if strings.TrimSpace(in.Content) == "" {
				return fail("invalid_plan", "plan content required", 400)
			}
			revision := 1
			if t.Plan != nil {
				revision = t.Plan.Revision + 1
			}
			t.Plan = &core.Plan{Revision: revision, Content: in.Content, Source: "pi_tool"}
			t.Status = "awaiting_confirmation"
			t.Phase = "architecture"
		case "execute":
			if role != "architect" {
				return fail("wrong_role", "only architect may address execution", 403)
			}
			if t.Execution == nil || !executionActive(t) {
				return fail("user_start_required", "the user must confirm this plan and explicitly start execution", 409)
			}

		case "finish":
			if role != "architect" || t.Settings.Reviewer == "pi" {
				return fail("wrong_role", "same-Pi completion is available only to the task Pi", 403)
			}
			if t.Execution == nil || t.Execution.Status != "completed" || in.ExecutionRequestID != t.Execution.RequestID || t.Status != "reporting" {
				return fail("stale_execution", "finish must reference the current completed execution", 409)
			}
			if in.Verdict != "done" && in.Verdict != "needs_changes" {
				return fail("invalid_verdict", "verdict must be done or needs_changes", 400)
			}
			if strings.TrimSpace(in.Summary) == "" {
				return fail("invalid_summary", "execution summary required", 400)
			}
			if in.Verdict == "done" && len(t.Execution.Evidence) == 0 {
				return fail("evidence_missing", "completion requires native execution evidence", 409)
			}
			result := core.Completion{Verdict: in.Verdict, Summary: in.Summary, Findings: in.Findings, At: time.Now().UTC(), SessionID: t.Sessions["architect"].ID, ExecutionRequestID: t.Execution.RequestID}
			t.Completion = &result
			t.CompletionHistory = append(t.CompletionHistory, result)
			t.Status = in.Verdict
			if in.Verdict == "done" {
				t.Phase = "done"
			}
		case "review":
			if role != "reviewer" {
				return fail("wrong_role", "only the independent reviewer may submit a verdict", 403)
			}
			if t.Execution == nil || t.Execution.Status != "completed" || in.ExecutionRequestID != t.Execution.RequestID {
				return fail("stale_execution", "review must reference the current completed execution", 409)
			}
			if t.Status != "review" {
				return fail("review_closed", "review round is not open", 409)
			}
			if in.Verdict != "approved" && in.Verdict != "needs_changes" {
				return fail("invalid_verdict", "verdict must be approved or needs_changes", 400)
			}
			if strings.TrimSpace(in.Summary) == "" {
				return fail("invalid_review", "review summary required", 400)
			}
			if in.Verdict == "approved" && len(t.Execution.Evidence) == 0 {
				return fail("evidence_missing", "approval requires native execution evidence", 409)
			}
			t.ReviewHistory = append(t.ReviewHistory, core.Review{Round: len(t.ReviewHistory) + 1, Verdict: in.Verdict, Summary: in.Summary, Findings: in.Findings, At: time.Now().UTC(), SessionID: t.Sessions["reviewer"].ID, ExecutionRequestID: t.Execution.RequestID})
			t.Status = "needs_changes"
			if in.Verdict == "approved" {
				t.Status = "done"
				t.Phase = "done"
			}
		default:
			return fail("not_found", "unknown structured extension action", 404)
		}
		core.Changed(st, t)
		return nil
	})
	if err != nil {
		writeError(w, err)
		return
	}
	s.requestDone(in.RequestID, "completed", nil)
	s.response(w, in.RequestID)
}
