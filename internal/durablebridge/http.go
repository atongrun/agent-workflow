package durablebridge

import (
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"
)

var ownerPattern = regexp.MustCompile(`^[A-Za-z0-9_-]{1,80}$`)
var requestPattern = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)
var labelPattern = regexp.MustCompile(`^[A-Za-z0-9._:/-]{1,128}$`)

func (c *Client) Handler(credentials []Credential, protectedTokens ...string) (http.Handler, error) {
	if len(credentials) < 1 || len(credentials) > 256 {
		return nil, ErrInvalid
	}
	type key struct {
		hash  [32]byte
		owner string
	}
	keys := make([]key, 0, len(credentials))
	seen := map[[32]byte]bool{}
	for _, credential := range credentials {
		token := os.Getenv(credential.TokenEnv)
		if len(token) < 24 || len(token) > 4096 || strings.IndexFunc(token, unicode.IsSpace) >= 0 || !ownerPattern.MatchString(credential.Owner) {
			return nil, ErrInvalid
		}
		h := sha256.Sum256([]byte(token))
		if seen[h] {
			return nil, ErrInvalid
		}
		seen[h] = true
		for _, secret := range protectedTokens {
			other := sha256.Sum256([]byte(secret))
			if secret != "" && subtle.ConstantTimeCompare(h[:], other[:]) == 1 {
				return nil, ErrInvalid
			}
		}
		keys = append(keys, key{h, credential.Owner})
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		header := r.Header.Get("Authorization")
		if len(r.Header.Values("Authorization")) != 1 || !strings.HasPrefix(header, "Bearer ") || len(header) > 4103 {
			writeCode(w, 401, "unauthorized")
			return
		}
		h := sha256.Sum256([]byte(strings.TrimPrefix(header, "Bearer ")))
		owner := ""
		for _, key := range keys {
			if subtle.ConstantTimeCompare(h[:], key.hash[:]) == 1 {
				owner = key.owner
			}
		}
		if owner == "" {
			writeCode(w, 401, "unauthorized")
			return
		}
		c.serve(w, r, owner)
	}), nil
}

