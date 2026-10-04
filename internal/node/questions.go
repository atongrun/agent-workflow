package node

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"regexp"
	"time"

	"github.com/atongrun/agent-workflow/internal/opencode"
)

type QuestionReplyInput struct {
	RequestID          string     `json:"requestId"`
	TaskID             string     `json:"taskId"`
	ExecutionRequestID string     `json:"executionRequestId"`
	SessionID          string     `json:"sessionId"`
	Answers            [][]string `json:"answers"`
}
type QuestionReply struct {
	PayloadHash        string    `json:"payloadHash"`
	RequestID          string    `json:"requestId"`
	QuestionID         string    `json:"questionId"`
	TaskID             string    `json:"taskId"`
	JobID              string    `json:"jobId"`
	ExecutionRequestID string    `json:"executionRequestId"`
	SessionID          string    `json:"sessionId"`
	Status             string    `json:"status"`
	Error              string    `json:"error,omitempty"`
	ErrorCode          string    `json:"errorCode,omitempty"`
	HTTPStatus         int       `json:"httpStatus,omitempty"`
	CreatedAt          time.Time `json:"createdAt"`
}

// Hash is persisted independently of the public receipt; answers are not copied
// into a second conversation. A dispatching receipt after crash stays uncertain.
type questionReceipt struct {
	Reply QuestionReply `json:"reply"`
	Hash  string        `json:"hash"`
}

var questionHashPattern = regexp.MustCompile(`^[a-f0-9]{64}$`)
var questionRequestPattern = regexp.MustCompile(`^[A-Za-z0-9._:-]{1,128}$`)

// QuestionReplyHash binds a reconciled receipt to the original typed payload.
func QuestionReplyHash(id string, in QuestionReplyInput) string {
	b, _ := json.Marshal(struct {
		QuestionID string
		Input      QuestionReplyInput
	}{id, in})
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:])
}
func questionScope(rec *record, task, execution, session string) bool {
	return task != "" && execution != "" && session != "" && rec.Job.TaskID == task && rec.Job.RequestID == execution && rec.Job.SessionID == session
}
func questionReadScope(w http.ResponseWriter, r *http.Request, rec *record) bool {
	q := r.URL.Query()
	if len(q) != 3 || len(q["taskId"]) != 1 || len(q["executionRequestId"]) != 1 || len(q["sessionId"]) != 1 {
		writeError(w, 400, "invalid_query", "taskId, executionRequestId and sessionId are required exactly once")
		return false
	}
	if !questionScope(rec, q.Get("taskId"), q.Get("executionRequestId"), q.Get("sessionId")) {
		writeError(w, 409, "stale_execution", "task/job/session binding does not match")
		return false
	}
	return true
}

// Caller holds project mutex. Native question tool/message must belong to the
// recorded user turn, not merely a reused native session or another job.
func (s *Server) boundQuestions(r *http.Request, p *project, rec *record) ([]opencode.Question, error) {
	session, err := s.native.Session(r.Context(), p.workspace, rec.Job.SessionID)
	if err != nil {
		return nil, err
	}
	if session.ID != rec.Job.SessionID || !sameWorkspace(session.Directory, p.workspace) {
		return nil, errQuestionBinding
	}
	messages, err := s.native.Messages(r.Context(), p.workspace, rec.Job.SessionID)
	if err != nil {
		return nil, err
	}
	raw, err := s.native.PendingQuestions(r.Context(), p.workspace)
	if err != nil {
		return nil, err
	}
	user := false
	for _, m := range messages {
		if m.Info.ID == rec.Job.MessageID && m.Info.SessionID == rec.Job.SessionID && m.Info.Role == "user" {
			user = true
		}
	}
	if !user {
		return nil, errQuestionBinding
	}
	out := []opencode.Question{}
	for _, v := range raw {
		var q opencode.Question
		if json.Unmarshal(v, &q) != nil || !opencode.ValidQuestionID(q.ID) || q.SessionID != rec.Job.SessionID || q.Tool == nil || q.Tool.MessageID == "" || q.Tool.CallID == "" || len(q.Questions) == 0 {
			continue
		}
		found := false
		for _, m := range messages {
			if m.Info.ID != q.Tool.MessageID || m.Info.SessionID != rec.Job.SessionID || m.Info.ParentID != rec.Job.MessageID || m.Info.Role != "assistant" {
				continue
			}
			for _, part := range m.Parts {
				if part.Type == "tool" && part.ID != "" && part.SessionID == rec.Job.SessionID && part.MessageID == m.Info.ID && part.Tool == "question" && part.CallID == q.Tool.CallID && (part.State.Status == "running" || part.State.Status == "pending") {
					found = true
				}
			}
		}
		if found {
			out = append(out, q)
		}
	}
	return out, nil
}

