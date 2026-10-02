package lifecycle

import (
	"context"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/atongrun/agent-workflow/internal/node"
	"github.com/atongrun/agent-workflow/internal/opencode"
)

func TestNativeIdleFailsClosedOnBusyOrUnknownResponses(t *testing.T) {
	cases := []struct {
		name, path, body string
		status           int
		wantOK           bool
	}{
		{name: "empty native state", wantOK: true},
		{name: "known idle session", path: "/session/status", body: `{"ses_fixture":{"type":"idle"}}`, wantOK: true},
		{name: "unhealthy native", path: "/global/health", body: `{"healthy":false}`},
		{name: "unknown health", path: "/global/health", body: `{}`},
		{name: "malformed health", path: "/global/health", body: `{`},
		{name: "native unavailable", path: "/global/health", status: 503},
		{name: "busy session", path: "/session/status", body: `{"ses_fixture":{"type":"busy"}}`},
		{name: "retrying session", path: "/session/status", body: `{"ses_fixture":{"type":"retry"}}`},
		{name: "unknown session", path: "/session/status", body: `{"ses_fixture":{}}`},
		{name: "status unavailable", path: "/session/status", status: 503},
		{name: "status malformed", path: "/session/status", body: `[]`},
		{name: "status null", path: "/session/status", body: `null`},
		{name: "permission pending", path: "/permission", body: `[{"id":"perm_fixture"}]`},
		{name: "permission unavailable", path: "/permission", status: 503},
		{name: "permission malformed", path: "/permission", body: `{}`},
		{name: "permission null", path: "/permission", body: `null`},
		{name: "question pending", path: "/question", body: `[{"id":"question_fixture"}]`},
		{name: "question unavailable", path: "/question", status: 503},
		{name: "question malformed", path: "/question", body: `{}`},
		{name: "question null", path: "/question", body: `null`},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			workspace := filepath.Join(t.TempDir(), "workspace")
			paths := map[string]int{}
			client := &http.Client{Transport: fixtureTransport(func(req *http.Request) (*http.Response, error) {
				if req.Method != "GET" {
					t.Fatalf("idle check mutated native state: %s", req.Method)
				}
				if req.URL.Host != "127.0.0.1:4096" {
					t.Fatalf("idle check left loopback: %s", req.URL)
				}
				if req.URL.Path != "/global/health" && req.URL.Query().Get("directory") != workspace {
					t.Fatalf("missing configured workspace scope: %s", req.URL)
				}
				paths[req.URL.Path]++
				b := map[string]string{"/global/health": `{"healthy":true,"version":"fixture"}`, "/session/status": `{}`, "/permission": `[]`, "/question": `[]`}[req.URL.Path]
				if b == "" {
					t.Fatalf("unexpected native call: %s", req.URL)
				}
				status := 200
				if req.URL.Path == tc.path {
					if tc.body != "" {
						b = tc.body
					}
					if tc.status != 0 {
						status = tc.status
					}
				}
				return &http.Response{StatusCode: status, Body: io.NopCloser(strings.NewReader(b)), Header: make(http.Header)}, nil
			})}
			n, err := opencode.New(opencode.Config{URL: "http://127.0.0.1:4096", HTTPClient: client})
			if err != nil {
				t.Fatal(err)
			}
			err = nativeIdle(context.Background(), n, Config{Node: node.Config{Projects: map[string]string{"fixture": workspace}}})
			if (err == nil) != tc.wantOK {
				t.Fatalf("native idle result = %v; wantOK=%t", err, tc.wantOK)
			}
			if tc.wantOK && len(paths) != 4 {
				t.Fatalf("idle omitted a native state check: %v", paths)
			}
		})
	}
}

