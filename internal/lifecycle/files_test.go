package lifecycle

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func mustWriteFixture(t *testing.T, path string, b []byte) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, b, 0600); err != nil {
		t.Fatal(err)
	}
}

func TestSwitchVersionCommitRollbackAndPreservation(t *testing.T) {
	for _, outcome := range []string{"success", "activation failure", "rollback activation failure", "activation unknown"} {
		t.Run(outcome, func(t *testing.T) {
			root := t.TempDir()
			old := Pointer{Version: "v1.2.3"}
			if err := writeJSON(filepath.Join(root, "current.json"), old); err != nil {
				t.Fatal(err)
			}
			sentinels := map[string][]byte{
				"config.json": []byte("configuration sentinel"),
				filepath.Join("credentials", "windows-node", "node-token.dpapi"): []byte("opaque credential sentinel; not a real secret"),
				filepath.Join("state", "jobs", "sentinel.json"):                  []byte("durable job sentinel"),
				filepath.Join("versions", "v1.2.3", "awf.exe"):                   []byte("old binary sentinel"),
				filepath.Join("versions", "v1.2.4", "awf.exe"):                   []byte("new binary sentinel"),
			}
			for p, b := range sentinels {
				mustWriteFixture(t, filepath.Join(root, p), b)
			}
			activated, rolledBack := 0, 0
			err := switchVersion(root, "v1.2.4", old, func() error {
				activated++
				if p, e := current(root); e != nil || p.Version != "v1.2.4" {
					t.Fatalf("activation saw pointer %+v, %v", p, e)
				}
				if outcome == "activation unknown" {
					return &activationUnknown{errors.New("runtime remains unverified")}
				}
				if outcome != "success" {
					return errors.New("synthetic activation failure")
				}
				return nil
			}, func() error {
				rolledBack++
				if p, e := current(root); e != nil || p != old {
					t.Fatalf("rollback saw pointer %+v, %v", p, e)
				}
				if outcome == "rollback activation failure" {
					return errors.New("synthetic restart failure")
				}
				return nil
			})
			if (err == nil) != (outcome == "success") {
				t.Fatalf("outcome %q: %v", outcome, err)
			}
			wantVersion, wantRollback := old.Version, 1
			if outcome == "success" || outcome == "activation unknown" {
				wantVersion, wantRollback = "v1.2.4", 0
			}
			if p, e := current(root); e != nil || p.Version != wantVersion {
				t.Fatalf("final pointer %+v, %v", p, e)
			}
			if activated != 1 || rolledBack != wantRollback {
				t.Fatalf("callback counts activate=%d rollback=%d", activated, rolledBack)
			}
			for p, want := range sentinels {
				got, e := os.ReadFile(filepath.Join(root, p))
				if e != nil || !bytes.Equal(got, want) {
					t.Errorf("preserved file %s changed: %q, %v", p, got, e)
				}
			}
		})
	}
}

func TestSwitchVersionRefusesBeforeActivation(t *testing.T) {
	for _, tc := range []struct {
		name, version string
		blocked       bool
	}{
		{"invalid tag", "../escape", false}, {"unwritable pointer", "v1.2.4", true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			root := t.TempDir()
			if tc.blocked {
				mustWriteFixture(t, filepath.Join(root, "current.json", "keep"), []byte("sentinel"))
			}
			called := false
			callback := func() error { called = true; return nil }
			if err := switchVersion(root, tc.version, Pointer{Version: "v1.2.3"}, callback, callback); err == nil {
				t.Fatal("unsafe switch accepted")
			}
			if called {
				t.Fatal("callback invoked before pointer commit")
			}
			entries, err := os.ReadDir(root)
			if err != nil {
				t.Fatal(err)
			}
			for _, entry := range entries {
				if strings.HasPrefix(entry.Name(), ".awf-") {
					t.Errorf("temporary pointer leaked: %s", entry.Name())
				}
			}
		})
	}
}

func TestSwitchVersionReportsPointerRollbackFailure(t *testing.T) {
	root := t.TempDir()
	p := filepath.Join(root, "current.json")
	if err := writeJSON(p, Pointer{Version: "v1.2.3"}); err != nil {
		t.Fatal(err)
	}
	rollbackCalled := false
	err := switchVersion(root, "v1.2.4", Pointer{Version: "v1.2.3"}, func() error {
		if err := os.Remove(p); err != nil {
			t.Fatal(err)
		}
		mustWriteFixture(t, filepath.Join(p, "block-replacement"), []byte("sentinel"))
		return errors.New("activation failed")
	}, func() error { rollbackCalled = true; return nil })
	if err == nil || !strings.Contains(err.Error(), "pointer rollback also failed") {
		t.Fatalf("rollback error lost: %v", err)
	}
	if rollbackCalled {
		t.Fatal("prior version activated without restoring its pointer")
	}
}

func TestAtomicWritePreservesDestinationOnFailure(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "pointer")
	mustWriteFixture(t, filepath.Join(path, "sentinel"), []byte("preserve"))
	if err := atomicWrite(path, []byte("replacement")); err == nil {
		t.Fatal("directory overwrite unexpectedly succeeded")
	}
	if got, err := os.ReadFile(filepath.Join(path, "sentinel")); err != nil || string(got) != "preserve" {
		t.Fatalf("destination changed: %q, %v", got, err)
	}
	entries, err := os.ReadDir(root)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 1 || entries[0].Name() != "pointer" {
		t.Fatalf("temporary files leaked: %v", entries)
	}
}

func TestReadBoundedAndStrictPointerJSON(t *testing.T) {
	root := t.TempDir()
	p := filepath.Join(root, "input")
	mustWriteFixture(t, p, []byte("123456789"))
	if _, err := readBounded(p, 8); err == nil {
		t.Fatal("oversized file accepted")
	}
	if got, err := readBounded(p, 9); err != nil || string(got) != "123456789" {
		t.Fatalf("exact limit = %q, %v", got, err)
	}
	if _, err := readBounded(root, 100); err == nil {
		t.Fatal("directory accepted as regular input")
	}
	for _, data := range []string{`{"version":"../escape"}`, `{"version":"v1.2.3","unknown":true}`, `{"version":"v1.2.3"}{}`, `{"version":"v1.2.3"}garbage`, `null`, `{}`} {
		mustWriteFixture(t, filepath.Join(root, "current.json"), []byte(data))
		if _, err := current(root); err == nil {
			t.Fatalf("invalid pointer accepted: %q", data)
		}
	}
	// Valid prefix followed by data beyond the old reader limit must not be accepted.
	mustWriteFixture(t, filepath.Join(root, "current.json"), []byte(`{"version":"v1.2.3"}`+strings.Repeat(" ", 2<<20)+`{}`))
	if _, err := current(root); err == nil {
		t.Fatal("oversized/trailing JSON accepted")
	}
}

func TestDefaultRootUsesProgramsKnownFolder(t *testing.T) {
	for _, value := range []string{"", "relative"} {
		if _, err := rootFromProgramsFolder(value, nil); err == nil {
			t.Fatalf("unsafe known folder accepted: %q", value)
		}
	}
	programs := filepath.Join(t.TempDir(), "Programs")
	if got, err := rootFromProgramsFolder(programs, nil); err != nil || got != filepath.Join(programs, "AWF") {
		t.Fatalf("default root=%q, %v", got, err)
	}
	if _, err := rootFromProgramsFolder(programs, os.ErrPermission); err == nil {
		t.Fatal("known folder failure ignored")
	}
	if _, err := os.Stat(programs); !os.IsNotExist(err) {
		t.Fatal("planning created Programs")
	}
}
