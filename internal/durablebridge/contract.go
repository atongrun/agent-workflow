package durablebridge

import "encoding/json"

// These are the explicit parent-approved defaults pending PRIVATE's final
// field agreement. Business payload/result schemas remain PRIVATE-owned.
const (
	ProtocolVersion       = 1
	DurableVersion        = "1.0.4"
	PublicPrefix          = "/v1/content"
	OwnerHeader           = "X-AWF-Owner"
	MaxRequestBytes       = 256 * 1024
	MaxWorkerRequestBytes = MaxRequestBytes + 1024
	MaxResponseBytes      = 512 * 1024
	MaxResultBytes        = 256 * 1024
	MaxCursorBytes        = 512
	MaxNativeID           = uint64(1<<53 - 1)
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

type fingerprintInput struct {
	Version       int             `json:"version"`
	Capability    string          `json:"capability"`
	PayloadSchema string          `json:"payloadSchema"`
	OpaquePayload json.RawMessage `json:"opaquePayload"`
}

// Summary deliberately has no input, result, prompt, model configuration,
// task/checkpoint detail or transcript. PRIVATE must enforce the same scope.
type Summary struct {
	RequestID      string `json:"requestId"`
	ConversationID uint64 `json:"conversationId"`
	SubmissionID   uint64 `json:"submissionId"`
	Status         string `json:"status"`
	AbortRequested *bool  `json:"abortRequested"`
	Reason         string `json:"reason,omitempty"`
}

type Receipt struct {
	Version int    `json:"version"`
	Owner   string `json:"owner"`
	Summary
	Result json.RawMessage `json:"result,omitempty"`
}

type Page struct {
	Version    int       `json:"version"`
	Owner      string    `json:"owner"`
	Items      []Summary `json:"items"`
	NextCursor string    `json:"nextCursor,omitempty"`
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
