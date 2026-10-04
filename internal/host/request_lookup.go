package host

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
)

// requestLookup is a read-only reconciliation operation. It deliberately uses
// the original typed input and normalization so old reserve hashes still match.
// It never reserves an ID, starts Pi, queries a node, or authorizes an effect.
func (s *Server) requestLookup(w http.ResponseWriter, r *http.Request) {
	if len(r.URL.Query()) != 0 {
		writeError(w, fail("invalid_query", "request receipts do not accept query parameters", 400))
		return
	}
	var in struct {
		RequestID string          `json:"requestId"`
		Operation string          `json:"operation"`
		Payload   json.RawMessage `json:"payload"`
	}
	if err := decode(w, r, &in); err != nil {
		writeError(w, err)
		return
	}
	if !requestPattern.MatchString(in.RequestID) || in.RequestID != r.PathValue("requestId") {
		writeError(w, fail("invalid_request_id", "path and requestId must identify the same original request", 400))
		return
	}
	if len(in.Payload) == 0 || bytes.Equal(bytes.TrimSpace(in.Payload), []byte("null")) {
		writeError(w, fail("invalid_json", "original payload object is required", 400))
		return
	}
	var payload any
	var payloadID string
	switch in.Operation {
	case "delete", "restore":
		var original lifecycleInput
		if err := decodeLookupPayload(in.Payload, &original); err != nil {
			writeError(w, err)
			return
		}
		payload, payloadID = original, original.RequestID
	case "pi/resume":
		var original piResumeInput
		if err := decodeLookupPayload(in.Payload, &original); err != nil {
			writeError(w, err)
			return
		}
		payload, payloadID = original, original.RequestID
	case "budget":
		var original budgetInput
		if err := decodeLookupPayload(in.Payload, &original); err != nil {
			writeError(w, err)
			return
		}
		payload, payloadID = original, original.RequestID
	case "target":
		var original targetInput
		if err := decodeLookupPayload(in.Payload, &original); err != nil {
			writeError(w, err)
			return
		}
		payload, payloadID = original, original.RequestID
	case "start", "rework":
		var original actionInput
		if err := decodeLookupPayload(in.Payload, &original); err != nil {
			writeError(w, err)
			return
		}
		if original.Role == "" {
			original.Role = "architect"
		}
		if original.Role != "architect" && original.Role != "reviewer" {
			writeError(w, fail("invalid_role", "role must be architect or reviewer", 400))
			return
		}
		payload, payloadID = original, original.RequestID
	default:
		writeError(w, fail("invalid_operation", "verified lookup supports only pi/resume, budget, target, start, rework, delete, and restore", 400))
		return
	}
	if payloadID != in.RequestID {
		writeError(w, fail("invalid_request_id", "payload must retain the original requestId", 400))
		return
	}
	encoded, _ := json.Marshal(payload)
	digest := sha256.Sum256(encoded)
	st := s.store.Snapshot()
	req := st.Requests[in.RequestID]
	if req == nil || req.TaskID != r.PathValue("id") || st.Tasks[req.TaskID] == nil {
		writeError(w, fail("request_not_found", "request receipt not found for this task", 404))
		return
	}
	if req.Operation != in.Operation || req.Hash != hex.EncodeToString(digest[:]) {
		writeError(w, fail("idempotency_conflict", "requestId was already used with different operation or payload", 409))
		return
	}
	writeJSON(w, 200, map[string]any{"request": req, "task": st.Tasks[req.TaskID]})
}

func decodeLookupPayload(raw json.RawMessage, value any) error {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(value); err != nil {
		return fail("invalid_json", "invalid original request payload", 400)
	}
	if decoder.Decode(&struct{}{}) != io.EOF {
		return fail("invalid_json", "expected one original payload object", 400)
	}
	return nil
}
