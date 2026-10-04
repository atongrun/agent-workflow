package opencode

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestLoopbackOnlyAndNoURLCredentials(t *testing.T) {
	for _, raw := range []string{"https://example.org", "http://192.0.2.1:4096", "http://user:secret@127.0.0.1", "http://127.0.0.1/path", "http://127.0.0.1?directory=other", "file:///tmp/socket"} {
		if _, err := New(Config{URL: raw}); err == nil {
			t.Errorf("accepted unsafe native origin %s", raw)
		}
	}
	for _, raw := range []string{"http://127.0.0.1:4096", "http://[::1]:4096", "http://localhost:4096"} {
		if _, err := New(Config{URL: raw}); err != nil {
			t.Errorf("loopback rejected %s: %v", raw, err)
		}
	}
}
func TestWindowsDirectoryAndNativeJSONPrompt(t *testing.T) {
	const directory = `C:\Users\Example User\Projects\space & unicode-示例`
	prompt := strings.Repeat("Long multiline instruction\n\"quoted\" & $shell; `literal`\n", 1000)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("directory") != directory {
			t.Errorf("directory mangled: %s", r.URL)
		}
		u, p, ok := r.BasicAuth()
		if !ok || u != "opencode" || p != "local-password" {
			t.Error("missing native basic auth")
		}
		if r.URL.Path != "/session/ses_native/prompt_async" {
			t.Errorf("unexpected route %s", r.URL)
		}
		var body struct {
			MessageID string                        `json:"messageID"`
			Parts     []struct{ Type, Text string } `json:"parts"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Fatal(err)
		}
		if body.MessageID != "msg_native" || len(body.Parts) != 1 || body.Parts[0].Type != "text" || body.Parts[0].Text != prompt {
			t.Error("structured prompt changed")
		}
		w.WriteHeader(204)
	}))
	defer server.Close()
	client, err := New(Config{URL: server.URL, Password: "local-password"})
	if err != nil {
		t.Fatal(err)
	}
	if err = client.PromptAsync(context.Background(), directory, "ses_native", "msg_native", prompt); err != nil {
		t.Fatal(err)
	}
}
func TestMutatingRequestsNeverRedirectOrRetry(t *testing.T) {
	var first, redirected atomic.Int32
	target := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { redirected.Add(1); w.WriteHeader(204) }))
	defer target.Close()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		first.Add(1)
		http.Redirect(w, r, target.URL, http.StatusTemporaryRedirect)
	}))
	defer server.Close()
	client, _ := New(Config{URL: server.URL})
	err := client.PromptAsync(context.Background(), "/workspace", "ses_one", "msg_one", "work")
	var status *HTTPError
	if !errors.As(err, &status) || status.StatusCode != 307 {
		t.Fatalf("redirect not surfaced: %v", err)
	}
	if first.Load() != 1 || redirected.Load() != 0 {
		t.Fatal("mutating request redirected or repeated")
	}
}
func TestPathIDsAndMalformedResponsesFail(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { fmt.Fprint(w, "{broken") }))
	defer server.Close()
	client, _ := New(Config{URL: server.URL})
	if _, err := client.Session(context.Background(), "/workspace", "../global"); err == nil {
		t.Fatal("path traversal accepted")
	}
	if _, err := client.CreateSession(context.Background(), "/workspace", "new"); err == nil {
		t.Fatal("malformed JSON accepted")
	}
}
func TestSSEHandshakeAndMultilineData(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		fmt.Fprint(w, "data: {\"type\":\"server.connected\",\"properties\":{}}\n\n")
		w.(http.Flusher).Flush()
		fmt.Fprint(w, "data: {\"type\":\"session.error\",\n")
		fmt.Fprint(w, "data: \"properties\":{\"sessionID\":\"ses_one\"}}\n\n")
		w.(http.Flusher).Flush()
		<-r.Context().Done()
	}))
	defer server.Close()
	client, _ := New(Config{URL: server.URL, HTTPClient: &http.Client{Timeout: 10 * time.Millisecond}})
	stream, err := client.OpenEvents(context.Background(), "C:\\Workspace")
	if err != nil {
		t.Fatal(err)
	}
	defer stream.Close()
	time.Sleep(20 * time.Millisecond)
	event, err := stream.Next()
	if err != nil || event.Type != "session.error" {
		t.Fatalf("SSE event: %+v %v", event, err)
	}
}

func TestSSEAggregateFrameBound(t *testing.T) {
	frame := "data: " + strings.Repeat("x", 1<<20) + "\ndata: " + strings.Repeat("y", 1<<20) + "\n\n"
	scanner := bufio.NewScanner(strings.NewReader(frame))
	scanner.Buffer(make([]byte, 4096), 2<<20)
	stream := &Events{body: io.NopCloser(strings.NewReader("")), scanner: scanner, cancel: func() {}}
	_, err := stream.Next()
	if err == nil || !strings.Contains(err.Error(), "frame exceeds") {
		t.Fatalf("unbounded multiline frame: %v", err)
	}
}
func TestOptionalNativeModelSelection(t *testing.T) {
	for _, model := range []*ModelSelection{nil, {ProviderID: "provider", ModelID: "model-with-version"}} {
		t.Run(fmt.Sprint(model), func(t *testing.T) {
			var received map[string]json.RawMessage
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				_ = json.NewDecoder(r.Body).Decode(&received)
				w.WriteHeader(204)
			}))
			defer server.Close()
			client, err := New(Config{URL: server.URL})
			if err != nil {
				t.Fatal(err)
			}
			if err = client.PromptAsync(context.Background(), "/workspace", "ses_model", "msg_model", "work", model); err != nil {
				t.Fatal(err)
			}
			if model == nil {
				if _, ok := received["model"]; ok {
					t.Fatal("omitted selection changed native default")
				}
			} else {
				var got ModelSelection
				if err = json.Unmarshal(received["model"], &got); err != nil {
					t.Fatal(err)
				}
				if got != *model {
					t.Fatalf("model forwarding changed: %+v", got)
				}
			}
		})
	}
	for _, model := range []*ModelSelection{{}, {ProviderID: "provider"}, {ModelID: "model"}, {ProviderID: "bad\nprovider", ModelID: "model"}} {
		if model.Validate() == nil {
			t.Fatalf("invalid model accepted: %+v", model)
		}
	}
}

func TestQuestionReplyScopedTypedACKAndNoRetry(t *testing.T) {
	for _, ack := range []string{"true", "false", "{}"} {
		t.Run(ack, func(t *testing.T) {
			var calls atomic.Int32
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls.Add(1)
				if r.Method != "POST" || r.URL.Path != "/question/que_native/reply" || r.URL.Query().Get("directory") != `C:\Workspace` {
					t.Error("wrong question route/scope")
				}
				_, password, ok := r.BasicAuth()
				if !ok || password != "local-password" {
					t.Error("missing node-local basic auth")
				}
				var body struct {
					Answers [][]string `json:"answers"`
				}
				if json.NewDecoder(r.Body).Decode(&body) != nil || len(body.Answers) != 1 || body.Answers[0][0] != "Yes" {
					t.Error("typed answer changed")
				}
				fmt.Fprint(w, ack)
			}))
			defer server.Close()
			client, _ := New(Config{URL: server.URL, Password: "local-password"})
			err := client.ReplyQuestion(context.Background(), `C:\Workspace`, "que_native", [][]string{{"Yes"}})
			if (err == nil) != (ack == "true") || calls.Load() != 1 {
				t.Fatal("wrong ACK or retried mutation", err, calls.Load())
			}
			if err := client.ReplyQuestion(context.Background(), `C:\Workspace`, "que_../escape", [][]string{{"Yes"}}); err == nil || calls.Load() != 1 {
				t.Fatal("unsafe native question ID forwarded")
			}
		})
	}
}

func TestQuestionRejectUsesScopedOwnerAuthentication(t *testing.T) {
	for _, ack := range []string{"true", "false", "{}", "404"} {
		t.Run(ack, func(t *testing.T) {
			var calls atomic.Int32
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls.Add(1)
				if r.Method != "POST" || r.URL.Path != "/question/que_old/reject" || r.URL.Query().Get("directory") != `C:\Workspace` {
					t.Error("wrong rejection scope")
				}
				_, password, ok := r.BasicAuth()
				if !ok || password != "owner-password" {
					t.Error("missing owner authentication")
				}
				if ack == "404" {
					w.WriteHeader(http.StatusNotFound)
				}
				fmt.Fprint(w, ack)
			}))
			defer server.Close()
			client, _ := New(Config{URL: server.URL, Password: "owner-password"})
			err := client.RejectQuestion(context.Background(), `C:\Workspace`, "que_old")
			if (err == nil) != (ack == "true") || calls.Load() != 1 {
				t.Fatal("wrong ACK or repeated mutation", err, calls.Load())
			}
			if err := client.RejectQuestion(context.Background(), `C:\Workspace`, "que_../other"); err == nil || calls.Load() != 1 {
				t.Fatal("invalid question forwarded")
			}
		})
	}
}
