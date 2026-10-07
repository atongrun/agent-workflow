// Package content provides the generic, isolated content-job boundary.
package content

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"time"
)

const (
	MaxBodyBytes     = 131072
	MaxFrameBytes    = 131072
	MaxPayloadBytes  = 65536
	MaxArtifactBytes = 65536
	MaxJSONDepth     = 32
)

var (
	ErrInvalid     = errors.New("invalid_request")
	ErrConflict    = errors.New("request_conflict")
	ErrQueueFull   = errors.New("queue_full")
	ErrNotFound    = errors.New("not_found")
	ErrUnavailable = errors.New("unavailable")
	ErrFence       = errors.New("stale_fence")
)

type Status string

const (
	Queued            Status = "queued"
	Running           Status = "running"
	Cancelling        Status = "cancelling"
	Succeeded         Status = "succeeded"
	Failed            Status = "failed"
	Cancelled         Status = "cancelled"
	NeedsVerification Status = "needs_verification"
)

func (s Status) Terminal() bool {
	return s == Succeeded || s == Failed || s == Cancelled || s == NeedsVerification
}

type Input struct {
	RequestID     string          `json:"requestId"`
	Capability    string          `json:"capability"`
	PayloadSchema string          `json:"payloadSchema"`
	OpaquePayload json.RawMessage `json:"opaquePayload"`
}

type Profile struct {
	ModelRef         string            `json:"modelRef"`
	ResourceVersions map[string]string `json:"resourceVersions"`
	TimeoutSeconds   int               `json:"timeoutSeconds"`
}

type Artifact struct {
	Schema     string `json:"schema"`
	MediaType  string `json:"mediaType"`
	Bytes      int    `json:"bytes"`
	SHA256     string `json:"sha256"`
	DataBase64 string `json:"dataBase64"`
}

type Job struct {
	JobID            string    `json:"jobId"`
	RequestID        string    `json:"requestId"`
	Capability       string    `json:"capability"`
	PayloadSchema    string    `json:"payloadSchema"`
	Status           Status    `json:"status"`
	CreatedAt        string    `json:"createdAt"`
	UpdatedAt        string    `json:"updatedAt"`
	CancelRequested  bool      `json:"cancelRequested"`
	ExecutionID      string    `json:"executionId,omitempty"`
	OwnerEpoch       string    `json:"ownerEpoch,omitempty"`
	NativeSessionRef string    `json:"nativeSessionRef,omitempty"`
	NativeStopReason string    `json:"nativeStopReason,omitempty"`
	ErrorCode        string    `json:"errorCode,omitempty"`
	Result           *Artifact `json:"result,omitempty"`
}

type Page struct {
	Jobs       []Job  `json:"jobs"`
	NextCursor string `json:"nextCursor,omitempty"`
}

type Execute struct {
	Version          int               `json:"version"`
	Type             string            `json:"type"`
	JobID            string            `json:"jobId"`
	ExecutionID      string            `json:"executionId"`
	OwnerEpoch       string            `json:"ownerEpoch"`
	Capability       string            `json:"capability"`
	PayloadSchema    string            `json:"payloadSchema"`
	OpaquePayload    json.RawMessage   `json:"opaquePayload"`
	ModelRef         string            `json:"modelRef"`
	ResourceVersions map[string]string `json:"resourceVersions"`
	DeadlineAt       string            `json:"deadlineAt"`
}

type CancelFrame struct {
	Version     int    `json:"version"`
	Type        string `json:"type"`
	JobID       string `json:"jobId"`
	ExecutionID string `json:"executionId"`
	OwnerEpoch  string `json:"ownerEpoch"`
}

type Event struct {
	Version          int       `json:"version"`
	JobID            string    `json:"jobId"`
	ExecutionID      string    `json:"executionId"`
	OwnerEpoch       string    `json:"ownerEpoch"`
	Sequence         int64     `json:"sequence"`
	Type             string    `json:"type"`
	NativeSessionRef string    `json:"nativeSessionRef,omitempty"`
	Artifact         *Artifact `json:"artifact,omitempty"`
	StopReason       string    `json:"stopReason,omitempty"`
	ErrorCode        string    `json:"errorCode,omitempty"`
}

// Outcome contains independently observed native and process evidence.
// Quiescent means the owned process group is gone, including descendants.
type Outcome struct {
	SessionRef  string
	StopReason  string
	Artifact    *Artifact
	RawArtifact []byte
	ErrorCode   string
	CleanExit   bool
	Quiescent   bool
	NotStarted  bool // Go proved it never called the process runner after cancellation.
}

type ProcessBinding struct {
	PID        int
	StartToken string
	SessionRef string
}

func newID() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		panic(err)
	}
	b[6] = b[6]&15 | 64
	b[8] = b[8]&63 | 128
	s := hex.EncodeToString(b[:])
	return s[:8] + "-" + s[8:12] + "-" + s[12:16] + "-" + s[16:20] + "-" + s[20:]
}

func validID(s string) bool {
	if len(s) != 36 || s[8] != '-' || s[13] != '-' || s[18] != '-' || s[23] != '-' || s[14] != '4' {
		return false
	}
	if s[19] != '8' && s[19] != '9' && s[19] != 'a' && s[19] != 'b' {
		return false
	}
	for i, c := range s {
		if i == 8 || i == 13 || i == 18 || i == 23 {
			continue
		}
		if c < '0' || c > '9' {
			if c < 'a' || c > 'f' {
				return false
			}
		}
	}
	return true
}

func timestamp() string { return time.Now().UTC().Format(time.RFC3339Nano) }
