package durablebridge

import "encoding/json"

// Generic PRIVATE wire v1 supplied by the parent. Business payload/result
// schemas remain PRIVATE-owned.
const (
	ProtocolVersion       = 1
	DurableVersion        = "1.0.4"
	PublicPrefix          = "/v1/content"
	OwnerHeader           = "X-AWF-Owner"
	MaxRequestBytes       = 128 * 1024
	MaxWorkerRequestBytes = MaxRequestBytes
	MaxInputBytes         = 64 * 1024
	MaxResponseBytes      = 512 * 1024
	MaxResultBytes        = 64 * 1024
	MaxCursorBytes        = 2048
	MaxNativeID           = uint64(1<<53 - 1)
	DefaultPageLimit      = 20
	MaxPageLimit          = 50
)

type SubmitInput struct {
	Version       int             `json:"version"`
	RequestID     string          `json:"requestId"`
	Capability    string          `json:"capability"`
	PayloadSchema string          `json:"payloadSchema"`
	OpaquePayload json.RawMessage `json:"opaquePayload"`
}

// Submit is constructed only by the authenticated Go boundary.
type Submit struct {
	SubmitInput
	Owner       string `json:"owner"`
	Fingerprint string `json:"fingerprint"`
}

type cancelInput struct {
	Version int    `json:"version"`
	Owner   string `json:"owner"`
}

// Summary deliberately has no input, result, prompt, model configuration,
// task/checkpoint detail or transcript. PRIVATE must enforce the same scope.
type Summary struct {
	Version        int     `json:"version"`
	RequestID      string  `json:"requestId"`
	ConversationID uint64  `json:"conversationId"`
	SubmissionID   *uint64 `json:"submissionId,omitempty"`
	Status         string  `json:"status"`
	AbortRequested *bool   `json:"abortRequested"`
	Reason         string  `json:"reason,omitempty"`
	Detail         *string `json:"detail,omitempty"`
}

type Receipt struct {
	Summary
	Result json.RawMessage `json:"result,omitempty"`
}

type Page struct {
	Version int       `json:"version"`
	Items   []Summary `json:"items"`
	// RawMessage distinguishes the required explicit null from a missing field.
	NextCursor json.RawMessage `json:"nextCursor"`
}

type Health struct {
	Version        int    `json:"version"`
	DurableVersion string `json:"durableVersion"`
	Ready          bool   `json:"ready"`
}

type ErrorEnvelope struct {
	Version int `json:"version"`
	Error   struct {
		Code string `json:"code"`
	} `json:"error"`
}

// Worker errors are strings; public errors deliberately retain an object.
type WorkerError struct {
	Version int    `json:"version"`
	Error   string `json:"error"`
}
