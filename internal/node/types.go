// Package node accepts durable execution jobs and adapts them to native OpenCode
// sessions. A completed job is an observed native turn, never a review verdict.
package node

import (
	"encoding/json"
	"github.com/atongrun/agent-workflow/internal/opencode"
	"net/http"
	"time"
)

type Config struct {
	OpenCodeModel    *opencode.ModelSelection `json:"openCodeModel,omitempty"`
	ListenAddress    string                   `json:"listenAddress"`
	AllowedSourceIPs []string                 `json:"allowedSourceIPs,omitempty"` // Empty permits loopback only; a list replaces that default.
	Token            string                   `json:"token"`
	StateDir         string                   `json:"stateDir"`
	Projects         map[string]string        `json:"projects"`
	OpenCodeURL      string                   `json:"openCodeUrl"`
	OpenCodeUsername string                   `json:"openCodeUsername,omitempty"`
	OpenCodePassword string                   `json:"openCodePassword,omitempty"`
	HTTPClient       *http.Client             `json:"-"`
	PollInterval     time.Duration            `json:"-"`
}

type JobRequest struct {
	RequestID      string `json:"requestId"`
	TaskID         string `json:"taskId"`
	ProjectID      string `json:"projectId"`
	Repository     string `json:"repository"`
	Branch         string `json:"branch"`
	Plan           string `json:"plan"`
	Prompt         string `json:"prompt"`
	TimeoutSeconds int    `json:"timeoutSeconds"`
	SessionID      string `json:"sessionId,omitempty"`
}

type Evidence struct {
	Kind      string          `json:"kind"`
	Source    string          `json:"source"`
	Content   string          `json:"content"`
	Tool      string          `json:"tool"`
	Status    string          `json:"status"`
	CallID    string          `json:"callId"`
	MessageID string          `json:"messageId"`
	Input     json.RawMessage `json:"input,omitempty"`
	Output    string          `json:"output,omitempty"`
	Error     string          `json:"error,omitempty"`
	Metadata  json.RawMessage `json:"metadata,omitempty"`
	Verified  bool            `json:"verified"`
}

type Job struct {
	QuestionCleanupState string                      `json:"questionCleanupState,omitempty"`
	QuestionCleanup      map[string]*QuestionCleanup `json:"questionCleanup,omitempty"`
	Model                *opencode.ModelSelection    `json:"model,omitempty"`
	ID                   string                      `json:"id"`
	RequestID            string                      `json:"requestId"`
	TaskID               string                      `json:"taskId"`
	ProjectID            string                      `json:"projectId"`
	Repository           string                      `json:"repository"`
	Branch               string                      `json:"branch"`
	Workspace            string                      `json:"workspace"`
	SessionID            string                      `json:"sessionId,omitempty"`
	MessageID            string                      `json:"messageId"`
	Status               string                      `json:"status"`
	SubmissionState      string                      `json:"submissionState"`
	NativeStatus         string                      `json:"nativeStatus,omitempty"`
	NativeError          string                      `json:"nativeError,omitempty"`
	PendingPermissions   []json.RawMessage           `json:"pendingPermissions,omitempty"`
	PendingQuestions     []json.RawMessage           `json:"pendingQuestions,omitempty"`
	CreatedAt            time.Time                   `json:"createdAt"`
	UpdatedAt            time.Time                   `json:"updatedAt"`
	StartedAt            *time.Time                  `json:"startedAt,omitempty"`
	CompletedAt          *time.Time                  `json:"completedAt,omitempty"`
	ExecutionSeconds     float64                     `json:"executionSeconds"`
	TimeoutSeconds       int                         `json:"timeoutSeconds"`
	Summary              string                      `json:"summary,omitempty"`
	Evidence             []Evidence                  `json:"evidence"`
	Error                string                      `json:"error,omitempty"`
	CancelRequested      bool                        `json:"cancelRequested"`
	AbortConfirmed       bool                        `json:"abortConfirmed"`
	TimedOut             bool                        `json:"timedOut"`
}

type record struct {
	QuestionReplies map[string]*questionReceipt `json:"questionReplies,omitempty"`
	Version         int                         `json:"version"`
	Job             Job                         `json:"job"`
	Request         JobRequest                  `json:"request"`
	Fingerprint     string                      `json:"fingerprint"`
	SessionTitle    string                      `json:"sessionTitle"`
	CancelRequestID string                      `json:"cancelRequestId,omitempty"`
	CancelPhase     string                      `json:"cancelPhase,omitempty"`
	// Accounting deliberately does not carry a wall-clock sample across restarts.
	HadWait  bool `json:"hadWait,omitempty"`
	lastBusy time.Time
}

func terminal(status string) bool {
	return status == "completed" || status == "failed" || status == "cancelled"
}
