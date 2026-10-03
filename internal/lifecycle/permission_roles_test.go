package lifecycle

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func permissionMetadataFixture() doctorACLMetadata {
	return doctorACLMetadata{OwnerSID: "S-1-5-21-1001", CurrentUserSID: "S-1-5-21-1001", DACLState: "present", Complete: true, Entries: []doctorACE{
		{SID: "S-1-5-21-1001", Mask: "0x001f01ff", Flags: 0x13},
		{SID: "S-1-5-18", Mask: "0x001f01ff", Flags: 0x13},
	}}
}

func TestPermissionRolePolicy(t *testing.T) {
	for _, tc := range []struct {
		name string
		role permissionRole
		edit func(*doctorACLMetadata)
		ok   bool
	}{
		{"private exact", privatePermissionRole, func(*doctorACLMetadata) {}, true},
		{"program exact", programPermissionRole, func(*doctorACLMetadata) {}, true},
		{"program builtin administrators", programPermissionRole, func(m *doctorACLMetadata) {
			m.OwnerSID = "S-1-5-32-544"
			m.Entries = append(m.Entries, doctorACE{SID: "S-1-5-32-544", Mask: "0x001f01ff", Flags: 0x13})
		}, true},
		{"program current user write", programPermissionRole, func(m *doctorACLMetadata) { m.Entries[0].Mask = "0x40000000" }, true},
		{"program inherited users read execute", programPermissionRole, func(m *doctorACLMetadata) {
			m.Entries = append(m.Entries, doctorACE{SID: "S-1-5-32-545", Mask: "0x001200a9", Flags: 0x13})
		}, true},
		{"program inherited app packages generic read", programPermissionRole, func(m *doctorACLMetadata) {
			m.Entries = append(m.Entries, doctorACE{SID: "S-1-15-2-1", Mask: "0xa0000000", Flags: 0x13})
		}, true},
		{"program explicit other read", programPermissionRole, func(m *doctorACLMetadata) {
			m.Entries = append(m.Entries, doctorACE{SID: "S-1-5-32-545", Mask: "0x001200a9", Flags: 0x3})
		}, false},
		{"program inherited creator owner template", programPermissionRole, func(m *doctorACLMetadata) {
			m.Entries = append(m.Entries, doctorACE{SID: "S-1-3-0", Mask: "0x10000000", Flags: 0x1b})
		}, true},
		{"program effective creator owner", programPermissionRole, func(m *doctorACLMetadata) {
			m.Entries = append(m.Entries, doctorACE{SID: "S-1-3-0", Mask: "0x10000000", Flags: 0x13})
		}, false},
		{"program explicit creator owner template", programPermissionRole, func(m *doctorACLMetadata) {
			m.Entries = append(m.Entries, doctorACE{SID: "S-1-3-0", Mask: "0x10000000", Flags: 0x0b})
		}, false},
		{"program creator group template", programPermissionRole, func(m *doctorACLMetadata) {
			m.Entries = append(m.Entries, doctorACE{SID: "S-1-3-1", Mask: "0x10000000", Flags: 0x1b})
		}, false},
		{"private creator owner template", privatePermissionRole, func(m *doctorACLMetadata) {
			m.Entries = append(m.Entries, doctorACE{SID: "S-1-3-0", Mask: "0x10000000", Flags: 0x1b})
		}, false},
		{"program untrusted owner", programPermissionRole, func(m *doctorACLMetadata) { m.OwnerSID = "S-1-5-21-9999" }, false},
		{"program no current writer", programPermissionRole, func(m *doctorACLMetadata) { m.Entries[0].Mask = "0x001200a9" }, false},
		{"private administrators", privatePermissionRole, func(m *doctorACLMetadata) {
			m.Entries = append(m.Entries, doctorACE{SID: "S-1-5-32-544", Mask: "0x001f01ff", Flags: 0x13})
		}, false},
		{"private inherited read", privatePermissionRole, func(m *doctorACLMetadata) {
			m.Entries = append(m.Entries, doctorACE{SID: "S-1-5-32-545", Mask: "0x001200a9", Flags: 0x13})
		}, false},
		{"private partial current access", privatePermissionRole, func(m *doctorACLMetadata) { m.Entries[0].Mask = "0x40000000" }, false},
		{"private inherit only", privatePermissionRole, func(m *doctorACLMetadata) { m.Entries[0].Flags = 0x1b }, false},
		{"private system missing", privatePermissionRole, func(m *doctorACLMetadata) { m.Entries = m.Entries[:1] }, false},
		{"null dacl", programPermissionRole, func(m *doctorACLMetadata) { m.DACLState = "null" }, false},
		{"unsupported deny", programPermissionRole, func(m *doctorACLMetadata) { m.Entries[0].Type = 1 }, false},
		{"unknown flags", programPermissionRole, func(m *doctorACLMetadata) { m.Entries[0].Flags = 0x80 }, false},
		{"missing owner", programPermissionRole, func(m *doctorACLMetadata) { m.OwnerSID = "" }, false},
		{"unknown mask", programPermissionRole, func(m *doctorACLMetadata) { m.Entries[0].Mask = "" }, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			m := permissionMetadataFixture()
			tc.edit(&m)
			issues := permissionPolicyIssues(&m, tc.role)
			if got := m.Complete && len(issues) == 0; got != tc.ok {
				t.Fatalf("accepted=%t, complete=%t, issues=%v", got, m.Complete, issues)
			}
		})
	}
}

