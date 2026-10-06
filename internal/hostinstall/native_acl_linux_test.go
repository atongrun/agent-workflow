//go:build linux

package hostinstall

import (
	"context"
	"encoding/binary"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
)

func setWritableDefaultACL(t *testing.T, dir string) []byte {
	t.Helper()
	// Linux POSIX ACL xattr version2, minimal owner/group/other entries, no IDs.
	b := make([]byte, 28)
	binary.LittleEndian.PutUint32(b, 2)
	for i, tag := range []uint16{1, 4, 32} {
		entry := b[4+i*8:]
		binary.LittleEndian.PutUint16(entry, tag)
		binary.LittleEndian.PutUint16(entry[2:], 7)
		binary.LittleEndian.PutUint32(entry[4:], ^uint32(0))
	}
	err := syscall.Setxattr(dir, "system.posix_acl_default", b, 0)
	if errors.Is(err, syscall.EOPNOTSUPP) {
		t.Skip("fixture filesystem does not support default ACLs")
	}
	if err != nil {
		t.Fatal(err)
	}
	return b
}

func readDefaultACL(t *testing.T, dir string) []byte {
	t.Helper()
	b := make([]byte, 4096)
	n, err := syscall.Getxattr(dir, "system.posix_acl_default", b)
	if errors.Is(err, syscall.ENODATA) || errors.Is(err, syscall.EOPNOTSUPP) {
		return nil
	}
	if err != nil {
		t.Fatal(err)
	}
	return b[:n]
}

func TestProgramStageIsolatesInheritedDefaultACL(t *testing.T) {
	parent := privateParent(t)
	original := setWritableDefaultACL(t, parent)
	stage, err := os.MkdirTemp(parent, ".new-stage-")
	if err != nil {
		t.Fatal(err)
	}
	before, _ := os.Stat(stage)
	if len(readDefaultACL(t, stage)) == 0 {
		t.Fatal("private stage did not inherit the default ACL")
	}
	root, err := os.OpenRoot(stage)
	if err != nil {
		t.Fatal(err)
	}
	defer root.Close()
	if err := isolateProgramStage(root); err != nil {
		t.Fatal(err)
	}
	if err := isolateProgramStage(root); err != nil {
		t.Fatal("absent default ACL must be idempotent", err)
	}
	after, _ := os.Stat(stage)
	if !os.SameFile(before, after) || after.Mode().Perm() != 0700 || len(readDefaultACL(t, stage)) != 0 || string(readDefaultACL(t, parent)) != string(original) {
		t.Fatal("stage identity/mode or parent ACL changed")
	}
	if err := root.Mkdir("program", 0755); err != nil {
		t.Fatal(err)
	}
	promoted := filepath.Join(parent, "promoted")
	if err := os.Rename(stage, promoted); err != nil {
		t.Fatal(err)
	}
	if len(readDefaultACL(t, promoted)) != 0 || len(readDefaultACL(t, filepath.Join(promoted, "program"))) != 0 {
		t.Fatal("promotion reintroduced a default ACL")
	}
}

func TestProgramStageRejectsNonPrivateTarget(t *testing.T) {
	for _, mode := range []os.FileMode{0755, 0777} {
		dir := privateParent(t)
		if err := os.Chmod(dir, mode); err != nil {
			t.Fatal(err)
		}
		root, err := os.OpenRoot(dir)
		if err != nil {
			t.Fatal(err)
		}
		if err := isolateProgramStage(root); err == nil {
			t.Fatal("non-private directory accepted")
		}
		root.Close()
	}
}

func TestNativeProgramStagesPreventInheritedDefaultACL(t *testing.T) {
	f := newNativeFixture(t)
	parent := filepath.Join(f.dir, "opt")
	original := setWritableDefaultACL(t, parent)
	f.install(t)
	check := func() {
		t.Helper()
		for _, name := range programRoots {
			err := filepath.WalkDir(filepath.Join(f.dir, name), func(path string, entry fs.DirEntry, err error) error {
				if err != nil {
					return err
				}
				if entry.IsDir() && len(readDefaultACL(t, path)) != 0 {
					t.Fatalf("installed program retained a default ACL: %s", name)
				}
				return nil
			})
			if err != nil {
				t.Fatal(err)
			}
		}
		if string(readDefaultACL(t, parent)) != string(original) {
			t.Fatal("shared parent default ACL changed")
		}
	}
	check()
	old, err := f.a.installed(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	f.m.SourceCommit = strings.Repeat("b", 40)
	newDir, receipt := nativePreparedFixture(t, f.m)
	if err := f.a.replacePrepared(context.Background(), f.m, newDir, receipt, old); err != nil {
		t.Fatal(err)
	}
	check()
}
