//go:build windows

package host

import (
	"bytes"
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

type windowsProviderTransport func(*http.Request) (*http.Response, error)

func (f windowsProviderTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	return f(r)
}

func TestWindowsProviderPOSIXFileChecksFailClosed(t *testing.T) {
	// Windows mode bits express the read-only attribute, not a private DACL.
	// Neither spelling of a POSIX private file may bypass the existing check.
	for _, mode := range []os.FileMode{0600, 0400} {
		t.Run(mode.String(), func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "credential")
			if err := os.WriteFile(path, []byte("synthetic-provider-credential"), mode); err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() { _ = os.Chmod(path, 0600) })
			if data, err := privateRegular(path, 4096); err == nil || len(data) != 0 {
				t.Fatal("POSIX mode accepted as a private Windows credential")
			}
		})
	}

	dir := t.TempDir()
	existing := filepath.Join(dir, "existing.json")
	original := []byte(`{"unchanged":true}`)
	if err := os.WriteFile(existing, original, 0600); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{existing, filepath.Join(dir, "new.json")} {
		if err := atomicPrivateJSON(path, map[string]bool{"changed": true}); err == nil {
			t.Fatal("POSIX directory check accepted Windows provider persistence")
		}
	}
	data, err := os.ReadFile(existing)
	if err != nil || !bytes.Equal(data, original) {
		t.Fatal("rejected provider write changed an existing file")
	}
	entries, err := os.ReadDir(dir)
	if err != nil || len(entries) != 1 || entries[0].Name() != "existing.json" {
		t.Fatal("rejected provider write created an output or temporary file")
	}
}

func TestWindowsProviderManagementRefusesBeforeHTTPOrStateWrites(t *testing.T) {
	for _, mode := range []string{"credential-file", "linux-broker"} {
		t.Run(mode, func(t *testing.T) {
			s := testServer(t)
			dir := t.TempDir()
			s.cfg.MagpieWebKeyFile = filepath.Join(dir, "web-key")
			s.cfg.MagpieConfigDir = dir
			s.cfg.ContentServiceTokenFile = filepath.Join(dir, "content-key")
			s.cfg.DurableConfig = filepath.Join(dir, "durable-config")
			s.cfg.ContentPiAgentDir = filepath.Join(dir, "content")
			s.cfg.ContentDurablePiAgentDir = filepath.Join(dir, "durable")
			const credential = "synthetic-windows-management-credential"
			const submittedKey = "synthetic-windows-submitted-key"
			originals := map[string][]byte{}
			originals[s.cfg.MagpieWebKeyFile] = []byte(credential)
			originals[s.cfg.ContentServiceTokenFile] = []byte(credential)
			originals[s.cfg.DurableConfig] = []byte(`{}`)
			originals[filepath.Join(dir, "providers.json")] = []byte(`{"providers":[]}`)
			for _, agentDir := range []string{s.cfg.PiAgentDir, s.cfg.ContentPiAgentDir, s.cfg.ContentDurablePiAgentDir} {
				originals[filepath.Join(agentDir, "models.json")] = []byte(`{"providers":{"magpie":{"baseUrl":"http://127.0.0.1:3425/v1","api":"openai-completions","apiKey":"magpie","models":[{"id":"qwen-cn/existing","contextWindow":1000,"maxTokens":500}]}}}`)
				originals[filepath.Join(agentDir, "settings.json")] = []byte(`{"defaultModel":"existing"}`)
			}
			for path, data := range originals {
				if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(path, data, 0600); err != nil {
					t.Fatal(err)
				}
			}
			if mode == "linux-broker" {
				s.cfg.ContentAdminSocket = filepath.Join(dir, "provider.sock")
				// Exercise the real non-Linux guard; no providerAdminCall bypass.
				if err := validateProviderSocket(s.cfg.ContentAdminSocket); err == nil {
					t.Fatal("Linux provider socket accepted on Windows")
				}
				if err := validateProviderPeer(nil); err == nil {
					t.Fatal("Linux provider peer accepted on Windows")
				}
			}
			httpCalls := 0
			// Count direct management and fallback calls. The broker owns a separate
			// transport and is refused by its real platform guards above.
			s.http = &http.Client{Transport: windowsProviderTransport(func(*http.Request) (*http.Response, error) {
				httpCalls++
				return nil, errors.New("unexpected provider HTTP request")
			})}
			input := map[string]any{"requestId": "windows-refused", "preset": "zhipu", "key": submittedKey, "models": []string{"glm-5"}, "expectedRevision": "unconfirmed-revision"}
			for _, request := range []struct {
				method, path, code string
				status             int
				body               any
			}{
				{"GET", "/v1/provider-settings", "provider_unavailable", 503, nil},
				{"POST", "/v1/provider-settings", "provider_unavailable", 503, input},
				{"POST", "/v1/provider-settings/models", "provider_catalog_unavailable", 400, input},
			} {
				response := call(t, s, request.method, request.path, request.body)
				var envelope struct {
					Error struct {
						Code string `json:"code"`
					} `json:"error"`
				}
				if err := json.Unmarshal(response.Body.Bytes(), &envelope); err != nil || response.Code != request.status || envelope.Error.Code != request.code {
					t.Fatalf("%s %s: unexpected refusal status %d, code %q", request.method, request.path, response.Code, envelope.Error.Code)
				}
				if strings.Contains(response.Body.String(), credential) || strings.Contains(response.Body.String(), submittedKey) {
					t.Fatal("provider refusal exposed a credential")
				}
				if httpCalls != 0 {
					t.Fatal("unsupported provider management reached HTTP")
				}
				for _, path := range []string{s.providerFencePath(), s.providerReceiptPath("windows-refused"), filepath.Dir(s.providerReceiptPath("windows-refused"))} {
					if _, err := os.Lstat(path); !os.IsNotExist(err) {
						t.Fatal("rejected provider operation created a receipt or admission fence")
					}
				}
				for path, original := range originals {
					data, err := os.ReadFile(path)
					if err != nil || !bytes.Equal(data, original) {
						t.Fatal("rejected provider operation changed native configuration")
					}
				}
			}
		})
	}
}
