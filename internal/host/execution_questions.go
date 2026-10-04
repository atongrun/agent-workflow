package host

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/url"

	"github.com/atongrun/agent-workflow/internal/core"
	"github.com/atongrun/agent-workflow/internal/node"
	"github.com/atongrun/agent-workflow/internal/opencode"
)

type executionQuestionInput struct {
	RequestID          string     `json:"requestId"`
	ExecutionRequestID string     `json:"executionRequestId"`
	JobID              string     `json:"jobId"`
	SessionID          string     `json:"sessionId"`
	Answers            [][]string `json:"answers"`
}
type executionQuestionsView struct {
	TaskID             string              `json:"taskId"`
	JobID              string              `json:"jobId"`
	ExecutionRequestID string              `json:"executionRequestId"`
	SessionID          string              `json:"sessionId"`
	Questions          []opencode.Question `json:"questions"`
}

func questionExecution(t *core.Task, execution, job, session string) *core.Execution {
	if execution == "" || job == "" || session == "" {
		return nil
	}
	matches := func(e *core.Execution) bool {
		return e != nil && e.RequestID == execution && e.JobID == job && e.SessionID == session
	}
	if matches(t.Execution) {
		return t.Execution
	}
	for i := range t.ExecutionHistory {
		if matches(&t.ExecutionHistory[i]) {
			return &t.ExecutionHistory[i]
		}
	}
	return nil
}
func questionNodeQuery(taskID string, e *core.Execution) string {
	return url.Values{"taskId": {taskID}, "executionRequestId": {e.RequestID}, "sessionId": {e.SessionID}}.Encode()
}
func (s *Server) executionQuestions(w http.ResponseWriter, r *http.Request) {
	t, err := s.task(r.PathValue("id"))
	if err != nil {
		writeError(w, err)
		return
	}
	q := r.URL.Query()
	if len(q) != 3 || len(q["executionRequestId"]) != 1 || len(q["jobId"]) != 1 || len(q["sessionId"]) != 1 {
		writeError(w, fail("invalid_query", "executionRequestId, jobId and sessionId are required exactly once", 400))
		return
	}
	e := questionExecution(t, q.Get("executionRequestId"), q.Get("jobId"), q.Get("sessionId"))
	if t.DeletedAt != nil || e == nil || e != t.Execution || !questionHostActive(t) || e.CancelRequested {
		writeError(w, fail("stale_execution", "questions require the current active execution binding", 409))
		return
	}
	var out executionQuestionsView
	_, err = s.nodeCall(r.Context(), executionNodeID(t), "GET", "/v1/jobs/"+url.PathEscape(e.JobID)+"/questions?"+questionNodeQuery(t.ID, e), nil, &out)
	if err != nil {
		writeError(w, fail("question_unavailable", "node could not verify current native questions", 409))
		return
	}
	if out.TaskID != t.ID || out.JobID != e.JobID || out.ExecutionRequestID != e.RequestID || out.SessionID != e.SessionID || out.Questions == nil {
		writeError(w, fail("question_unavailable", "question response binding is invalid", 409))
		return
	}
	for _, question := range out.Questions {
		if question.SessionID != e.SessionID || !opencode.ValidQuestionID(question.ID) || question.Tool == nil || question.Tool.MessageID == "" || question.Tool.CallID == "" {
			writeError(w, fail("question_unavailable", "native question binding is invalid", 409))
			return
		}
	}
	writeJSON(w, 200, out)
}
func (s *Server) executionQuestionReply(w http.ResponseWriter, r *http.Request) {
	if len(r.URL.Query()) != 0 {
		writeError(w, fail("invalid_query", "question replies do not accept query parameters", 400))
		return
	}
	qid := r.PathValue("questionId")
	if !opencode.ValidQuestionID(qid) {
		writeError(w, fail("invalid_question_id", "valid native questionId required", 400))
		return
	}
	var in executionQuestionInput
	if err := decode(w, r, &in); err != nil {
		writeError(w, err)
		return
	}
	id := r.PathValue("id")
	op := "execution/question-reply/" + qid
	duplicate, err := s.reserveRequest(in.RequestID, id, op, in, func(st *core.State, req *core.Request) error {
		t := st.Tasks[id]
		if t == nil {
			return fail("not_found", "task not found", 404)
		}
		e := questionExecution(t, in.ExecutionRequestID, in.JobID, in.SessionID)
		if e == nil || e != t.Execution || !questionHostActive(t) || e.CancelRequested {
			return fail("stale_execution", "question reply requires current task/job/session binding", 409)
		}
		if len(in.Answers) == 0 {
			return fail("invalid_answers", "answers are required", 400)
		}
		return nil
	})
	if err != nil {
		writeError(w, err)
		return
	}
	saved := s.store.Snapshot().Requests[in.RequestID]
	if duplicate && saved.Status == "failed" {
		writeQuestionFailure(w, saved)
		return
	}
	if duplicate && saved.Status == "completed" {
		s.response(w, in.RequestID)
		return
	}
	t, taskErr := s.task(id)
	if taskErr != nil {
		writeError(w, taskErr)
		return
	}
	e := questionExecution(t, in.ExecutionRequestID, in.JobID, in.SessionID)
	if e == nil {
		s.response(w, in.RequestID)
		return
	}
	bound := *t
	bound.Execution = e
	nodeInput := node.QuestionReplyInput{RequestID: in.RequestID, TaskID: id, ExecutionRequestID: in.ExecutionRequestID, SessionID: in.SessionID, Answers: in.Answers}
	var result struct {
		Reply node.QuestionReply `json:"reply"`
	}
	// Historical uncertain retries first reconcile the durable node receipt. A
	// same-ID node POST is receipt-idempotent even if the original call is racing.
	code := 404
	attemptedPost := false
	if duplicate {
		code, err = s.nodeCall(r.Context(), executionNodeID(&bound), "GET", "/v1/jobs/"+url.PathEscape(e.JobID)+"/question-replies/"+url.PathEscape(in.RequestID)+"?"+questionNodeQuery(id, e), nil, &result)
	}
	if !duplicate || code == 404 && t.DeletedAt == nil && e == t.Execution && questionHostActive(t) && !e.CancelRequested {
		if err = s.store.Update(func(st *core.State) error {
			current := st.Tasks[id]
			execution := questionExecution(current, in.ExecutionRequestID, in.JobID, in.SessionID)
			if current.DeletedAt != nil || execution != current.Execution || !questionHostActive(current) || execution.CancelRequested {
				return fail("stale_execution", "execution changed before forwarding reply", 409)
			}
			st.Requests[in.RequestID].Dispatched = true
			return nil
		}); err == nil {
			attemptedPost = true
			code, err = s.nodeCall(r.Context(), executionNodeID(&bound), "POST", "/v1/jobs/"+url.PathEscape(e.JobID)+"/questions/"+qid+"/reply", nodeInput, &result)
		}
	}

	status := "needs_verification"
	var failure *questionFailure
	replyBound := result.Reply.RequestID == in.RequestID && result.Reply.QuestionID == qid && result.Reply.TaskID == id && result.Reply.JobID == in.JobID && result.Reply.ExecutionRequestID == in.ExecutionRequestID && result.Reply.SessionID == in.SessionID && result.Reply.PayloadHash == node.QuestionReplyHash(qid, nodeInput)
	if err == nil && replyBound {
		if result.Reply.Status == "completed" {
			status = "completed"
		}
		if result.Reply.Status == "failed" && (result.Reply.HTTPStatus == 400 || result.Reply.HTTPStatus == 409) {
			failure = &questionFailure{Code: result.Reply.ErrorCode, Message: result.Reply.Error, HTTPStatus: result.Reply.HTTPStatus}
		}
	} else if err != nil && (attemptedPost || !saved.Dispatched) {
		// These explicit node/API rejections precede native answer acceptance.
		// Transport errors, malformed responses and storage failures stay uncertain.
		failure = classifyQuestionFailure(err)
	}
	if failure != nil {
		status = "failed"
	}
	if saveErr := s.store.Update(func(st *core.State) error {
		req := st.Requests[in.RequestID]
		if req.Status == "completed" || req.Status == "failed" && status != "completed" {
			return nil
		}
		req.Status = status
		switch status {
		case "completed":
			req.Result = mustJSON(result.Reply)
			req.Error = ""
		case "failed":
			req.Result = mustJSON(failure)
			req.Error = failure.Message
		default:
			req.Error = "native question reply requires original receipt verification; do not use a new requestId"
		}
		core.Emit(st, id, "execution.question-reply", map[string]any{"requestId": in.RequestID, "status": status})
		return nil
	}); saveErr != nil {
		writeError(w, saveErr)
		return
	}
	saved = s.store.Snapshot().Requests[in.RequestID]
	if saved.Status == "failed" {
		writeQuestionFailure(w, saved)
		return
	}
	s.response(w, in.RequestID)
}

