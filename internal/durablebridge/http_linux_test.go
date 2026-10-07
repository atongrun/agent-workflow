//go:build linux

package durablebridge

import (
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

const fixtureRequest = "11111111-2222-4333-8444-555555555555"
const fixtureRequest2 = "11111111-2222-4333-8444-555555555556"
const fixtureToken = "fixture-owner-a-token-1234567890"
const fixtureTokenB = "fixture-owner-b-token-1234567890"

func fixtureSummary(request string, status string) Summary {
	abort := false
	sid := uint64(2)
	return Summary{Version: 1, RequestID: request, ConversationID: 1, SubmissionID: &sid, Status: status, AbortRequested: &abort}
}

func fixtureReceipt() Receipt {
	return Receipt{Summary: fixtureSummary(fixtureRequest, "placed")}
}

// This is a real Unix HTTP server with synthetic responses, not a Pi Harness.
func fixtureUnixHandler(t *testing.T, serve http.Handler) http.Handler {
	t.Helper()
	dir, err := os.MkdirTemp("/tmp", "awf-uds-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(dir) })
	socket := filepath.Join(dir, "worker.sock")
	listener, err := net.Listen("unix", socket)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(socket, 0600); err != nil {
		t.Fatal(err)
	}
	server := &http.Server{Handler: serve, ReadHeaderTimeout: time.Second}
	go server.Serve(listener)
	t.Cleanup(func() { server.Close(); listener.Close() })
	client, err := NewUnixClient(socket, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(client.Close)
	t.Setenv("AWF_FIXTURE_A", fixtureToken)
	t.Setenv("AWF_FIXTURE_B", fixtureTokenB)
	handler, err := client.Handler([]Credential{{Owner: "owner-a", TokenEnv: "AWF_FIXTURE_A"}, {Owner: "owner-b", TokenEnv: "AWF_FIXTURE_B"}}, "fixture-host-secret-1234567890")
	if err != nil {
		t.Fatal(err)
	}
	return handler
}

func publicCall(handler http.Handler, method, path, body, token string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(method, PublicPrefix+path, strings.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+token)
	// Deliberately try to smuggle a different owner and unrelated secrets.
	req.Header.Set(OwnerHeader, "owner-b")
	req.Header.Set("Cookie", "do-not-forward")
	req.Header.Set("Idempotency-Key", "do-not-forward")
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, req)
	return w
}

func TestOwnerFingerprintAndCanonicalInputUnixFixture(t *testing.T) {
	var mu sync.Mutex
	var submissions []Submit
	handler := fixtureUnixHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/submissions" || r.Method != "POST" || r.Header.Get(OwnerHeader) != "" || r.Header.Get("Authorization") != "" || r.Header.Get("Cookie") != "" || r.Header.Get("Idempotency-Key") != "" {
			t.Error("untrusted route/header reached worker")
		}
		b, _ := io.ReadAll(r.Body)
		var input Submit
		if strictJSON(b, &input) != nil || input.Owner != "owner-a" || len(input.Fingerprint) != 64 {
			t.Error("missing trusted owner/fingerprint")
		}
		mu.Lock()
		submissions = append(submissions, input)
		mu.Unlock()
		writeJSON(w, 202, fixtureReceipt())
	}))
	for _, payload := range []string{`{"b":2,"a":1.0}`, `{ "a":1, "b":2 }`} {
		body := `{"version":1,"requestId":"` + fixtureRequest + `","capability":"shortpost","payloadSchema":"content.v1","opaquePayload":` + payload + `}`
		if w := publicCall(handler, "POST", "/submissions", body, fixtureToken); w.Code != 202 {
			t.Fatalf("submit failed: %d %s", w.Code, w.Body.String())
		}
	}
	mu.Lock()
	defer mu.Unlock()
	if len(submissions) != 2 || submissions[0].Fingerprint != submissions[1].Fingerprint || string(submissions[0].OpaquePayload) != `{"a":1,"b":2}` {
		t.Fatal("canonical retry changed fingerprint or number normalization")
	}
}

func TestUntrustedInputDoesNotReachWorkerUnixFixture(t *testing.T) {
	var calls atomic.Int32
	handler := fixtureUnixHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		writeJSON(w, 200, fixtureReceipt())
	}))
	valid := `{"version":1,"requestId":"` + fixtureRequest + `","capability":"shortpost","payloadSchema":"content.v1","opaquePayload":{}}`
	for _, body := range []string{
		strings.TrimSuffix(valid, "}") + `,"owner":"owner-b"}`,
		strings.TrimSuffix(valid, "}") + `,"fingerprint":"invented"}`,
		strings.Replace(valid, `"version":1`, `"version":1,"version":1`, 1),
		strings.Replace(valid, `"version":1`, `"version":1,"Version":1`, 1),
		strings.Replace(valid, `"requestId"`, `"RequestID"`, 1),
		strings.Replace(valid, `"opaquePayload":{}`, `"opaquePayload":{"a":1,"a":2}`, 1),
		strings.Replace(valid, `"opaquePayload":{}`, `"opaquePayload":null`, 1),
		valid + "{}", strings.Replace(valid, "shortpost", string([]byte{0xff}), 1),
		strings.Replace(valid, `"opaquePayload":{}`, `"opaquePayload":`+strings.Repeat("[", 34)+"0"+strings.Repeat("]", 34), 1),
	} {
		if w := publicCall(handler, "POST", "/submissions", body, fixtureToken); w.Code != 400 {
			t.Fatalf("unsafe input accepted: %d", w.Code)
		}
	}
	if w := publicCall(handler, "POST", "/submissions", valid, "wrong-token"); w.Code != 401 {
		t.Fatal(w.Code)
	}
	if w := publicCall(handler, "POST", "/submissions", strings.Repeat(" ", MaxRequestBytes+1), fixtureToken); w.Code != 413 {
		t.Fatal(w.Code)
	}
	if calls.Load() != 0 {
		t.Fatal("rejected input reached worker")
	}
}

