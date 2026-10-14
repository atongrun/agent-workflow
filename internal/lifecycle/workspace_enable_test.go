package lifecycle

import (
	"bytes"
	"errors"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func workspaceEnableFixture(t *testing.T) (string, Config) {
	t.Helper()
	root, cfg, args := lifecycleConfigFixture(t)
	if err := initialize(root, args, strings.NewReader("n\ny\n"), io.Discard); err != nil {
		t.Fatal(err)
	}
	if _, err := managedDirectory(root, "private"); err != nil {
		t.Fatal(err)
	}
	if err := atomicWrite(filepath.Join(cfg.Node.StateDir, "node.lock"), nil); err != nil {
		t.Fatal(err)
	}
	return root, cfg
}
func TestWorkspaceEnablePreservesConfigurationAndIsIdempotent(t *testing.T) {
	root, before := workspaceEnableFixture(t)
	if _, e := managedDirectory(root, "credentials", "windows-node"); e != nil {
		t.Fatal(e)
	}
	credential := []byte("inert fixture credential; never decrypt or expose")
	if e := atomicWrite(before.CredentialFile, credential); e != nil {
		t.Fatal(e)
	}
	lock, e := exclusive(root)
	if e != nil {
		t.Fatal(e)
	}
	defer lock.Close()
	target := filepath.Join(root, "private", "managed-workspaces")
	var out bytes.Buffer
	if e := enableWorkspace(root, &out); e != nil {
		t.Fatal(e)
	}
	got, e := loadConfig(root)
	if e != nil {
		t.Fatal(e)
	}
	before.Node.ManagedRoot = target
	if !reflect.DeepEqual(got, before) {
		t.Fatal("settings other than managed root changed")
	}
	if e := checkPrivatePath(target); e != nil {
		t.Fatal(e)
	}
	if e := enableWorkspace(root, &out); e != nil {
		t.Fatal(e)
	}
	entries, e := os.ReadDir(target)
	if e != nil || len(entries) != 0 {
		t.Fatal("workspace eagerly prepared or changed data")
	}
	if strings.Contains(out.String(), root) || strings.Contains(out.String(), before.CredentialFile) {
		t.Fatal("command exposed internal paths")
	}
	preserved, e := os.ReadFile(before.CredentialFile)
	if e != nil || !bytes.Equal(credential, preserved) {
		t.Fatal("existing credential identity changed")
	}
	if strings.Contains(out.String(), string(credential)) {
		t.Fatal("command exposed credential content")
	}
}
func TestWorkspaceEnableSaveFailureRestoresOriginalBytes(t *testing.T) {
	root, _ := workspaceEnableFixture(t)
	p := filepath.Join(root, "config.json")
	original, e := os.ReadFile(p)
	if e != nil {
		t.Fatal(e)
	}
	fail := func(path string, data []byte) error {
		if e := atomicWrite(path, data); e != nil {
			return e
		}
		return errors.New("synthetic post-write failure")
	}
	if e := enableWorkspaceWith(root, io.Discard, fail); e == nil {
		t.Fatal("save failure accepted")
	}
	after, e := os.ReadFile(p)
	if e != nil || !bytes.Equal(original, after) {
		t.Fatal("original configuration was not restored")
	}
	if _, e := os.Stat(filepath.Join(root, "private", "managed-workspaces")); !os.IsNotExist(e) {
		t.Fatal("failed attempt left default workspace")
	}
}
func TestWorkspaceEnableRejectsExistingContentAndActiveOwnership(t *testing.T) {
	for _, kind := range []string{"existing", "runtime", "startup", "state-lock", "other-root", "reserved-id", "overlap"} {
		t.Run(kind, func(t *testing.T) {
			root, cfg := workspaceEnableFixture(t)
			p := filepath.Join(root, "config.json")
			var held *os.File
			switch kind {
			case "existing":
				if _, e := managedDirectory(root, "private", "managed-workspaces"); e != nil {
					t.Fatal(e)
				}
			case "runtime":
				if e := writeJSON(runtimePath(root), Runtime{Version: "v1.2.3"}); e != nil {
					t.Fatal(e)
				}
			case "startup":
				if e := createStartup(root, Startup{LaunchID: strings.Repeat("a", 64), Version: "v1.2.3"}); e != nil {
					t.Fatal(e)
				}
			case "state-lock":
				var e error
				held, e = lockFile(filepath.Join(cfg.Node.StateDir, "node.lock"))
				if e != nil {
					t.Fatal(e)
				}
				defer held.Close()
			case "reserved-id":
				cfg.Node.Projects["managed"] = t.TempDir()
				if e := writeJSON(p, cfg); e != nil {
					t.Fatal(e)
				}
			case "overlap":
				cfg.Node.Projects["overlap"] = filepath.Join(root, "private")
				if e := writeJSON(p, cfg); e != nil {
					t.Fatal(e)
				}
			case "other-root":
				cfg.Node.ManagedRoot = t.TempDir()
				if e := writeJSON(p, cfg); e != nil {
					t.Fatal(e)
				}
			}
			original, e := os.ReadFile(p)
			if e != nil {
				t.Fatal(e)
			}
			if e := enableWorkspace(root, io.Discard); e == nil {
				t.Fatal("unsafe state accepted")
			}
			after, e := os.ReadFile(p)
			if e != nil || !bytes.Equal(original, after) {
				t.Fatal("rejected operation changed configuration")
			}
		})
	}
}

func TestWorkspaceEnableRejectsResolvedProjectOverlap(t *testing.T) {
	root, cfg := workspaceEnableFixture(t)
	link := filepath.Join(t.TempDir(), "project-link")
	if e := os.Symlink(filepath.Join(root, "private"), link); e != nil {
		t.Skipf("symlink unavailable: %v", e)
	}
	cfg.Node.Projects["linked"] = link
	p := filepath.Join(root, "config.json")
	if e := writeJSON(p, cfg); e != nil {
		t.Fatal(e)
	}
	original, e := os.ReadFile(p)
	if e != nil {
		t.Fatal(e)
	}
	if e := enableWorkspace(root, io.Discard); e == nil {
		t.Fatal("resolved overlap accepted")
	}
	after, e := os.ReadFile(p)
	if e != nil || !bytes.Equal(original, after) {
		t.Fatal("rejection changed configuration")
	}
	if _, e := os.Stat(filepath.Join(root, "private", "managed-workspaces")); !os.IsNotExist(e) {
		t.Fatal("rejection created workspace")
	}
}
