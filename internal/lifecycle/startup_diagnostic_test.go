package lifecycle

import (
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestStartupFailureFixture(t *testing.T) {
	if message := os.Getenv("LIFECYCLE_FAILURE_FIXTURE"); message != "" {
		_, _ = io.WriteString(os.Stderr, message+"\n")
		os.Exit(1)
	}
}

func TestStartMissingCredentialDoesNotSpawnOrCreateIntent(t *testing.T) {
	root, _, args := lifecycleConfigFixture(t)
	if err := initialize(root, args, strings.NewReader("n\ny\n"), io.Discard); err != nil {
		t.Fatal(err)
	}
	if err := writeJSON(filepath.Join(root, "current.json"), Pointer{Version: "v1.2.3"}); err != nil {
		t.Fatal(err)
	}
	called := false
	err := startWith(root, io.Discard, func(string) *exec.Cmd { called = true; return nil }, time.Second)
	if err == nil || !strings.Contains(err.Error(), "run awf pair") || called {
		t.Fatalf("missing credential did not fail before spawn: %v, called=%t", err, called)
	}
	if _, err := os.Stat(startupPath(root)); !os.IsNotExist(err) {
		t.Fatalf("missing credential created startup intent: %v", err)
	}
}

func TestStartReportsChildFailureWithoutLeakingStderr(t *testing.T) {
	for _, tc := range []struct{ name, message, want string }{
		{"port busy", "native OpenCode port is in use; refusing to adopt or stop another process", "127.0.0.1:4096 is unavailable"},
		{"unreadable credential", "paired node credential is missing or unreadable; run awf pair first", "check the configured path"},
		{"wrong user", "cannot decrypt paired node credential as this Windows user", "Windows account that paired"},
		{"privacy", "paired credential file must be private to the current user and SYSTEM, with no reparse point", "privacy checks failed"},
		{"native launch", "cannot start the configured native OpenCode executable", "verify the configured native .exe"},
		{"node bind", "cannot bind configured node interface", "IP belongs to this Windows machine"},
		{"secret", "SECRET_FIXTURE_TOKEN", "AWF runtime failed to start"},
		{"secret prefix", "SECRET_FIXTURE_TOKEN\nnative OpenCode port is in use; refusing to adopt or stop another process", "AWF runtime failed to start"},
		{"overflow", strings.Repeat("SECRET_FIXTURE_TOKEN", 300), "AWF runtime failed to start"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			root, c, args := lifecycleConfigFixture(t)
			if err := initialize(root, args, strings.NewReader("n\ny\n"), io.Discard); err != nil {
				t.Fatal(err)
			}
			if err := writeJSON(filepath.Join(root, "current.json"), Pointer{Version: "v1.2.3"}); err != nil {
				t.Fatal(err)
			}
			if _, err := managedDirectory(root, "credentials", "windows-node"); err != nil {
				t.Fatal(err)
			}
			const credential = "inert credential fixture, never decrypted"
			mustWriteFixture(t, c.CredentialFile, []byte(credential))
			t.Setenv("LIFECYCLE_FAILURE_FIXTURE", tc.message)
			err := startWith(root, io.Discard, func(string) *exec.Cmd {
				return exec.Command(os.Args[0], "-test.run=^TestStartupFailureFixture$")
			}, 10*time.Second)
			if err == nil || !strings.Contains(err.Error(), tc.want) || strings.Contains(err.Error(), "SECRET_FIXTURE_TOKEN") {
				t.Fatalf("failure = %v", err)
			}
			if err := noPendingStartup(root); err != nil {
				t.Fatalf("observed child did not clear intent: %v", err)
			}
			if b, err := os.ReadFile(c.CredentialFile); err != nil || string(b) != credential {
				t.Fatal("credential fixture changed")
			}
		})
	}
}