func TestPermissionProgramRejectsEveryOtherWriteRight(t *testing.T) {
	// Content writes, append, attributes/EAs, child deletion, deletion, security
	// changes and generic write/all must never be treated as read-only.
	for _, mask := range []string{"0x00000002", "0x00000004", "0x00000010", "0x00000040", "0x00000100", "0x00010000", "0x00040000", "0x00080000", "0x40000000", "0x10000000"} {
		t.Run(mask, func(t *testing.T) {
			m := permissionMetadataFixture()
			m.Entries = append(m.Entries, doctorACE{SID: "S-1-1-0", Mask: mask, Flags: 0x13})
			if issues := permissionPolicyIssues(&m, programPermissionRole); len(issues) == 0 {
				t.Fatal("untrusted inherited write permission accepted")
			}
		})
	}
}

func TestPermissionPathsKeepExistingCredentialAndStateLocations(t *testing.T) {
	root := t.TempDir()
	for _, name := range []string{".", "bin", "versions/v1.2.3/awf.exe", "config.json", "channel.json", "current.json", "lifecycle.lock"} {
		if got := pathPermissionRole(root, filepath.Join(root, filepath.FromSlash(name))); got != programPermissionRole {
			t.Fatalf("%s role=%s", name, got)
		}
	}
	for _, name := range []string{"credentials/windows-node/node-token.dpapi", "state/jobs/job.json", "private/runtime.json", "private/starting.json", "logs/runtime.log", "PRIVATE/runtime.json"} {
		if got := pathPermissionRole(root, filepath.Join(root, filepath.FromSlash(name))); got != privatePermissionRole {
			t.Fatalf("%s role=%s", name, got)
		}
	}
	if runtimePath(root) != filepath.Join(root, "private", "runtime.json") || startupPath(root) != filepath.Join(root, "private", "starting.json") {
		t.Fatal("runtime identities are not in the private subtree")
	}
}

