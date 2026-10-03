package lifecycle

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func doctorFixture(local string) doctorPlatform {
	return doctorPlatform{
		context:      func() (string, string) { return "unpackaged", "fixture" },
		localAppData: func() (string, error) { return local, nil },
		physical:     func(p string) (string, error) { return p, nil },
		acl:          func(string) (string, error) { return "fixture metadata", nil },
		reparse:      func(string) error { return nil },
	}
}
func doctorNoCommand(string) (string, error) { return "", errors.New("missing") }
func doctorHas(r doctorReport, check, status string) bool {
	for _, f := range r.Findings {
		if f.Check == check && f.Status == status {
			return true
		}
	}
	return false
}
func doctorSnapshot(t *testing.T, root string) map[string]string {
	t.Helper()
	m := map[string]string{}
	err := filepath.WalkDir(root, func(p string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		st, err := d.Info()
		if err != nil {
			return err
		}
		m[p] = st.Mode().String() + st.ModTime().String()
		if st.Mode().IsRegular() {
			b, err := os.ReadFile(p)
			if err != nil {
				return err
			}
			m[p] += string(b)
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return m
}
func TestDoctorZeroWritesPartialAndMalformedRoots(t *testing.T) {
	for _, fixture := range []string{"absent", "empty", "credentials-only", "malformed", "runtime"} {
		t.Run(fixture, func(t *testing.T) {
			local := t.TempDir()
			root := filepath.Join(local, "AWF")
			if fixture != "absent" {
				if err := os.Mkdir(root, 0700); err != nil {
					t.Fatal(err)
				}
			}
			switch fixture {
			case "credentials-only":
				p := filepath.Join(root, "credentials", "windows-node")
				if err := os.MkdirAll(p, 0700); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(filepath.Join(p, "node-token.dpapi"), []byte("DO-NOT-READ-SECRET"), 0600); err != nil {
					t.Fatal(err)
				}
			case "malformed":
				if err := os.Mkdir(filepath.Join(root, "current.json"), 0700); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(filepath.Join(root, "config.json"), []byte("malformed SECRET configuration"), 0600); err != nil {
					t.Fatal(err)
				}
			case "runtime":
				for _, p := range []string{"runtime.json", "starting.json"} {
					if err := os.WriteFile(filepath.Join(root, p), []byte(`{"token":"SECRET"}`), 0600); err != nil {
						t.Fatal(err)
					}
				}
			}
			before := doctorSnapshot(t, local)
			report := inspectDoctor(local, doctorFixture(local), doctorNoCommand)
			if !reflect.DeepEqual(before, doctorSnapshot(t, local)) {
				t.Fatal("doctor changed the tree")
			}
			b, err := json.Marshal(report)
			if err != nil {
				t.Fatal(err)
			}
			if strings.Contains(string(b), "SECRET") {
				t.Fatal("file contents leaked")
			}
			if fixture == "absent" && !doctorHas(report, "root", "missing") {
				t.Fatal(report)
			}
			if fixture == "malformed" && !doctorHas(report, "current.json", "mismatch") {
				t.Fatal(report)
			}
		})
	}
}
func TestDoctorAggregatesUnknownAndMismatch(t *testing.T) {
	local := t.TempDir()
	root := filepath.Join(local, "AWF")
	if err := os.Mkdir(root, 0700); err != nil {
		t.Fatal(err)
	}
	p := doctorFixture(local)
	p.context = func() (string, string) { return "packaged", "fixture" }
	p.localAppData = func() (string, error) { return "", errors.New("unknown") }
	p.physical = func(string) (string, error) { return filepath.Join(local, "redirected"), nil }
	p.acl = func(string) (string, error) { return "ACL unavailable", errors.New("unknown") }
	r := inspectDoctor(local, p, func(string) (string, error) { return filepath.Join(local, "other.exe"), nil })
	for _, want := range [][2]string{{"package-context", "packaged"}, {"profile", "unknown"}, {"root.physical", "mismatch"}, {"root.acl", "unknown"}, {"launcher-resolution", "mismatch"}} {
		if !doctorHas(r, want[0], want[1]) {
			t.Fatalf("missing %v: %+v", want, r)
		}
	}
}
func TestDoctorRejectsReparseBeforeQuery(t *testing.T) {
	local := t.TempDir()
	root := filepath.Join(local, "AWF")
	if err := os.Mkdir(root, 0700); err != nil {
		t.Fatal(err)
	}
	p := doctorFixture(local)
	p.reparse = func(path string) error {
		if path == root {
			return errors.New("reparse")
		}
		return nil
	}
	p.physical = func(string) (string, error) { t.Fatal("queried blocked tree"); return "", nil }
	p.acl = func(string) (string, error) { t.Fatal("inspected blocked tree"); return "", nil }
	r := inspectDoctor(local, p, doctorNoCommand)
	if !doctorHas(r, "root", "unknown") {
		t.Fatal(r)
	}
}
func TestDoctorDispatchAndOutput(t *testing.T) {
	t.Setenv("LOCALAPPDATA", "")
	if handled, err := Forward([]string{"doctor"}); handled || err != nil {
		t.Fatal(handled, err)
	}
	var out bytes.Buffer
	if err := Run([]string{"doctor", "--json"}, nil, &out); err != nil {
		t.Fatal(err)
	}
	var r doctorReport
	if err := json.Unmarshal(out.Bytes(), &r); err != nil {
		t.Fatal(err)
	}
	if r.Schema != 1 || !doctorHas(r, "root", "unknown") {
		t.Fatal(r)
	}
	out.Reset()
	if err := Run([]string{"doctor", "--repair"}, nil, &out); err == nil {
		t.Fatal("repair flag accepted")
	}
}

type doctorBrokenWriter struct{}

func (doctorBrokenWriter) Write([]byte) (int, error) { return 0, errors.New("output unavailable") }
func TestDoctorOutputFailure(t *testing.T) {
	t.Setenv("LOCALAPPDATA", "")
	for _, args := range [][]string{{"doctor"}, {"doctor", "--json"}} {
		if err := Run(args, nil, doctorBrokenWriter{}); err == nil {
			t.Fatal("output failure hidden", args)
		}
	}
}
