package lifecycle

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

func TestManagedTreeRejectsLinkedVersions(t *testing.T) {
	root := t.TempDir()
	outside := t.TempDir()
	if e := privateRoot(root); e != nil {
		t.Fatal(e)
	}
	if e := os.Symlink(outside, filepath.Join(root, "versions")); e != nil {
		t.Skipf("fixture symlink unavailable: %v", e)
	}
	if e := privateRoot(root); e == nil {
		t.Fatal("private root adopted linked versions")
	}
	if e := validateInstallRoot(root); e == nil {
		t.Fatal("launcher validation adopted linked versions")
	}
	if _, e := managedDirectory(root, "versions"); e == nil {
		t.Fatal("staging accepted linked versions")
	}
	entries, e := os.ReadDir(outside)
	if e != nil || len(entries) != 0 {
		t.Fatal("external linked directory was changed")
	}
}
func TestManagedTreeRejectsLinkedFiles(t *testing.T) {
	root := t.TempDir()
	outside := filepath.Join(t.TempDir(), "other")
	if e := privateRoot(root); e != nil {
		t.Fatal(e)
	}
	if e := os.WriteFile(outside, []byte("preserve"), 0600); e != nil {
		t.Fatal(e)
	}
	if e := os.Symlink(outside, filepath.Join(root, "current.json")); e != nil {
		t.Skipf("fixture symlink unavailable: %v", e)
	}
	if e := validateInstallRoot(root); e == nil {
		t.Fatal("launcher accepted linked pointer file")
	}
	b, e := os.ReadFile(outside)
	if e != nil || string(b) != "preserve" {
		t.Fatal("external linked file was changed")
	}
}
func TestManagedTreeRejectsBroadExistingChild(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("native protected-DACL fixture covers Windows")
	}
	root := t.TempDir()
	if e := privateRoot(root); e != nil {
		t.Fatal(e)
	}
	child := filepath.Join(root, "versions")
	if e := os.Mkdir(child, 0700); e != nil {
		t.Fatal(e)
	}
	if e := os.Chmod(child, 0777); e != nil {
		t.Fatal(e)
	}
	if e := privateRoot(root); e == nil {
		t.Fatal("private parent masked a broad child")
	}
	if _, e := managedDirectory(root, "versions"); e == nil {
		t.Fatal("staging accepted broad child")
	}
}