func TestPermissionLegacyLayoutRefusedWithoutMutation(t *testing.T) {
	for _, name := range []string{"data", "runtime.json", "starting.json"} {
		t.Run(name, func(t *testing.T) {
			root := t.TempDir()
			path := filepath.Join(root, name)
			if err := os.WriteFile(path, []byte("historical marker"), 0600); err != nil {
				t.Fatal(err)
			}
			if err := privateRoot(root); err == nil || !strings.Contains(err.Error(), "historical") {
				t.Fatalf("historical layout accepted: %v", err)
			}
			if _, err := managedDirectory(root, "private"); err == nil {
				t.Fatal("private directory created in historical tree")
			}
			if _, err := readRuntime(root); err == nil || os.IsNotExist(err) {
				t.Fatal("historical runtime mistaken for stopped state")
			}
			if _, err := readStartup(root); err == nil || os.IsNotExist(err) {
				t.Fatal("historical startup mistaken for absent intent")
			}
			entries, err := os.ReadDir(root)
			if err != nil || len(entries) != 1 {
				t.Fatal("historical tree was changed")
			}
			data, err := os.ReadFile(path)
			if err != nil || string(data) != "historical marker" {
				t.Fatal("historical data was changed")
			}
		})
	}
}

func TestPermissionExistingModesAreNeverRepaired(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("native descriptor preservation covered separately")
	}
	root := t.TempDir()
	if err := os.Chmod(root, 0755); err != nil {
		t.Fatal(err)
	}
	if err := privateRoot(root); err != nil {
		t.Fatal(err)
	}
	if _, err := managedDirectory(root, "state", "jobs"); err != nil {
		t.Fatal(err)
	}
	if err := validateInstallRoot(root); err != nil {
		t.Fatal(err)
	}
	if st, err := os.Stat(root); err != nil || st.Mode().Perm() != 0755 {
		t.Fatal("ordinary program root was modified")
	}
	state := filepath.Join(root, "state")
	if err := os.Chmod(state, 0755); err != nil {
		t.Fatal(err)
	}
	if _, err := managedDirectory(root, "state"); err == nil {
		t.Fatal("existing broad private directory accepted")
	}
	if err := validateInstallRoot(root); err == nil {
		t.Fatal("private descendant was treated as program data")
	}
	if st, err := os.Stat(state); err != nil || st.Mode().Perm() != 0755 {
		t.Fatal("existing private directory was repaired")
	}
}

func TestPermissionManagedCreationValidatesAllPartsFirst(t *testing.T) {
	root := t.TempDir()
	for _, bad := range []string{"", ".", "..", "a/b", `a\b`, "a:stream"} {
		if _, err := managedDirectory(root, "state", bad); err == nil {
			t.Fatalf("invalid part %q accepted", bad)
		}
		if entries, err := os.ReadDir(root); err != nil || len(entries) != 0 {
			t.Fatal("partial managed directory created before invalid component rejected")
		}
	}
}

func TestPermissionRuntimeIdentitiesUsePrivateStorage(t *testing.T) {
	root := t.TempDir()
	intent := Startup{LaunchID: strings.Repeat("a", 64), Version: "v1.2.3"}
	if err := createStartup(root, intent); err != nil {
		t.Fatal(err)
	}
	r := Runtime{LaunchID: intent.LaunchID, URL: "http://127.0.0.1:1234", Token: strings.Repeat("b", 64), Version: intent.Version}
	if err := writeJSON(runtimePath(root), r); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{filepath.Join(root, "private"), startupPath(root), runtimePath(root)} {
		if err := checkPrivatePath(path); err != nil {
			t.Fatalf("runtime identity is not private: %v", err)
		}
	}
	for _, name := range []string{"runtime.json", "starting.json"} {
		if _, err := os.Lstat(filepath.Join(root, name)); !os.IsNotExist(err) {
			t.Fatal("runtime identity remains at program root")
		}
	}
	if got, err := readRuntime(root); err != nil || got != r {
		t.Fatalf("runtime did not round-trip: %v", err)
	}
	if err := clearStartup(root, intent.LaunchID); err != nil {
		t.Fatal(err)
	}
	if runtime.GOOS != "windows" {
		if err := os.Chmod(runtimePath(root), 0644); err != nil {
			t.Fatal(err)
		}
		if _, err := readRuntime(root); err == nil {
			t.Fatal("readRuntime accepted a broadly readable token file")
		}
	}
}
