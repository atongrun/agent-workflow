package lifecycle

import (
	"bytes"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestWorkspaceEnableRejectsJunctionEvenWhenCredentialPathMatches(t *testing.T) {
	root, cfg := workspaceEnableFixture(t)
	link := filepath.Join(t.TempDir(), "fixture-junction")
	target := filepath.Join(root, "private")
	if output, err := exec.Command("cmd.exe", "/c", "mklink", "/J", link, target).CombinedOutput(); err != nil {
		t.Fatalf("fixture junction creation failed: %v: %s", err, output)
	}
	defer os.Remove(link)
	cfg.Node.Projects["junction"] = link
	cfg.CredentialFile = link
	path := filepath.Join(root, "config.json")
	if err := writeJSON(path, cfg); err != nil {
		t.Fatal(err)
	}
	original, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := enableWorkspace(root, io.Discard); err == nil {
		t.Fatal("junction accepted when credential path matched")
	}
	after, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(original, after) {
		t.Fatal("rejection changed configuration")
	}
	if _, err := os.Stat(filepath.Join(target, "managed-workspaces")); !os.IsNotExist(err) {
		t.Fatal("rejection created workspace")
	}
}