func TestFinalWorkerEnvelopeBudgetUnixFixture(t *testing.T) {
	var calls atomic.Int32
	handler := fixtureUnixHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		b, _ := io.ReadAll(r.Body)
		if len(b) > MaxWorkerRequestBytes || strings.Contains(string(b), `\u003c`) {
			t.Error("final frame expanded past its budget or HTML escaped")
		}
		writeJSON(w, 202, fixtureReceipt())
	}))
	wrap := func(payload string) string {
		return `{"version":1,"requestId":"` + fixtureRequest + `","capability":"shortpost","payloadSchema":"content.v1","opaquePayload":"` + payload + `"}`
	}
	body := wrap(strings.Repeat("<&>", (MaxInputBytes-3)/3))
	if len(body) > MaxRequestBytes {
		t.Fatal("invalid fixture")
	}
	if w := publicCall(handler, "POST", "/submissions", body, fixtureToken); w.Code != 202 {
		t.Fatal(w.Code, w.Body.String())
	}
	body = wrap(strings.Repeat("\u2028", (MaxInputBytes-3)/3))
	if len(body) > MaxRequestBytes {
		t.Fatal("invalid fixture")
	}
	if w := publicCall(handler, "POST", "/submissions", body, fixtureToken); w.Code != 202 {
		t.Fatal("literal Unicode was unnecessarily expanded", w.Code)
	}
	if w := publicCall(handler, "POST", "/submissions", wrap(strings.Repeat("x", MaxInputBytes)), fixtureToken); w.Code != 413 {
		t.Fatal("oversized opaque input was sent", w.Code)
	}
	if calls.Load() != 2 {
		t.Fatal("oversized final frame reached worker")
	}
}

func TestArbitraryNativeReasonIsNotPublicUnixFixture(t *testing.T) {
	handler := fixtureUnixHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receipt := fixtureReceipt()
		receipt.Status = "unanswered"
		receipt.Reason = "private-secret-model-detail"
		if r.URL.Path == "/v1/submissions" {
			writeJSON(w, 200, Page{Version: 1, Items: []Summary{receipt.Summary}, NextCursor: json.RawMessage("null")})
		} else {
			writeJSON(w, 200, receipt)
		}
	}))
	for _, path := range []string{"/submissions", "/conversations/1/submissions/2"} {
		w := publicCall(handler, "GET", path, "", fixtureToken)
		if w.Code != 200 || strings.Contains(w.Body.String(), "private-secret") || !strings.Contains(w.Body.String(), `"reason":"unanswered"`) {
			t.Fatal(w.Code, w.Body.String())
		}
	}
}

func TestLostMutationAckIsNotRetriedAndLookupIsReadOnlyUnixFixture(t *testing.T) {
	var mutations, reads atomic.Int32
	handler := fixtureUnixHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "POST" {
			mutations.Add(1)
			io.Copy(io.Discard, r.Body)
			conn, _, err := w.(http.Hijacker).Hijack()
			if err == nil {
				conn.Close()
			}
			return
		}
		reads.Add(1)
		writeJSON(w, 200, fixtureReceipt())
	}))
	body := `{"version":1,"requestId":"` + fixtureRequest + `","capability":"shortpost","payloadSchema":"content.v1","opaquePayload":{}}`
	if w := publicCall(handler, "POST", "/submissions", body, fixtureToken); w.Code != 503 {
		t.Fatal(w.Code)
	}
	if mutations.Load() != 1 {
		t.Fatalf("lost ACK caused %d mutations", mutations.Load())
	}
	if w := publicCall(handler, "GET", "/requests/"+fixtureRequest, "", fixtureToken); w.Code != 200 {
		t.Fatal(w.Code)
	}
	if mutations.Load() != 1 || reads.Load() != 1 {
		t.Fatal("lookup recreated or retried a mutation")
	}
	if w := publicCall(handler, "POST", "/conversations/1/submissions/2/abort", "", fixtureToken); w.Code != 503 {
		t.Fatal(w.Code)
	}
	if mutations.Load() != 2 {
		t.Fatal("abort mutation retried")
	}
}

