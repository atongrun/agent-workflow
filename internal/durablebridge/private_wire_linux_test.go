//go:build linux

package durablebridge

import (
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"sync/atomic"
	"testing"
)

func TestPrivateHTTPSubmissionReferenceFingerprint(t *testing.T) {
	opaque, err := base64.StdEncoding.DecodeString("eyJvcGVyYXRpb24iOiJnZW5lcmF0ZSIsImlucHV0Ijp7ImlkZWEiOiLlhazlvIDlkIjmiJA8Jj7kuK3mlofigKjigKnkuI7lrZfpnaJcXHUyMDI4IiwidHlwZSI6ImV4cGVyaWVuY2UifSwicmV0YWluZWRTb3VyY2VzIjpbXX0=")
	if err != nil {
		t.Fatal(err)
	}
	var calls atomic.Int32
	h := fixtureUnixHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		body, _ := io.ReadAll(r.Body)
		var input Submit
		if strictJSON(body, &input) != nil || input.Fingerprint != "f937a1e281bff96e82ef02a5c873587e6a5d6781010a85b9f07d6396a7e4afe2" || !strings.Contains(string(body), "\u2028\u2029") {
			t.Error("HTTP admission fingerprint differs from actual TS probe")
		}
		if (input.RequestID == fixtureRequest && input.Owner != "owner-a") || (input.RequestID == fixtureRequest2 && input.Owner != "owner-b") {
			t.Error("untrusted HTTP owner")
		}
		receipt := fixtureReceipt()
		receipt.RequestID = input.RequestID
		writeJSON(w, 202, receipt)
	}))
	for _, request := range []struct{ id, token string }{{fixtureRequest, fixtureToken}, {fixtureRequest2, fixtureTokenB}} {
		body := `{"version":1,"requestId":"` + request.id + `","capability":"shortpost","payloadSchema":"shortpost.input.v1","opaquePayload":` + string(opaque) + `}`
		if response := publicCall(h, "POST", "/submissions", body, request.token); response.Code != 202 {
			t.Fatal(response.Code, response.Body.String())
		}
	}
	if calls.Load() != 2 {
		t.Fatal("unexpected submission count")
	}
}

func TestPrivateExactWorkerRoutesAndOwnerCarriers(t *testing.T) {
	for _, test := range []struct {
		method, public, worker string
		cancel                 bool
	}{
		{"GET", "/requests/" + fixtureRequest, "/v1/submissions/by-request/" + fixtureRequest, false},
		{"POST", "/requests/" + fixtureRequest + "/abort", "/v1/submissions/by-request/" + fixtureRequest + "/cancel", true},
		{"GET", "/conversations/1/submissions/2", "/v1/submissions/1/2", false},
		{"POST", "/conversations/1/submissions/2/abort", "/v1/submissions/1/2/cancel", true},
	} {
		t.Run(test.public, func(t *testing.T) {
			var calls atomic.Int32
			h := fixtureUnixHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls.Add(1)
				if r.Method != test.method || r.URL.Path != test.worker || r.Header.Get(OwnerHeader) != "" || r.Header.Get("Authorization") != "" || r.Header.Get("Content-Type") != "application/json" {
					t.Error("wrong worker route or forwarded credential/header")
				}
				body, _ := io.ReadAll(r.Body)
				if test.cancel {
					var input cancelInput
					if r.URL.RawQuery != "" || strictJSON(body, &input) != nil || input.Version != 1 || input.Owner != "owner-a" {
						t.Error("cancel owner was not in trusted body")
					}
				} else if len(body) != 0 || r.URL.Query().Get("owner") != "owner-a" || len(r.URL.Query()) != 1 {
					t.Error("GET owner was not in trusted query")
				}
				writeJSON(w, 200, fixtureReceipt())
			}))
			response := publicCall(h, test.method, test.public, "", fixtureToken)
			if response.Code != 200 || strings.Contains(response.Body.String(), `"owner"`) || calls.Load() != 1 {
				t.Fatal(response.Code, response.Body.String(), calls.Load())
			}
			for _, unsafe := range []struct{ path, body string }{{test.public + "?owner=owner-b", ""}, {test.public, `{"owner":"owner-b"}`}} {
				if response := publicCall(h, test.method, unsafe.path, unsafe.body, fixtureToken); response.Code != 400 {
					t.Fatal(response.Code)
				}
			}
			if calls.Load() != 1 {
				t.Fatal("untrusted owner override reached worker")
			}
		})
	}
}

