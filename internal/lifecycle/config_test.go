package lifecycle

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/atongrun/agent-workflow/internal/node"
)

func lifecycleConfigFixture(t *testing.T) (string, Config, []string) {
	t.Helper()
	base := t.TempDir()
	root, workspace, binary := filepath.Join(base, "AWF"), filepath.Join(base, "workspace"), filepath.Join(base, "OpenCode.exe")
	if err := os.MkdirAll(workspace, 0700); err != nil {
		t.Fatal(err)
	}
	mustWriteFixture(t, binary, []byte("MZ inert configuration fixture"))
	c := Config{Schema: 1, OpenCodeBinary: binary, CredentialFile: filepath.Join(root, "credentials", "windows-node", "node-token.dpapi"), Node: node.Config{StateDir: filepath.Join(root, "state"), ListenAddress: "127.0.0.1:7071", OpenCodeURL: "http://127.0.0.1:4096", Projects: map[string]string{"acceptance": workspace}}}
	return root, c, []string{"--workspace", workspace, "--opencode", binary}
}

func TestInitRequiresExplicitReviewAndSave(t *testing.T) {
	for _, answer := range []string{"", "n", "n\n", "n\nn\n", "y\nn\n", "yes\n\n", "no\ny"} {
		t.Run(strings.ReplaceAll(answer, "\n", "_"), func(t *testing.T) {
			root, _, args := lifecycleConfigFixture(t)
			var out bytes.Buffer
			if err := initialize(root, args, strings.NewReader(answer), &out); err == nil {
				t.Fatal("init accepted incomplete/cancelled review")
			}
			if _, err := os.Stat(root); !os.IsNotExist(err) {
				t.Fatalf("cancelled init changed installation: %v", err)
			}
		})
	}
}

func TestInitSaveRequiresAndDisplaysExactReview(t *testing.T) {
	root, c, args := lifecycleConfigFixture(t)
	var out bytes.Buffer
	if err := initialize(root, args, strings.NewReader("n\nyes\n"), &out); err != nil {
		t.Fatal(err)
	}
	for _, expected := range []string{root, c.OpenCodeBinary, c.CredentialFile, c.Node.Projects["acceptance"], c.Node.StateDir, c.Node.ListenAddress, "Login autostart: false", "Save this exact configuration?"} {
		if !strings.Contains(out.String(), expected) {
			t.Errorf("review omitted %q", expected)
		}
	}
	got, err := loadConfig(root)
	if err != nil {
		t.Fatal(err)
	}
	if got.Autostart || got.Node.Token != "" || got.Node.OpenCodePassword != "" || got.Node.OpenCodeUsername != "" {
		t.Fatalf("init unexpectedly enabled autostart or credentials: %+v", got)
	}
	entries, err := os.ReadDir(filepath.Join(c.Node.StateDir, "jobs"))
	if err != nil || len(entries) != 0 {
		t.Fatalf("initial job store = %v, %v", entries, err)
	}
	if _, err := os.Stat(c.CredentialFile); !os.IsNotExist(err) {
		t.Fatalf("init created credentials: %v", err)
	}
	before, err := os.ReadFile(filepath.Join(root, "config.json"))
	if err != nil {
		t.Fatal(err)
	}
	if err = initialize(root, args, strings.NewReader("n\ny\n"), &out); err == nil {
		t.Fatal("existing configuration overwritten")
	}
	after, err := os.ReadFile(filepath.Join(root, "config.json"))
	if err != nil || !bytes.Equal(before, after) {
		t.Fatalf("configuration changed on repeated init: %v", err)
	}
}

func TestValidateConfigRejectsUnsafeConfiguration(t *testing.T) {
	cases := []struct {
		name   string
		mutate func(string, *Config)
	}{
		{"unknown schema", func(_ string, c *Config) { c.Schema = 2 }},
		{"inline token", func(_ string, c *Config) { c.Node.Token = "secret" }},
		{"inline native password", func(_ string, c *Config) { c.Node.OpenCodePassword = "secret" }},
		{"inline native username", func(_ string, c *Config) { c.Node.OpenCodeUsername = "name" }},
		{"external state", func(_ string, c *Config) { c.Node.StateDir = filepath.Dir(c.Node.StateDir) }},
		{"remote OpenCode", func(_ string, c *Config) { c.Node.OpenCodeURL = "http://192.0.2.1:4096" }},
		{"relative executable", func(_ string, c *Config) { c.OpenCodeBinary = "OpenCode.exe" }},
		{"shell wrapper", func(_ string, c *Config) { c.OpenCodeBinary += ".cmd" }},
		{"missing executable", func(_ string, c *Config) { c.OpenCodeBinary += ".missing.exe" }},
		{"relative credential", func(_ string, c *Config) { c.CredentialFile = "token.dpapi" }},
		{"no workspace", func(_ string, c *Config) { c.Node.Projects = nil }},
		{"relative workspace", func(_ string, c *Config) { c.Node.Projects["acceptance"] = "workspace" }},
		{"empty project", func(_ string, c *Config) {
			p := c.Node.Projects["acceptance"]
			c.Node.Projects = map[string]string{" ": p}
		}},
		{"wildcard listen", func(_ string, c *Config) { c.Node.ListenAddress = "0.0.0.0:7071" }},
		{"wildcard IPv6", func(_ string, c *Config) { c.Node.ListenAddress = "[::]:7071" }},
		{"zero port", func(_ string, c *Config) { c.Node.ListenAddress = "127.0.0.1:0" }},
		{"hostname listener", func(_ string, c *Config) { c.Node.ListenAddress = "localhost:7071" }},
		{"remote without allowlist", func(_ string, c *Config) { c.Node.ListenAddress = "192.0.2.1:7071" }},
		{"CIDR allowlist", func(_ string, c *Config) { c.Node.AllowedSourceIPs = []string{"192.0.2.0/24"} }},
		{"hostname allowlist", func(_ string, c *Config) { c.Node.AllowedSourceIPs = []string{"control.example"} }},
		{"wildcard allowlist", func(_ string, c *Config) { c.Node.AllowedSourceIPs = []string{"0.0.0.0"} }},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			root, c, _ := lifecycleConfigFixture(t)
			tc.mutate(root, &c)
			if err := validateConfig(root, c); err == nil {
				t.Fatal("unsafe configuration accepted")
			}
		})
	}
}
