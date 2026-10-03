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

func TestStartupDelayFixture(t *testing.T) {
	if os.Getenv("LIFECYCLE_DELAY_FIXTURE") != "1" {
		return
	}
	// This synthetic owned child does nothing and exits normally. In particular,
	// it is delayed before opening any runtime lock or creating runtime identity.
	time.Sleep(700 * time.Millisecond)
}
func TestUnobservedChildBlocksStopUpdateAndDuplicateStart(t *testing.T) {
	root, c, args := lifecycleConfigFixture(t)
	if e := initialize(root, args, strings.NewReader("n\ny\n"), io.Discard); e != nil {
		t.Fatal(e)
	}
	if e := writeJSON(filepath.Join(root, "current.json"), Pointer{Version: "v1.2.3"}); e != nil {
		t.Fatal(e)
	}
	if _, e := managedDirectory(root, "credentials", "windows-node"); e != nil {
		t.Fatal(e)
	}
	mustWriteFixture(t, c.CredentialFile, []byte("inert credential fixture, never decrypted"))
	t.Setenv("LIFECYCLE_DELAY_FIXTURE", "1")
	e := startWith(root, io.Discard, func(string) *exec.Cmd { return exec.Command(os.Args[0], "-test.run=^TestStartupDelayFixture$") }, 10*time.Millisecond)
	if e == nil || !strings.Contains(e.Error(), "unknown") {
		t.Fatalf("stalled start = %v", e)
	}
	pending, e := readStartup(root)
	if e != nil || pending.Version != "v1.2.3" {
		t.Fatalf("startup intent missing: %v", e)
	}
	// Prove that this fixture has not acquired runtime.lock; the intent must be
	// what prevents the false 'stopped' result and an upgrade.
	guard, e := lockFile(filepath.Join(root, "runtime.lock"))
	if e != nil {
		t.Fatal(e)
	}
	guard.Close()
	if e = stop(root, io.Discard); e == nil {
		t.Fatal("stalled child was incorrectly reported stopped")
	}
	if e = update(root, []string{"--version", "v1.2.4"}, io.Discard); e == nil {
		t.Fatal("update ignored pending child")
	}
	called := false
	if e = startWith(root, io.Discard, func(string) *exec.Cmd { called = true; return nil }, time.Millisecond); e == nil || called {
		t.Fatal("duplicate startup was permitted")
	}
	if got, e := current(root); e != nil || got.Version != "v1.2.3" {
		t.Fatal("unknown startup switched version")
	}
	if got, e := loadConfig(root); e != nil || got.Node.StateDir != c.Node.StateDir {
		t.Fatal("unknown startup changed config")
	}
	// This test process remains alive to observe the exact child's normal exit.
	// In a CLI process that exits earlier, the retained intent remains fail-closed.
	until := time.Now().Add(5 * time.Second)
	for time.Now().Before(until) {
		if noPendingStartup(root) == nil {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("observed exact child exit did not clear its startup intent")
}
func TestOldChildCannotClearNewerStartupIntent(t *testing.T) {
	root := t.TempDir()
	if e := privateRoot(root); e != nil {
		t.Fatal(e)
	}
	old := strings.Repeat("a", 64)
	next := Startup{LaunchID: strings.Repeat("b", 64), Version: "v1.2.4"}
	if e := createStartup(root, next); e != nil {
		t.Fatal(e)
	}
	if e := clearStartup(root, old); e == nil {
		t.Fatal("old child claimed newer startup identity")
	}
	if p, e := readStartup(root); e != nil || p != next {
		t.Fatal("newer intent was cleared")
	}
	if e := createStartup(root, Startup{LaunchID: old, Version: "v1.2.3"}); e == nil {
		t.Fatal("unresolved intent was overwritten")
	}
	if e := clearStartup(root, next.LaunchID); e != nil {
		t.Fatal(e)
	}
	if e := noPendingStartup(root); e != nil {
		t.Fatal(e)
	}
}