func TestPrivatePendingReceiptAndListWithoutInventedSID(t *testing.T) {
	for _, cancelled := range []bool{false, true} {
		pending := fixtureSummary(fixtureRequest, "admission_pending")
		pending.SubmissionID = nil
		pending.ConversationID = 3
		pending.AbortRequested = &cancelled
		detail := "dispatch_requires_verification"
		pending.Detail = &detail
		h := fixtureUnixHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Path == "/v1/submissions" {
				writeJSON(w, 200, Page{Version: 1, Items: []Summary{pending}, NextCursor: json.RawMessage(`"opaque continuation"`)})
				return
			}
			writeJSON(w, 200, Receipt{Summary: pending})
		}))
		for _, path := range []string{"/requests/" + fixtureRequest, "/submissions"} {
			response := publicCall(h, "GET", path, "", fixtureToken)
			if response.Code != 200 || strings.Contains(response.Body.String(), `"submissionId"`) || strings.Contains(response.Body.String(), `"detail"`) || !strings.Contains(response.Body.String(), `"status":"admission_pending"`) {
				t.Fatal(response.Code, response.Body.String())
			}
		}
	}
	for _, sid := range []string{`,"submissionId":0`, `,"submissionId":null`, `,"submissionId":2`} {
		h := fixtureUnixHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.Write([]byte(`{"version":1,"requestId":"` + fixtureRequest + `","conversationId":3,"status":"admission_pending","abortRequested":false` + sid + `}`))
		}))
		if response := publicCall(h, "GET", "/requests/"+fixtureRequest, "", fixtureToken); response.Code != 503 {
			t.Fatal("pending SID accepted", sid, response.Code)
		}
	}
}

func TestPrivateWorkerStringErrorPublicObjectProjection(t *testing.T) {
	for code, status := range map[string]int{"invalid_input": 400, "not_found": 404, "request_conflict": 409, "unavailable": 503} {
		h := fixtureUnixHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			writeJSON(w, status, WorkerError{Version: 1, Error: code})
		}))
		response := publicCall(h, "GET", "/requests/"+fixtureRequest, "", fixtureToken)
		var error ErrorEnvelope
		if response.Code != status || strictJSON(response.Body.Bytes(), &error) != nil || error.Error.Code != code {
			t.Fatal(response.Code, response.Body.String())
		}
	}
	for _, body := range []string{`{"version":1,"error":"admission_pending"}`, `{"version":1,"error":{"code":"request_conflict"}}`, `{"version":1,"error":"request_conflict","detail":"private"}`} {
		h := fixtureUnixHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(409); w.Write([]byte(body)) }))
		if response := publicCall(h, "GET", "/requests/"+fixtureRequest, "", fixtureToken); response.Code != 503 {
			t.Fatal(response.Code, response.Body.String())
		}
	}
}

func TestPrivateLateCancelValidatesThenOmitsCompletedResult(t *testing.T) {
	for _, path := range []string{"/requests/" + fixtureRequest + "/abort", "/conversations/1/submissions/2/abort"} {
		h := fixtureUnixHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			receipt := fixtureReceipt()
			receipt.Status = "done"
			receipt.Result = json.RawMessage(`{"candidates":[{"label":"公开候选0","content":"公开合成成稿"}],"delivery":{"expectedCount":1,"editorIncomplete":false}}`)
			writeJSON(w, 200, receipt)
		}))
		response := publicCall(h, "POST", path, "", fixtureToken)
		if response.Code != 200 || strings.Contains(response.Body.String(), `"result"`) || !strings.Contains(response.Body.String(), `"status":"done"`) || !strings.Contains(response.Body.String(), `"abortRequested":false`) {
			t.Fatal(response.Code, response.Body.String())
		}
	}
}