func TestNativeReceiptScopeAndBoundsUnixFixture(t *testing.T) {
	for _, name := range []string{"wrong-owner", "wrong-id", "unsafe-integer", "invented-status", "missing-abort", "done-reason", "unanswered-without-reason", "huge-result", "huge-response", "private-detail", "redirect", "valid-result"} {
		t.Run(name, func(t *testing.T) {
			handler := fixtureUnixHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				receipt := fixtureReceipt()
				switch name {
				case "wrong-owner":
					w.Write([]byte(`{"version":1,"owner":"owner-b","requestId":"` + fixtureRequest + `","conversationId":1,"submissionId":2,"status":"placed","abortRequested":false}`))
					return
				case "wrong-id":
					*receipt.SubmissionID = 3
				case "unsafe-integer":
					receipt.ConversationID = MaxNativeID + 1
				case "invented-status":
					receipt.Status = "running"
				case "missing-abort":
					receipt.AbortRequested = nil
				case "done-reason":
					receipt.Status = "done"
					receipt.Reason = "private"
				case "unanswered-without-reason":
					receipt.Status = "unanswered"
				case "huge-result":
					receipt.Status = "done"
					receipt.Result = json.RawMessage(`"` + strings.Repeat("x", MaxResultBytes) + `"`)
				case "huge-response":
					w.Write([]byte(strings.Repeat(" ", MaxResponseBytes+1)))
					return
				case "private-detail":
					w.WriteHeader(409)
					w.Write([]byte(`{"version":1,"error":{"code":"request_conflict","message":"private-secret"}}`))
					return
				case "redirect":
					w.Header().Set("Location", "http://127.0.0.1:1/private-secret")
					w.WriteHeader(307)
					return
				case "valid-result":
					receipt.Status = "done"
					receipt.Result = json.RawMessage(`{"artifactRef":"opaque-business-result"}`)
				}
				writeJSON(w, 200, receipt)
			}))
			w := publicCall(handler, "GET", "/conversations/1/submissions/2", "", fixtureToken)
			want := 503
			if name == "valid-result" || name == "done-reason" || name == "unanswered-without-reason" {
				want = 200
			}
			if w.Code != want || strings.Contains(w.Body.String(), "private-secret") {
				t.Fatalf("bad receipt leaked or passed: %d %s", w.Code, w.Body.String())
			}
		})
	}
}

func TestBoundedSummaryPaginationAndOwnerIsolationUnixFixture(t *testing.T) {
	var calls atomic.Int32
	handler := fixtureUnixHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		if (r.URL.Query().Get("owner") != "owner-a" && r.URL.Query().Get("owner") != "owner-b") || r.Header.Get(OwnerHeader) != "" || r.URL.Query().Get("limit") != "2" || r.URL.Query().Get("cursor") != "opaque+/=" {
			t.Error("pagination was not normalized")
		}
		first := fixtureSummary(fixtureRequest, "queued")
		second := fixtureSummary(fixtureRequest2, "done")
		*second.SubmissionID = 3
		writeJSON(w, 200, Page{Version: 1, Items: []Summary{first, second}, NextCursor: json.RawMessage(`"next.cursor"`)})
	}))
	for _, token := range []string{fixtureToken, fixtureTokenB} {
		w := publicCall(handler, "GET", "/submissions?limit=2&cursor=opaque%2B%2F%3D", "", token)
		if w.Code != 200 || strings.Contains(w.Body.String(), "opaquePayload") || strings.Contains(w.Body.String(), "result") {
			t.Fatal(w.Code, w.Body.String())
		}
	}
	for _, path := range []string{"/submissions?limit=101", "/submissions?limit=2&limit=3", "/submissions?owner=owner-b", "/submissions?cursor=a&cursor=b", "/submissions?offset=0", "/conversations/01/submissions/2", "/conversations/9007199254740992/submissions/2"} {
		if w := publicCall(handler, "GET", path, "", fixtureToken); w.Code != 400 {
			t.Fatal(path, w.Code)
		}
	}
	for _, method := range []string{"GET", "POST"} {
		path := "/conversations/1/submissions/2"
		if method == "POST" {
			path += "/abort"
		}
		if w := publicCall(handler, method, path, `{"owner":"owner-b"}`, fixtureToken); w.Code != 400 {
			t.Fatal(w.Code)
		}
	}
	if calls.Load() != 2 {
		t.Fatal("invalid pagination/body reached worker")
	}
}

func TestListCannotExposeResultUnixFixture(t *testing.T) {
	handler := fixtureUnixHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"version":1,"items":[{"version":1,"requestId":"` + fixtureRequest + `","conversationId":1,"submissionId":2,"status":"done","abortRequested":false,"result":{"private":"do-not-expose"}}],"nextCursor":null}`))
	}))
	w := publicCall(handler, "GET", "/submissions", "", fixtureToken)
	if w.Code != 503 || strings.Contains(w.Body.String(), "do-not-expose") {
		t.Fatal(w.Code, w.Body.String())
	}
}