var errQuestionBinding = &questionBindingError{}

type questionBindingError struct{}

func (*questionBindingError) Error() string { return "native question turn binding is unavailable" }
func questionAnswerValid(q opencode.Question, answers [][]string) bool {
	if len(answers) != len(q.Questions) {
		return false
	}
	for i, a := range answers {
		info := q.Questions[i]
		if len(a) == 0 || !info.Multiple && len(a) != 1 || len(a) > 64 {
			return false
		}
		seen := map[string]bool{}
		for _, v := range a {
			if len(v) == 0 || len(v) > 8192 || seen[v] {
				return false
			}
			seen[v] = true
			if info.Custom != nil && !*info.Custom {
				found := false
				for _, o := range info.Options {
					found = found || o.Label == v
				}
				if !found {
					return false
				}
			}
		}
	}
	return true
}
func (s *Server) jobQuestions(w http.ResponseWriter, r *http.Request, id string) {
	rec, p := s.lookup(id)
	if rec == nil {
		writeError(w, 404, "job_not_found", "job not found")
		return
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	if !questionReadScope(w, r, rec) {
		return
	}
	if !s.questionJobActive(p, rec) {
		writeError(w, 409, "execution_inactive", "questions require the current active job")
		return
	}
	if s.fault() != nil {
		writeError(w, 503, "storage_unavailable", "node storage requires repair")
		return
	}
	questions, err := s.boundQuestions(r, p, rec)
	if err != nil {
		writeError(w, 409, "question_unavailable", "native question binding could not be verified")
		return
	}
	writeJSON(w, 200, map[string]any{"taskId": rec.Job.TaskID, "jobId": rec.Job.ID, "executionRequestId": rec.Job.RequestID, "sessionId": rec.Job.SessionID, "questions": questions})
}
func (s *Server) questionReceipt(w http.ResponseWriter, r *http.Request, id, requestID string) {
	rec, p := s.lookup(id)
	if rec == nil {
		writeError(w, 404, "job_not_found", "job not found")
		return
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	if !questionReadScope(w, r, rec) {
		return
	}
	receipt := rec.QuestionReplies[requestID]
	if receipt == nil {
		writeError(w, 404, "request_not_found", "question receipt not found")
		return
	}
	writeJSON(w, 200, map[string]any{"reply": receipt.Reply})
}
func (s *Server) replyQuestion(w http.ResponseWriter, r *http.Request, id, qid string) {
	if len(r.URL.Query()) != 0 {
		writeError(w, 400, "invalid_query", "question replies do not accept query parameters")
		return
	}
	var in QuestionReplyInput
	if !decode(w, r, &in) {
		return
	}
	if !questionRequestPattern.MatchString(in.RequestID) || !opencode.ValidQuestionID(qid) {
		writeError(w, 400, "invalid_request", "safe requestId and native questionId required")
		return
	}
	rec, p := s.lookup(id)
	if rec == nil {
		writeError(w, 404, "job_not_found", "job not found")
		return
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	if !questionScope(rec, in.TaskID, in.ExecutionRequestID, in.SessionID) {
		writeError(w, 409, "stale_execution", "task/job/session binding does not match")
		return
	}
	hash := QuestionReplyHash(qid, in)
	if old := rec.QuestionReplies[in.RequestID]; old != nil {
		if old.Hash != hash {
			writeError(w, 409, "idempotency_conflict", "requestId already has different question or answers")
			return
		}
		writeJSON(w, 200, map[string]any{"reply": old.Reply})
		return
	}
	if s.fault() != nil {
		writeError(w, 503, "storage_unavailable", "node storage requires repair")
		return
	}
	if !s.questionJobActive(p, rec) {
		writeError(w, 409, "execution_inactive", "questions require the current active job")
		return
	}
	for _, receipt := range rec.QuestionReplies {
		if receipt.Reply.QuestionID == qid {
			writeError(w, 409, "question_already_answered", "inspect the original reply receipt; native answers are never resent")
			return
		}
	}
	if len(rec.QuestionReplies) >= 128 {
		writeError(w, 409, "question_limit", "question receipt limit reached")
		return
	}
	questions, err := s.boundQuestions(r, p, rec)
	if err != nil {
		writeError(w, 409, "question_unavailable", "native question binding could not be verified")
		return
	}
	var q *opencode.Question
	for i := range questions {
		if questions[i].ID == qid {
			if q != nil {
				writeError(w, 409, "question_unavailable", "ambiguous native question identity")
				return
			}
			q = &questions[i]
		}
	}
	if q == nil {
		writeError(w, 409, "question_unavailable", "question is not pending for this recorded turn")
		return
	}
	if !questionAnswerValid(*q, in.Answers) {
		writeError(w, 400, "invalid_answers", "answers must match question count and allowed choices")
		return
	}
	if rec.QuestionReplies == nil {
		rec.QuestionReplies = map[string]*questionReceipt{}
	}
	receipt := &questionReceipt{Hash: hash, Reply: QuestionReply{PayloadHash: hash, RequestID: in.RequestID, QuestionID: qid, TaskID: in.TaskID, JobID: id, ExecutionRequestID: in.ExecutionRequestID, SessionID: in.SessionID, Status: "dispatching", CreatedAt: time.Now().UTC()}}
	rec.QuestionReplies[in.RequestID] = receipt
	if s.persist(rec) != nil {
		writeError(w, 503, "storage_unavailable", "question dispatch receipt could not be persisted")
		return
	}
	// Never retry this native mutation after a timeout, crash, or lost ACK.
	err = s.native.ReplyQuestion(r.Context(), p.workspace, qid, in.Answers)
	receipt.Reply.Status = "completed"
	if err != nil {
		receipt.Reply.Status = "needs_verification"
		receipt.Reply.Error = "native reply outcome is unknown; do not resend"
		var nativeError *opencode.HTTPError
		if errors.As(err, &nativeError) && (nativeError.StatusCode == 400 || nativeError.StatusCode == 404) {
			receipt.Reply.Status = "failed"
			receipt.Reply.HTTPStatus = 400
			receipt.Reply.ErrorCode = "invalid_answers"
			receipt.Reply.Error = "native server rejected the question reply"
			if nativeError.StatusCode == 404 {
				receipt.Reply.HTTPStatus = 409
				receipt.Reply.ErrorCode = "question_expired"
				receipt.Reply.Error = "native question expired before reply; no answer was accepted"
			}
		}
	}
	if s.persist(rec) != nil {
		receipt.Reply.Status = "needs_verification"
		receipt.Reply.HTTPStatus = 0
		receipt.Reply.ErrorCode = ""
		receipt.Reply.Error = "question outcome was not durably confirmed; do not resend"
		writeError(w, 503, "storage_unavailable", "question outcome could not be persisted; inspect original receipt")
		return
	}
	writeJSON(w, 202, map[string]any{"reply": receipt.Reply})
	s.wake(p)
}

func (s *Server) questionJobActive(p *project, rec *record) bool {
	if rec.Job.Status != "running" && rec.Job.Status != "uncertain" {
		return false
	}
	if rec.Job.SubmissionState != "dispatching" && rec.Job.SubmissionState != "submitted" {
		return false
	}
	return !rec.Job.CancelRequested && s.next(p) == rec
}
func validQuestionReceipt(receipt *questionReceipt) bool {
	return receipt != nil && opencode.ValidQuestionID(receipt.Reply.QuestionID) && questionHashPattern.MatchString(receipt.Hash) && receipt.Reply.PayloadHash == receipt.Hash
}