func TestPrivateOpaqueDoneResultAndInputByteEdges(t *testing.T) {
	for _, encoded := range []string{`null`, `"` + strings.Repeat("x", MaxResultBytes-2) + `"`} {
		h := fixtureUnixHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			receipt := fixtureReceipt()
			receipt.Status = "done"
			receipt.Result = json.RawMessage(encoded)
			writeJSON(w, 200, receipt)
		}))
		response := publicCall(h, "GET", "/requests/"+fixtureRequest, "", fixtureToken)
		if response.Code != 200 || !strings.Contains(response.Body.String(), `"result":`) {
			t.Fatal(response.Code, response.Body.String())
		}
	}
	for _, status := range []string{"admission_pending", "placed", "unanswered"} {
		h := fixtureUnixHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			receipt := fixtureReceipt()
			receipt.Status = status
			if status == "admission_pending" {
				receipt.SubmissionID = nil
			}
			receipt.Result = json.RawMessage("null")
			writeJSON(w, 200, receipt)
		}))
		if response := publicCall(h, "GET", "/requests/"+fixtureRequest, "", fixtureToken); response.Code != 503 {
			t.Fatal(status, response.Code)
		}
	}
	var calls atomic.Int32
	h := fixtureUnixHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { calls.Add(1); writeJSON(w, 202, fixtureReceipt()) }))
	body := `{"version":1,"requestId":"` + fixtureRequest + `","capability":"shortpost","payloadSchema":"content.v1","opaquePayload":"` + strings.Repeat("x", MaxInputBytes-2) + `"}`
	if response := publicCall(h, "POST", "/submissions", body, fixtureToken); response.Code != 202 {
		t.Fatal(response.Code)
	}
	plain := `{"version":1,"requestId":"` + fixtureRequest + `","capability":"shortpost","payloadSchema":"content.v1","opaquePayload":{}}`
	full := plain + strings.Repeat(" ", MaxRequestBytes-len(plain))
	if response := publicCall(h, "POST", "/submissions", full, fixtureToken); response.Code != 202 {
		t.Fatal(response.Code)
	}
	if response := publicCall(h, "POST", "/submissions", full+" ", fixtureToken); response.Code != 413 || calls.Load() != 2 {
		t.Fatal(response.Code, calls.Load())
	}
}

func TestPrivateOptionalDetailAndItemVersionRemainStrict(t *testing.T) {
	for _, detail := range []string{"dispatch_requires_verification", "request_budget_exhausted", "stage_failed"} {
		h := fixtureUnixHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			summary := fixtureSummary(fixtureRequest, "placed")
			summary.Detail = &detail
			writeJSON(w, 200, Page{Version: 1, Items: []Summary{summary}, NextCursor: json.RawMessage("null")})
		}))
		response := publicCall(h, "GET", "/submissions", "", fixtureToken)
		if response.Code != 200 || strings.Contains(response.Body.String(), `"detail"`) || !strings.Contains(response.Body.String(), `"version":1`) {
			t.Fatal(response.Code, response.Body.String())
		}
	}
	for _, extra := range []string{`,"detail":"other"`, `,"detail":""`, `,"detail":null`, `,"owner":"owner-a"`, `,"model":"private"`} {
		h := fixtureUnixHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.Write([]byte(`{"version":1,"items":[{"version":1,"requestId":"` + fixtureRequest + `","conversationId":1,"submissionId":2,"status":"placed","abortRequested":false` + extra + `}],"nextCursor":null}`))
		}))
		if response := publicCall(h, "GET", "/submissions", "", fixtureToken); response.Code != 503 {
			t.Fatal(extra, response.Code)
		}
	}
}

func TestPrivateStatusAndCursorByteBounds(t *testing.T) {
	for _, wrong := range []struct {
		method, path string
		status       int
	}{{"POST", "/submissions", 200}, {"GET", "/requests/" + fixtureRequest, 202}, {"POST", "/requests/" + fixtureRequest + "/abort", 202}} {
		h := fixtureUnixHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { writeJSON(w, wrong.status, fixtureReceipt()) }))
		body := ""
		if wrong.path == "/submissions" {
			body = `{"version":1,"requestId":"` + fixtureRequest + `","capability":"shortpost","payloadSchema":"content.v1","opaquePayload":{}}`
		}
		if response := publicCall(h, wrong.method, wrong.path, body, fixtureToken); response.Code != 503 {
			t.Fatal(response.Code)
		}
	}
	var calls atomic.Int32
	h := fixtureUnixHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		cursor := r.URL.Query().Get("cursor")
		if len(cursor) != MaxCursorBytes {
			t.Error("cursor changed")
		}
		encoded, _ := json.Marshal(cursor)
		writeJSON(w, 200, Page{Version: 1, Items: []Summary{}, NextCursor: encoded})
	}))
	if response := publicCall(h, "GET", "/submissions?cursor="+strings.Repeat("x", MaxCursorBytes), "", fixtureToken); response.Code != 200 {
		t.Fatal(response.Code)
	}
	if response := publicCall(h, "GET", "/submissions?cursor="+strings.Repeat("x", MaxCursorBytes+1), "", fixtureToken); response.Code != 400 || calls.Load() != 1 {
		t.Fatal(response.Code, calls.Load())
	}
}