func (c *Client) serve(w http.ResponseWriter, r *http.Request, owner string) {
	if !strings.HasPrefix(r.URL.Path, PublicPrefix+"/") || r.URL.RawPath != "" {
		writeCode(w, 404, "not_found")
		return
	}
	path := strings.TrimPrefix(r.URL.Path, PublicPrefix)
	var body any
	var in SubmitInput
	var requestID string
	var conversationID, submissionID uint64
	limit := 0
	if path == "/submissions" {
		switch r.Method {
		case http.MethodPost:
			if r.URL.RawQuery != "" {
				writeCode(w, 400, "invalid_input")
				return
			}
			b, err := io.ReadAll(http.MaxBytesReader(w, r.Body, MaxRequestBytes))
			if err != nil {
				writeCode(w, 413, "invalid_input")
				return
			}
			if strictJSON(b, &in) != nil || in.Version != ProtocolVersion || !requestPattern.MatchString(in.RequestID) || !labelPattern.MatchString(in.Capability) || !labelPattern.MatchString(in.PayloadSchema) {
				writeCode(w, 400, "invalid_input")
				return
			}
			var payload any
			if len(in.OpaquePayload) == 0 || strictJSON(in.OpaquePayload, &payload) != nil || payload == nil {
				writeCode(w, 400, "invalid_input")
				return
			}
			// Send the canonical JSON that was hashed, preserving numeric lexemes.
			// Map keys are sorted by encoding/json; whitespace/key order cannot
			// turn an otherwise identical retry into a new fingerprint.
			in.OpaquePayload, _ = marshalFrame(payload)
			canonical, _ := marshalFrame(fingerprintInput{in.Version, in.Capability, in.PayloadSchema, in.OpaquePayload})
			hash := sha256.Sum256(canonical)
			body = Submit{SubmitInput: in, Owner: owner, Fingerprint: hex.EncodeToString(hash[:])}
			requestID = in.RequestID
		case http.MethodGet:
			q, err := url.ParseQuery(r.URL.RawQuery)
			if err != nil {
				writeCode(w, 400, "invalid_input")
				return
			}
			for k, v := range q {
				if (k != "limit" && k != "cursor") || len(v) != 1 {
					writeCode(w, 400, "invalid_input")
					return
				}
			}
			limit = DefaultPageLimit
			if q.Has("limit") {
				n, err := strconv.Atoi(q.Get("limit"))
				if err != nil || n < 1 || n > MaxPageLimit {
					writeCode(w, 400, "invalid_input")
					return
				}
				limit = n
			}
			if q.Has("cursor") && !validText(q.Get("cursor"), MaxCursorBytes, false) {
				writeCode(w, 400, "invalid_input")
				return
			}
			q.Set("limit", strconv.Itoa(limit))
			q.Set("owner", owner)
			path += "?" + q.Encode()
		default:
			writeCode(w, 405, "method_not_allowed")
			return
		}
	} else {
		if r.URL.RawQuery != "" {
			writeCode(w, 400, "invalid_input")
			return
		}
		parts := strings.Split(strings.TrimPrefix(path, "/"), "/")
		switch {
		case path == "/health" && r.Method == http.MethodGet:
		case len(parts) == 2 && parts[0] == "requests" && requestPattern.MatchString(parts[1]) && r.Method == http.MethodGet:
			requestID = parts[1]
		case (len(parts) == 4 || (len(parts) == 5 && parts[4] == "abort")) && parts[0] == "conversations" && parts[2] == "submissions":
			conversationID = parseNativeID(parts[1])
			submissionID = parseNativeID(parts[3])
			if conversationID == 0 || submissionID == 0 {
				writeCode(w, 400, "invalid_input")
				return
			}
			if len(parts) == 4 && r.Method == http.MethodGet {
				break
			}
			if len(parts) == 5 && r.Method == http.MethodPost {
				body = struct {
					Version int    `json:"version"`
					Owner   string `json:"owner"`
				}{ProtocolVersion, owner}
				break
			}
			writeCode(w, 405, "method_not_allowed")
			return
		default:
			writeCode(w, 404, "not_found")
			return
		}
	}
	if !(r.Method == http.MethodPost && path == "/submissions") {
		b, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 1))
		if err != nil || len(b) != 0 {
			writeCode(w, 400, "invalid_input")
			return
		}
	}
	b, status, err := c.call(r.Context(), r.Method, "/v1"+path, owner, body)
	if err != nil {
		if errors.Is(err, ErrFrameTooLarge) {
			writeCode(w, 413, "invalid_input")
			return
		}
		writeCode(w, 503, "unavailable")
		return
	}
	if status >= 300 {
		var e ErrorEnvelope
		if strictJSON(b, &e) != nil || e.Version != ProtocolVersion || errorStatus(e.Error.Code) != status {
			writeCode(w, 503, "unavailable")
			return
		}
		writeCode(w, status, e.Error.Code)
		return
	}
	if status != 200 && !(r.Method == http.MethodPost && path == "/submissions" && status == 202) {
		writeCode(w, 503, "unavailable")
		return
	}
	if path == "/health" {
		var h Health
		if strictJSON(b, &h) != nil || h.Version != ProtocolVersion || h.DurableVersion != DurableVersion || !h.Ready {
			writeCode(w, 503, "unavailable")
			return
		}
		writeJSON(w, 200, h)
		return
	}
	if limit > 0 {
		var page Page
		if strictJSON(b, &page) != nil || page.Version != ProtocolVersion || page.Items == nil || len(page.Items) > limit || !validCursor(page.NextCursor) {
			writeCode(w, 503, "unavailable")
			return
		}
		seen := map[[2]uint64]bool{}
		for i, item := range page.Items {
			key := [2]uint64{item.ConversationID, item.SubmissionID}
			if !validSummary(item) || seen[key] {
				writeCode(w, 503, "unavailable")
				return
			}
			seen[key] = true
			page.Items[i].Reason = publicReason(item.Reason)
		}
		writeJSON(w, 200, page)
		return
	}
	var receipt Receipt
	if strictJSON(b, &receipt) != nil || receipt.Version != ProtocolVersion || receipt.Owner != owner || !validSummary(receipt.Summary) || (requestID != "" && receipt.RequestID != requestID) || (conversationID != 0 && (receipt.ConversationID != conversationID || receipt.SubmissionID != submissionID)) || len(receipt.Result) > MaxResultBytes {
		writeCode(w, 503, "unavailable")
		return
	}
	if len(receipt.Result) > 0 {
		var result any
		if receipt.Status != "done" || *receipt.AbortRequested || (r.Method == http.MethodPost && strings.HasSuffix(path, "/abort")) || strictJSON(receipt.Result, &result) != nil || result == nil {
			writeCode(w, 503, "unavailable")
			return
		}
	}
	receipt.Reason = publicReason(receipt.Reason)
	writeJSON(w, status, receipt)
}

func validCursor(raw json.RawMessage) bool {
	if len(raw) == 0 {
		return false
	}
	var cursor *string
	return strictJSON(raw, &cursor) == nil && (cursor == nil || validText(*cursor, MaxCursorBytes, false))
}

func publicReason(reason string) string {
	switch reason {
	case "", "aborted", "model_error", "no_model", "reset", "stale", "faulted", "missing_task", "task_too_old", "migration_failed":
		return reason
	default:
		return "unanswered"
	}
}

func parseNativeID(text string) uint64 {
	n, err := strconv.ParseUint(text, 10, 64)
	if err != nil || n == 0 || n > MaxNativeID || strconv.FormatUint(n, 10) != text {
		return 0
	}
	return n
}

func validSummary(s Summary) bool {
	if !requestPattern.MatchString(s.RequestID) || s.ConversationID == 0 || s.ConversationID > MaxNativeID || s.SubmissionID == 0 || s.SubmissionID > MaxNativeID || s.AbortRequested == nil {
		return false
	}
	switch s.Status {
	case "queued", "placed", "done":
		return s.Reason == ""
	case "unanswered":
		return validText(s.Reason, 256, false)
	default:
		return false
	}
}

func validText(s string, max int, empty bool) bool {
	return (empty || s != "") && len(s) <= max && utf8.ValidString(s) && strings.IndexFunc(s, unicode.IsControl) < 0
}

func errorStatus(code string) int {
	switch code {
	case "invalid_input":
		return 400
	case "request_conflict", "admission_pending":
		return 409
	case "not_found":
		return 404
	case "unavailable":
		return 503
	}
	return 0
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	e := json.NewEncoder(w)
	e.SetEscapeHTML(false)
	_ = e.Encode(value)
}
func writeCode(w http.ResponseWriter, status int, code string) {
	var e ErrorEnvelope
	e.Version = ProtocolVersion
	e.Error.Code = code
	writeJSON(w, status, e)
}
