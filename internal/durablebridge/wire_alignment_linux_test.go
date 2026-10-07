//go:build linux

package durablebridge

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestPrivateOwnerAndRequestGrammar(t *testing.T) {
	t.Setenv("AWF_ALIGNMENT_TOKEN", fixtureToken)
	client, err := NewUnixClient("/tmp/awf-unused-alignment.sock", time.Second)
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	for _, owner := range []string{"owner-a", "Owner_A-9", strings.Repeat("a", 80)} {
		if _, err := client.Handler([]Credential{{Owner: owner, TokenEnv: "AWF_ALIGNMENT_TOKEN"}}); err != nil {
			t.Fatal(owner, err)
		}
	}
	for _, owner := range []string{"", strings.Repeat("a", 81), "owner.a", "owner:a", "owner@a", "owner/a", "用户"} {
		if _, err := client.Handler([]Credential{{Owner: owner, TokenEnv: "AWF_ALIGNMENT_TOKEN"}}); !errors.Is(err, ErrInvalid) {
			t.Fatal("invalid PRIVATE owner accepted", owner, err)
		}
	}
	var calls atomic.Int32
	handler := fixtureUnixHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		writeJSON(w, 202, fixtureReceipt())
	}))
	for _, request := range []string{"AAAAAAAA-2222-4333-8444-555555555555", "11111111-2222-3333-8444-555555555555", "11111111-2222-5333-8444-555555555555", "11111111-2222-4333-7444-555555555555"} {
		body := `{"version":1,"requestId":"` + request + `","capability":"shortpost","payloadSchema":"content.v1","opaquePayload":{}}`
		if w := publicCall(handler, "POST", "/submissions", body, fixtureToken); w.Code != 400 {
			t.Fatal("non-v4/lowercase request accepted", request, w.Code)
		}
	}
	if calls.Load() != 0 {
		t.Fatal("bad request reached worker")
	}
}

func TestPrivateListNullAndEmptyContinuation(t *testing.T) {
	var calls atomic.Int32
	handler := fixtureUnixHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		if r.URL.Query().Get("owner") != "owner-a" || r.Header.Get(OwnerHeader) != "" {
			t.Error("owner was not injected from Go auth")
		}
		if r.URL.Query().Has("cursor") {
			if r.URL.Query().Get("cursor") != "opaque+/=" || r.URL.Query().Get("limit") != "50" {
				t.Error("opaque cursor/limit changed")
			}
			writeJSON(w, 200, Page{Version: 1, Items: []Summary{}, NextCursor: json.RawMessage("null")})
			return
		}
		if r.URL.Query().Get("limit") != "20" {
			t.Error("default page limit changed")
		}
		// PRIVATE may stop after its bounded scan before finding another root.
		writeJSON(w, 200, Page{Version: 1, Items: []Summary{}, NextCursor: json.RawMessage(`"opaque+/="`)})
	}))
	first := publicCall(handler, "GET", "/submissions", "", fixtureToken)
	if first.Code != 200 || strings.Contains(first.Body.String(), `"owner"`) || !strings.Contains(first.Body.String(), `"items":[]`) || !strings.Contains(first.Body.String(), `"nextCursor":"opaque+/="`) {
		t.Fatal(first.Code, first.Body.String())
	}
	if calls.Load() != 1 {
		t.Fatal("Go auto-scanned empty continuation page")
	}
	last := publicCall(handler, "GET", "/submissions?limit=50&cursor=opaque%2B%2F%3D", "", fixtureToken)
	if last.Code != 200 || !strings.Contains(last.Body.String(), `"nextCursor":null`) {
		t.Fatal(last.Code, last.Body.String())
	}
	for _, path := range []string{"/submissions?limit=51", "/submissions?owner=owner-b"} {
		if w := publicCall(handler, "GET", path, "", fixtureToken); w.Code != 400 {
			t.Fatal(path, w.Code)
		}
	}
	if calls.Load() != 2 {
		t.Fatal("rejected or continuation request caused extra native reads")
	}
}

func TestPrivateListRequiresNullableCursorField(t *testing.T) {
	for _, suffix := range []string{"", `,"nextCursor":{}`, `,"nextCursor":[]`, `,"nextCursor":12`} {
		t.Run(suffix, func(t *testing.T) {
			handler := fixtureUnixHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.Write([]byte(`{"version":1,"items":[]` + suffix + `}`))
			}))
			if w := publicCall(handler, "GET", "/submissions", "", fixtureToken); w.Code != 503 {
				t.Fatal("invalid PRIVATE page shape accepted", w.Code)
			}
		})
	}
}

func TestCancelledReceiptDoesNotDeliverOpaqueResult(t *testing.T) {
	for _, path := range []string{"/conversations/1/submissions/2", "/conversations/1/submissions/2/abort"} {
		t.Run(path, func(t *testing.T) {
			handler := fixtureUnixHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				receipt := fixtureReceipt()
				receipt.Status = "done"
				aborted := true
				receipt.AbortRequested = &aborted
				receipt.Result = json.RawMessage(`{"candidates":[{"label":"first","content":"must-not-deliver"}],"delivery":{"expectedCount":1,"editorIncomplete":true}}`)
				writeJSON(w, 200, receipt)
			}))
			method := "GET"
			if strings.HasSuffix(path, "/abort") {
				method = "POST"
			}
			w := publicCall(handler, method, path, "", fixtureToken)
			if w.Code != 503 || strings.Contains(w.Body.String(), "must-not-deliver") {
				t.Fatal("cancelled native result delivered", w.Code, w.Body.String())
			}
		})
	}
}

func TestUnconfirmedJoinRetainsLeaseFixture(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, ".awf-owner.lock")
	lease, err := acquireLeaseFile(path)
	if err != nil {
		t.Fatal(err)
	}
	defer lease.Close()
	// No process is started or signalled here. Simulate an unavailable join
	// observation and verify the real OS lease is retained, rather than claiming
	// a synthetic timeout proves native uninterruptible-process behavior.
	w := &Worker{cmd: exec.Command("/not-started"), lease: lease, runtimeDir: dir, done: make(chan struct{})}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if err := w.Close(ctx); !errors.Is(err, ErrStopUnknown) {
		t.Fatal(err)
	}
	if _, err := os.Stat(dir); err != nil {
		t.Fatal("uncertain cleanup removed owned runtime")
	}
	if replacement, err := acquireLeaseFile(path); !errors.Is(err, ErrStorageOwned) {
		if replacement != nil {
			replacement.Close()
		}
		t.Fatal("uncertain join released ownership", err)
	}
}
