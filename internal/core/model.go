package core

import (
	"encoding/json"
	"time"
)

type Settings struct {
	Architect     string `json:"architect"`
	Executor      string `json:"executor"`
	Reviewer      string `json:"reviewer"`
	DefaultBranch string `json:"defaultBranch"`
	BranchPrefix  string `json:"branchPrefix"`
	TaskMinutes   int    `json:"taskMinutes"`
	MaxReworks    int    `json:"maxReworks"`
	PlanMinutes   int    `json:"planMinutes"`
}

func Defaults() Settings { return Settings{"pi", "opencode", "disabled", "main", "awf/", 60, 2, 180} }

type Session struct {
	Settled         int64                `json:"settled"`
	DialogDeadlines map[string]time.Time `json:"dialogDeadlines,omitempty"`
	Streaming       bool                 `json:"streaming"`
	Compacting      bool                 `json:"compacting"`
	ProcessID       string               `json:"processId,omitempty"`
	PendingCommands []string             `json:"pendingCommands,omitempty"`
	NativeQueued    int                  `json:"nativeQueued"`
	AwaitingStart   bool                 `json:"awaitingStart"`
	Pending         bool                 `json:"pending"`
	ID              string               `json:"id"`
	File            string               `json:"file,omitempty"`
	Available       bool                 `json:"available"`
	Busy            bool                 `json:"busy"`
	PendingUI       []json.RawMessage    `json:"pendingUi"`
	Persisted       bool                 `json:"persisted"`
}
type Plan struct {
	Revision    int        `json:"revision"`
	Content     string     `json:"content"`
	ConfirmedAt *time.Time `json:"confirmedAt,omitempty"`
	Source      string     `json:"source"`
}
type Budget struct {
	TaskSeconds int64      `json:"taskSeconds"`
	PlanSeconds int64      `json:"planSeconds"`
	Reworks     int        `json:"reworks"`
	ActiveSince *time.Time `json:"activeSince,omitempty"`
}
type Evidence struct {
	Kind     string `json:"kind"`
	Content  string `json:"content"`
	Source   string `json:"source"`
	Verified bool   `json:"verified"`
}
type ExecutionTarget struct {
	Revision     int    `json:"revision"`
	ProjectID    string `json:"projectId"`
	NodeID       string `json:"nodeId"`
	Repository   string `json:"repository"`
	RepositoryID string `json:"repositoryId,omitempty"`
}

type Execution struct {
	Target             *ExecutionTarget  `json:"target,omitempty"`
	PendingPermissions []json.RawMessage `json:"pendingPermissions,omitempty"`
	PendingQuestions   []json.RawMessage `json:"pendingQuestions,omitempty"`
	DispatchAttempted  bool              `json:"dispatchAttempted"`
	TimeoutSeconds     int               `json:"timeoutSeconds"`
	OriginalSessionID  string            `json:"originalSessionId,omitempty"`
	AccountedSeconds   int64             `json:"accountedSeconds"`
	RequestID          string            `json:"requestId"`
	JobID              string            `json:"jobId"`
	SessionID          string            `json:"sessionId,omitempty"`
	Status             string            `json:"status"`
	Summary            string            `json:"summary,omitempty"`
	Evidence           []Evidence        `json:"evidence"`
	Error              string            `json:"error,omitempty"`
	StartedAt          *time.Time        `json:"startedAt,omitempty"`
	FinishedAt         *time.Time        `json:"finishedAt,omitempty"`
	CancelRequested    bool              `json:"cancelRequested"`
}
type Review struct {
	Round              int       `json:"round"`
	Verdict            string    `json:"verdict"`
	Summary            string    `json:"summary"`
	Findings           []string  `json:"findings"`
	At                 time.Time `json:"at"`
	SessionID          string    `json:"sessionId"`
	ExecutionRequestID string    `json:"executionRequestId"`
}
type Completion struct {
	Verdict            string    `json:"verdict"`
	Summary            string    `json:"summary"`
	Findings           []string  `json:"findings"`
	At                 time.Time `json:"at"`
	SessionID          string    `json:"sessionId"`
	ExecutionRequestID string    `json:"executionRequestId"`
}

// RestrictedPlanning keeps model-only planning separate from execution workspaces.
const RestrictedPlanning = "restricted"

type Task struct {
	LifecycleRevision  int                 `json:"lifecycleRevision,omitempty"`
	DeletedAt          *time.Time          `json:"deletedAt,omitempty"`
	PlanningProfile    string              `json:"planningProfile,omitempty"`
	TargetRevision     int                 `json:"targetRevision"`
	RepositoryID       string              `json:"repositoryId,omitempty"`
	Completion         *Completion         `json:"completion,omitempty"`
	CompletionHistory  []Completion        `json:"completionHistory"`
	PlanID             string              `json:"planId"`
	ID                 string              `json:"id"`
	Title              string              `json:"title"`
	ProjectID          string              `json:"projectId"`
	Repository         string              `json:"repository"`
	Goal               string              `json:"goal"`
	AcceptanceCriteria string              `json:"acceptanceCriteria"`
	NodeID             string              `json:"nodeId"`
	Branch             string              `json:"branch"`
	Status             string              `json:"status"`
	Phase              string              `json:"phase"`
	CreatedAt          time.Time           `json:"createdAt"`
	UpdatedAt          time.Time           `json:"updatedAt"`
	Settings           Settings            `json:"settings"`
	Plan               *Plan               `json:"plan,omitempty"`
	Execution          *Execution          `json:"execution,omitempty"`
	ExecutionHistory   []Execution         `json:"executionHistory"`
	ReviewHistory      []Review            `json:"reviewHistory"`
	Sessions           map[string]*Session `json:"sessions"`
	Budget             Budget              `json:"budget"`
	LastError          string              `json:"lastError,omitempty"`
	GitMerged          *bool               `json:"gitMerged"`
}
type Request struct {
	SessionID  string          `json:"sessionId,omitempty"`
	ProcessID  string          `json:"processId,omitempty"`
	Dispatched bool            `json:"dispatched,omitempty"`
	Result     json.RawMessage `json:"result,omitempty"`
	Role       string          `json:"role,omitempty"`
	ID         string          `json:"id"`
	TaskID     string          `json:"taskId"`
	Operation  string          `json:"operation"`
	Hash       string          `json:"hash"`
	Status     string          `json:"status"`
	Error      string          `json:"error,omitempty"`
	CreatedAt  time.Time       `json:"createdAt"`
}
type Event struct {
	ID     int64           `json:"id"`
	Type   string          `json:"type"`
	TaskID string          `json:"taskId"`
	Time   time.Time       `json:"time"`
	Data   json.RawMessage `json:"data"`
}
type State struct {
	Version  int                 `json:"version"`
	Settings Settings            `json:"settings"`
	Tasks    map[string]*Task    `json:"tasks"`
	Requests map[string]*Request `json:"requests"`
	Events   []Event             `json:"events"`
	Sequence int64               `json:"sequence"`
}