func TestReadRuntimeRejectsUnsafeTargets(t *testing.T) {
	for _, address := range []string{"https://127.0.0.1:1234", "http://localhost:1234", "http://192.0.2.1:1234", "http://0.0.0.0:1234", "http://[::1]:1234", "http://127.0.0.1:1234/path", "http://127.0.0.1:1234?x=1", "http://127.0.0.1:1234#fragment", "http://127.0.0.1:1234@evil.invalid", "http://127.0.0.1:notaport", "http://127.0.0.1:65536"} {
		t.Run(address, func(t *testing.T) {
			root := t.TempDir()
			if err := writeJSON(runtimePath(root), Runtime{URL: address, Token: strings.Repeat("a", 64), Version: "v1.2.3"}); err != nil {
				t.Fatal(err)
			}
			if _, err := readRuntime(root); err == nil {
				t.Fatal("unsafe runtime identity accepted")
			}
		})
	}
	root := t.TempDir()
	if err := writeJSON(runtimePath(root), Runtime{URL: "http://127.0.0.1:1234", Token: "short", Version: "v1.2.3"}); err != nil {
		t.Fatal(err)
	}
	if _, err := readRuntime(root); err == nil {
		t.Fatal("invalid control token accepted")
	}
	want := Runtime{URL: "http://127.0.0.1:1234", Token: strings.Repeat("a", 64), Version: "v1.2.3"}
	if err := writeJSON(runtimePath(root), want); err != nil {
		t.Fatal(err)
	}
	if got, err := readRuntime(root); err != nil || got != want {
		t.Fatalf("runtime = %+v, %v", got, err)
	}
}

func TestControlRequiresAuthenticatedMatchingHealth(t *testing.T) {
	original := localHTTP
	t.Cleanup(func() { localHTTP = original })
	r := Runtime{URL: "http://127.0.0.1:1234", Token: strings.Repeat("a", 64), Version: "v1.2.3"}
	for _, tc := range []struct {
		name, body string
		status     int
		failure    bool
		wantOK     bool
	}{
		{"valid identity", `{"version":"v1.2.3"}`, 200, false, true},
		{"wrong identity", `{"version":"v1.2.4"}`, 200, false, false},
		{"missing identity", `{}`, 200, false, false},
		{"invalid JSON", `{`, 200, false, false},
		{"unauthorized", `unauthorized`, 401, false, false},
		{"unreachable", ``, 0, true, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			localHTTP = &http.Client{Transport: fixtureTransport(func(req *http.Request) (*http.Response, error) {
				if req.Header.Get("Authorization") != "Bearer "+r.Token {
					t.Fatal("missing scoped control authorization")
				}
				if req.Method != "GET" || req.URL.String() != r.URL+"/health" {
					t.Fatalf("unexpected control request: %s %s", req.Method, req.URL)
				}
				if tc.failure {
					return nil, errors.New("synthetic connection failure")
				}
				return &http.Response{StatusCode: tc.status, Body: io.NopCloser(strings.NewReader(tc.body)), Header: make(http.Header)}, nil
			})}
			if err := control(r, "GET", "/health"); (err == nil) != tc.wantOK {
				t.Fatalf("control = %v; wantOK=%t", err, tc.wantOK)
			}
		})
	}
	if err := original.CheckRedirect(nil, nil); err != http.ErrUseLastResponse {
		t.Fatalf("control redirects not refused: %v", err)
	}
}

func TestCleanEnvironmentRemovesInheritedRuntimeCredentials(t *testing.T) {
	input := []string{"PATH=fixture", "AWF_TOKEN=fixture", "awf_config=fixture", "AwF_SOMETHING=fixture", "OPENCODE_SERVER_PASSWORD=fixture", "opencode_server_username=fixture", "HOME=fixture", "OPENAI_API_KEY=provider-owned-fixture", "OPENCODE_CONFIG=provider-owned-fixture"}
	before := append([]string(nil), input...)
	want := []string{"PATH=fixture", "HOME=fixture", "OPENAI_API_KEY=provider-owned-fixture", "OPENCODE_CONFIG=provider-owned-fixture"}
	if got := cleanEnvironment(input); !reflect.DeepEqual(got, want) {
		t.Fatalf("cleaned environment = %v", got)
	}
	if !reflect.DeepEqual(input, before) {
		t.Fatal("input environment mutated")
	}
}

func TestUpdateAllFailsBeforeCreatingInstallation(t *testing.T) {
	root := t.TempDir()
	t.Setenv("LOCALAPPDATA", root)
	for _, flag := range []string{"--all", "-all", "--all=true", "--all=false"} {
		if err := Run([]string{"update", flag}, strings.NewReader(""), io.Discard); err == nil || !strings.Contains(err.Error(), "not implemented") {
			t.Fatalf("%s: %v", flag, err)
		}
	}
	if _, err := os.Stat(filepath.Join(root, "AWF")); !os.IsNotExist(err) {
		t.Fatalf("unsupported update changed installation: %v", err)
	}
}
