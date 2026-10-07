//go:build linux

package main

import (
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/atongrun/agent-workflow/internal/durablebridge"
	"github.com/atongrun/agent-workflow/internal/host"
)

func TestOneHostListenerKeepsNativeContentCredentialScope(t *testing.T) {
	const hostToken = "fixture-host-token-123456789012"
	const extensionToken = "fixture-extension-token-123456"
	const contentToken = "fixture-content-token-12345678"
	t.Setenv("AWF_CMD_HOST", hostToken)
	t.Setenv("AWF_CMD_EXTENSION", extensionToken)
	t.Setenv("AWF_CMD_CONTENT", contentToken)
	app, err := host.New(host.Config{DataDir: t.TempDir(), TokenEnv: "AWF_CMD_HOST", ExtensionTokenEnv: "AWF_CMD_EXTENSION", InternalURL: "http://127.0.0.1:7070"})
	if err != nil {
		t.Fatal(err)
	}
	defer app.Close()
	dir, err := os.MkdirTemp("/tmp", "awf-host-uds-")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(dir)
	socket := filepath.Join(dir, "worker.sock")
	listener, err := net.Listen("unix", socket)
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	if err := os.Chmod(socket, 0600); err != nil {
		t.Fatal(err)
	}
	native := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get(durablebridge.OwnerHeader) != "fixture-owner" || r.Header.Get("Authorization") != "" {
			t.Error("authentication was not kept at Host boundary")
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"version":1,"durableVersion":"1.0.4","ready":true}`))
	}), ReadHeaderTimeout: time.Second}
	go native.Serve(listener)
	defer native.Close()
	client, err := durablebridge.NewUnixClient(socket, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	content, err := client.Handler([]durablebridge.Credential{{Owner: "fixture-owner", TokenEnv: "AWF_CMD_CONTENT"}}, hostToken, extensionToken)
	if err != nil {
		t.Fatal(err)
	}
	combined := composeHostHandler(app.Handler(), content)
	for _, test := range []struct {
		path, token string
		status      int
	}{
		{"/v1/health", hostToken, 200}, {"/v1/health", contentToken, 401}, {"/v1/content/health", contentToken, 200}, {"/v1/content/health", hostToken, 401}, {"/v1/content/health", extensionToken, 401},
	} {
		r := httptest.NewRequest("GET", test.path, nil)
		r.Header.Set("Authorization", "Bearer "+test.token)
		r.Header.Set(durablebridge.OwnerHeader, "browser-owner")
		w := httptest.NewRecorder()
		combined.ServeHTTP(w, r)
		if w.Code != test.status {
			t.Fatal(test.path, w.Code, w.Body.String())
		}
	}
}
