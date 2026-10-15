package lifecycle

import (
	"bytes"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"syscall"
	"testing"
	"time"
	"unsafe"

	"github.com/atongrun/agent-workflow/internal/node"
	"github.com/atongrun/agent-workflow/internal/privatefile"
)

func TestWindowsNewPrivateFilesHaveExplicitOwnerAndNoninheritedDACL(t *testing.T) {
	root := ordinaryPermissionFixtureRoot(t)
	before := inspectDoctorACL(root)
	for _, kind := range []string{"file", "temporary", "lock"} {
		t.Run(kind, func(t *testing.T) {
			var f *os.File
			var err error
			switch kind {
			case "file":
				f, err = privatefile.Create(filepath.Join(root, "private-file"))
			case "temporary":
				f, err = privatefile.CreateTemp(root, ".private-")
			case "lock":
				f, err = privatefile.OpenLock(filepath.Join(root, "private.lock"))
			}
			if err != nil {
				t.Fatal(err)
			}
			defer f.Close()
			m := inspectDoctorACL(f.Name())
			if !m.Complete || m.OwnerSID != m.CurrentUserSID || m.CurrentUserSID == "" || m.Protected == nil || !*m.Protected || m.DACLState != "present" || len(m.Entries) != 2 {
				logWindowsPermissionMetadata(t, f.Name())
				t.Fatal("new private file owner/DACL contract is incomplete")
			}
			want := map[string]bool{m.CurrentUserSID: false, "S-1-5-18": false}
			for _, ace := range m.Entries {
				seen, allowed := want[ace.SID]
				if !allowed || seen || ace.Type != 0 || ace.Flags != 0 || ace.Mask != "0x001f01ff" {
					logWindowsPermissionMetadata(t, f.Name())
					t.Fatal("new private file grants anything other than current-user/SYSTEM full control")
				}
				want[ace.SID] = true
			}
			var flags uint32
			ok, _, _ := syscall.NewLazyDLL("kernel32.dll").NewProc("GetHandleInformation").Call(f.Fd(), uintptr(unsafe.Pointer(&flags)))
			if ok == 0 || flags&1 != 0 {
				t.Fatal("private file handle is inheritable or cannot be inspected")
			}
			if err = checkPrivatePath(f.Name()); err != nil {
				t.Fatal(err)
			}
		})
	}
	if after := inspectDoctorACL(root); !reflect.DeepEqual(before, after) {
		t.Fatal("creating private files changed the operator-provided parent")
	}
}

func TestWindowsPrivateCreateAndExistingLockNeverRepairOrReplace(t *testing.T) {
	root := privatePermissionFixtureRoot(t)
	path := filepath.Join(root, "existing.lock")
	want := []byte("synthetic existing identity")
	mustWritePrivateFixture(t, path, want)
	setBroadFixtureACL(t, path)
	before := inspectDoctorACL(path)
	if f, err := privatefile.Create(path); !os.IsExist(err) {
		if f != nil {
			f.Close()
		}
		t.Fatal("exclusive private creation did not refuse the existing object")
	}
	f, err := privatefile.OpenLock(path)
	if err != nil {
		t.Fatal(err)
	}
	if err = f.Close(); err != nil {
		t.Fatal(err)
	}
	if got, err := os.ReadFile(path); err != nil || !bytes.Equal(got, want) {
		t.Fatal("opening an existing lock truncated or replaced its contents")
	}
	if after := inspectDoctorACL(path); !reflect.DeepEqual(before, after) {
		t.Fatal("existing lock owner or ACL was changed")
	}
	if err = checkPrivatePath(path); err == nil {
		t.Fatal("broad existing ACL was silently repaired or accepted as private")
	}
	if f, err := privatefile.Create(root); err == nil {
		f.Close()
		t.Fatal("private creation replaced an existing directory")
	}
}

func TestWindowsPrivateCreateRefusesDanglingSymlinkWithoutChangingIt(t *testing.T) {
	root := t.TempDir()
	target := filepath.Join(root, "absent-target")
	link := filepath.Join(root, "dangling-link")
	if err := os.Symlink(target, link); err != nil {
		const errorPrivilegeNotHeld syscall.Errno = 1314
		if errors.Is(err, errorPrivilegeNotHeld) {
			t.Skip("Windows symlink fixture requires symbolic-link privilege or Developer Mode")
		}
		t.Fatalf("create dangling symlink fixture: %v", err)
	}
	before, err := os.Lstat(link)
	if err != nil || before.Mode()&os.ModeSymlink == 0 {
		t.Fatal("fixture is not a dangling symlink")
	}
	beforeTarget, err := os.Readlink(link)
	if err != nil {
		t.Fatal(err)
	}
	f, createErr := privatefile.Create(link)
	if f != nil {
		f.Close()
	}
	if createErr == nil {
		t.Error("exclusive private creation followed a dangling symlink")
	}
	if _, err := os.Lstat(target); !os.IsNotExist(err) {
		t.Error("exclusive private creation created or changed the missing target")
	}
	after, err := os.Lstat(link)
	if err != nil || after.Mode()&os.ModeSymlink == 0 || !os.SameFile(before, after) {
		t.Fatal("exclusive private creation replaced or removed the symlink")
	}
	if afterTarget, err := os.Readlink(link); err != nil || afterTarget != beforeTarget {
		t.Fatal("exclusive private creation changed the symlink target")
	}
}