type questionFailure struct {
	Code       string `json:"code"`
	Message    string `json:"message"`
	HTTPStatus int    `json:"httpStatus"`
}

func classifyQuestionFailure(err error) *questionFailure {
	var local *apiError
	if errors.As(err, &local) && local.Status >= 400 && local.Status < 500 {
		return &questionFailure{Code: local.Code, Message: local.Message, HTTPStatus: local.Status}
	}
	var remote *nodeHTTPError
	if !errors.As(err, &remote) {
		return nil
	}
	var envelope struct {
		Error struct {
			Code string `json:"code"`
		}
	}
	if json.Unmarshal([]byte(remote.Body), &envelope) != nil {
		return nil
	}
	switch envelope.Error.Code {
	case "invalid_json", "invalid_request", "invalid_query", "invalid_answers":
		if remote.Status == 400 {
			return &questionFailure{Code: envelope.Error.Code, Message: "node rejected the question reply before answering", HTTPStatus: 400}
		}
	case "stale_execution", "execution_inactive", "question_unavailable", "question_already_answered", "question_limit", "idempotency_conflict":
		if remote.Status == 409 {
			return &questionFailure{Code: envelope.Error.Code, Message: "node rejected the question reply; refresh the current question or original receipt", HTTPStatus: 409}
		}
	case "job_not_found":
		if remote.Status == 404 {
			return &questionFailure{Code: "job_not_found", Message: "recorded node job was not found", HTTPStatus: 404}
		}
	}
	return nil
}
func writeQuestionFailure(w http.ResponseWriter, req *core.Request) {
	var failure questionFailure
	if json.Unmarshal(req.Result, &failure) != nil || failure.HTTPStatus < 400 || failure.HTTPStatus >= 500 {
		writeError(w, fail("question_rejected", "question reply was rejected", 409))
		return
	}
	writeError(w, fail(failure.Code, failure.Message, failure.HTTPStatus))
}

func questionHostActive(t *core.Task) bool {
	if t.DeletedAt != nil || t.Execution == nil {
		return false
	}
	switch t.Execution.Status {
	case "running", "uncertain", "dispatching":
		return true
	}
	return false
}
