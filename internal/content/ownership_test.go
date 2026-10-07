//go:build linux || darwin

package content

import (
	"os"
	"path/filepath"
	"testing"
)

func TestPrivateLedgerOwnershipAndPaths(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, "ledger")
	t.Run("directory-trust", func(t *testing.T) {
		if err := validateDataDirectory(dir, true); err != nil {
			t.Skipf("executor ancestor ownership is unsuitable for production path validation: %v", err)
		}
		if err := os.Mkdir(dir, 0700); err != nil {
			t.Fatal(err)
		}
		defer os.Remove(dir)
		if err := validateDataDirectory(dir, false); err != nil {
			t.Fatal(err)
		}
		link := filepath.Join(root, "alias")
		if err := os.Symlink(dir, link); err != nil {
			t.Fatal(err)
		}
		if err := validateDataDirectory(filepath.Join(link, "nested"), true); err == nil {
			t.Fatal("symlink ancestor allowed")
		}
		if err := os.Chmod(dir, 0755); err != nil {
			t.Fatal(err)
		}
		if err := validateDataDirectory(dir, false); err == nil {
			t.Fatal("public data directory allowed")
		}
	})
	if err := os.Mkdir(dir, 0700); err != nil {
		t.Fatal(err)
	}
	lock, err := acquireContentLock(filepath.Join(dir, "content.lock"))
	if err != nil {
		t.Fatal(err)
	}
	defer lock()
	if duplicate, err := acquireContentLock(filepath.Join(dir, "content.lock")); err == nil {
		duplicate()
		t.Fatal("duplicate process ownership allowed")
	}
	private := filepath.Join(dir, "private")
	f, err := privateFile(private)
	if err != nil {
		t.Fatal(err)
	}
	f.Close()
	if err := os.Link(private, filepath.Join(dir, "hardlink")); err != nil {
		t.Fatal(err)
	}
	if f, err := privateFile(private); err == nil {
		f.Close()
		t.Fatal("multiply linked DB path allowed")
	}
	if err := os.Remove(filepath.Join(dir, "hardlink")); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(private, filepath.Join(dir, "symlink")); err != nil {
		t.Fatal(err)
	}
	if f, err := privateFile(filepath.Join(dir, "symlink")); err == nil {
		f.Close()
		t.Fatal("symlink DB file allowed")
	}
}