func TestWindowsPrivateJSONRefusesUnsafeExistingObjectsWithoutRepair(t *testing.T) {
	for _, target := range []string{"file", "parent"} {
		t.Run(target, func(t *testing.T) {
			root := privatePermissionFixtureRoot(t)
			path := filepath.Join(root, "runtime.json")
			want := []byte("preserve existing synthetic bytes")
			object := root
			if target == "file" {
				mustWritePrivateFixture(t, path, want)
				object = path
			}
			setBroadFixtureACL(t, object)
			before := inspectDoctorACL(object)
			if err := writePrivateJSON(path, map[string]string{"replacement": "forbidden"}); err == nil {
				t.Fatal("unsafe existing object accepted by private identity writer")
			}
			if after := inspectDoctorACL(object); !reflect.DeepEqual(before, after) {
				t.Fatal("private identity writer repaired an existing ACL")
			}
			if target == "file" {
				if got, err := os.ReadFile(path); err != nil || !bytes.Equal(got, want) {
					t.Fatal("unsafe existing file was replaced")
				}
			} else if _, err := os.Stat(path); !os.IsNotExist(err) {
				t.Fatal("unsafe parent accepted a new private identity")
			}
			entries, err := os.ReadDir(root)
			if err != nil || len(entries) != map[string]int{"file": 1, "parent": 0}[target] {
				t.Fatal("refusal left a temporary file")
			}
		})
	}
}

func TestWindowsProgramJSONKeepsInheritedProgramPermissions(t *testing.T) {
	root := ordinaryPermissionFixtureRoot(t)
	before := inspectDoctorACL(root)
	for _, name := range []string{"config.json", "channel.json", "current.json"} {
		path := filepath.Join(root, name)
		if err := writeJSON(path, map[string]string{"fixture": "program"}); err != nil {
			t.Fatal(err)
		}
		if err := checkProgramPath(path); err != nil {
			t.Fatal(err)
		}
		m := inspectDoctorACL(path)
		if m.Protected == nil || *m.Protected || checkPrivatePath(path) == nil {
			t.Fatal("ordinary program writer adopted the private-file ACL policy")
		}
	}
	if after := inspectDoctorACL(root); !reflect.DeepEqual(before, after) {
		t.Fatal("program write changed the existing parent descriptor")
	}
}

func TestWindowsNodeCreatesPrivateJobRecordsAndLock(t *testing.T) {
	root := privatePermissionFixtureRoot(t)
	jobs, err := managedDirectory(root, "state", "jobs")
	if err != nil {
		t.Fatal(err)
	}
	before := inspectDoctorACL(filepath.Dir(jobs))
	// Only a local synthetic HTTP receiver; no native process, model, or Git.
	native := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "synthetic native unavailable", http.StatusServiceUnavailable)
	}))
	t.Cleanup(native.Close)
	const token = "private-file-fixture-bearer-32-characters"
	h, err := node.New(node.Config{Token: token, StateDir: filepath.Dir(jobs), Projects: map[string]string{"fixture": t.TempDir()}, OpenCodeURL: native.URL, HTTPClient: &http.Client{Timeout: time.Second}})
	if err != nil {
		t.Fatal(err)
	}
	s := h.(*node.Server)
	t.Cleanup(func() { _ = s.Close() })
	body, err := json.Marshal(node.JobRequest{RequestID: "private-file-job", TaskID: "fixture-task", ProjectID: "fixture", Repository: "fixture/repository", Branch: "awf/fixture", Plan: "inert fixture", Prompt: "inert fixture", TimeoutSeconds: 60})
	if err != nil {
		t.Fatal(err)
	}
	req := httptest.NewRequest(http.MethodPost, "/v1/jobs", bytes.NewReader(body))
	req.RemoteAddr = "127.0.0.1:1234"
	req.Header.Set("Authorization", "Bearer "+token)
	reply := httptest.NewRecorder()
	h.ServeHTTP(reply, req)
	if reply.Code != http.StatusAccepted {
		t.Fatalf("synthetic job admission status=%d", reply.Code)
	}
	if err = s.Close(); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{filepath.Join(filepath.Dir(jobs), "node.lock"), filepath.Join(jobs, node.JobID("private-file-job")+".json")} {
		if err = checkPrivatePath(path); err != nil {
			logWindowsPermissionMetadata(t, path)
			t.Fatal("native Node file creation violated the private owner/DACL contract")
		}
	}
	if after := inspectDoctorACL(filepath.Dir(jobs)); !reflect.DeepEqual(before, after) {
		t.Fatal("Node changed the supplied state directory descriptor")
	}
}
