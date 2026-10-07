package durablebridge

import (
	"bytes"
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
	workerPath := "/v1" + path
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
			// Hash business input before PRIVATE fills defaults. Scalars use
			// JSON.stringify rules; version, owner and requestId are excluded.
			in.OpaquePayload, err = canonicalJSON(payload)
			if err != nil || len(in.OpaquePayload) > MaxInputBytes {
				writeCode(w, 413, "invalid_input")
				return
			}
			canonical, err := canonicalJSON(map[string]any{"capability": in.Capability, "payloadSchema": in.PayloadSchema, "opaquePayload": payload})
			if err != nil {
				writeCode(w, 400, "invalid_input")
				return
			}
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
			if q.Has("cursor") && !validText(q.Get("cursor"), MaxCursorBytes, true) {
				writeCode(w, 400, "invalid_input")
				return
			}
			q.Set("limit", strconv.Itoa(limit))
			q.Set("owner", owner)
			workerPath += "?" + q.Encode()
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
		case (len(parts) == 2 || (len(parts) == 3 && parts[2] == "abort")) && parts[0] == "requests" && requestPattern.MatchString(parts[1]):
			requestID = parts[1]
			workerPath = "/v1/submissions/by-request/" + requestID
			if len(parts) == 2 && r.Method == http.MethodGet {
				break
			}
			if len(parts) == 3 && r.Method == http.MethodPost {
				workerPath += "/cancel"
				body = cancelInput{ProtocolVersion, owner}
				break
			}
			writeCode(w, 405, "method_not_allowed")
			return
		case (len(parts) == 4 || (len(parts) == 5 && parts[4] == "abort")) && parts[0] == "conversations" && parts[2] == "submissions":
			conversationID = parseNativeID(parts[1])
			submissionID = parseNativeID(parts[3])
			if conversationID == 0 || submissionID == 0 {
				writeCode(w, 400, "invalid_input")
				return
			}
			workerPath = "/v1/submissions/" + parts[1] + "/" + parts[3]
			if len(parts) == 4 && r.Method == http.MethodGet {
				break
			}
			if len(parts) == 5 && r.Method == http.MethodPost {
				workerPath += "/cancel"
				body = cancelInput{ProtocolVersion, owner}
				break
			}
			writeCode(w, 405, "method_not_allowed")
			return
		default:
			writeCode(w, 404, "not_found")
			return
		}
	}
	if r.Method == http.MethodGet && limit == 0 && path != "/health" {
		workerPath += "?" + url.Values{"owner": {owner}}.Encode()
	}
	if !(r.Method == http.MethodPost && path == "/submissions") {
		b, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 1))
		if err != nil || len(b) != 0 {
			writeCode(w, 400, "invalid_input")
			return
		}
	}
	b, status, err := c.call(r.Context(), r.Method, workerPath, body)
	if err != nil {
		if errors.Is(err, ErrFrameTooLarge) {
			writeCode(w, 413, "invalid_input")
			return
		}
		writeCode(w, 503, "unavailable")
		return
	}
	if status >= 300 {
		var e WorkerError
		if strictJSON(b, &e) != nil || e.Version != ProtocolVersion || errorStatus(e.Error) != status {
			writeCode(w, 503, "unavailable")
			return
		}
		writeCode(w, status, e.Error)
		return
	}
	expectedStatus := 200
	if r.Method == http.MethodPost && path == "/submissions" {
		expectedStatus = 202
	}
	if status != expectedStatus {
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
		for i, item := range page.Items {
			if !validSummary(item) {
				writeCode(w, 503, "unavailable")
				return
			}
			page.Items[i].Reason = publicReason(item.Reason)
			page.Items[i].Detail = nil
		}
		writeJSON(w, 200, page)
		return
	}
	var receipt Receipt
	if strictJSON(b, &receipt) != nil || !validSummary(receipt.Summary) || (requestID != "" && receipt.RequestID != requestID) || (conversationID != 0 && (receipt.ConversationID != conversationID || nativeSID(receipt.Summary) != submissionID)) || len(receipt.Result) > MaxResultBytes {
		writeCode(w, 503, "unavailable")
		return
	}
	if len(receipt.Result) > 0 {
		var result any
		if receipt.Status != "done" || *receipt.AbortRequested || strictJSON(receipt.Result, &result) != nil {
			writeCode(w, 503, "unavailable")
			return
		}
	}
	if r.Method == http.MethodPost && strings.HasSuffix(path, "/abort") {
		// Completion wins over a late cancel. Validate cached delivery above,
		// then omit it from the public abort projection without inventing work.
		receipt.Result = nil
	}
	receipt.Reason = publicReason(receipt.Reason)
	receipt.Detail = nil
	writeJSON(w, status, receipt)
}

func validCursor(raw json.RawMessage) bool {
	if len(raw) == 0 {
		return false
	}
	if bytes.Equal(bytes.TrimSpace(raw), []byte("null")) {
		return true
	}
	var cursor string
	return strictJSON(raw, &cursor) == nil && validText(cursor, MaxCursorBytes, true)
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
	if s.Version != ProtocolVersion || !requestPattern.MatchString(s.RequestID) || s.ConversationID == 0 || s.ConversationID > MaxNativeID || s.AbortRequested == nil {
		return false
	}
	if s.Detail != nil {
		switch *s.Detail {
		case "dispatch_requires_verification", "request_budget_exhausted", "stage_failed":
		default:
			return false
		}
	}
	if s.Status == "admission_pending" {
		return s.SubmissionID == nil
	}
	if nativeSID(s) == 0 || nativeSID(s) > MaxNativeID {
		return false
	}
	switch s.Status {
	case "queued", "placed", "done", "unanswered":
		// reason is an optional native string, projected to safe public codes.
		return true
	default:
		return false
	}
}

func nativeSID(s Summary) uint64 {
	if s.SubmissionID == nil {
		return 0
	}
	return *s.SubmissionID
}

func validText(s string, max int, empty bool) bool {
	return (empty || s != "") && len(s) <= max && utf8.ValidString(s) && strings.IndexFunc(s, unicode.IsControl) < 0
}

func errorStatus(code string) int {
	switch code {
	case "invalid_input":
		return 400
	case "request_conflict":
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
