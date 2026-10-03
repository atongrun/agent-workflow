package lifecycle

import (
	"os"
	"os/user"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"unsafe"

	"github.com/atongrun/agent-workflow/internal/core"
)

// These tests use temporary synthetic credentials only. They never open the
// configured pairing credential or register startup. Run on real Windows.
func protectFixture(t *testing.T, plain, entropy string) []byte {
	t.Helper()
	in := bytesBlob([]byte(plain))
	extra := bytesBlob([]byte(entropy))
	var out blob
	r, _, e := syscall.NewLazyDLL("crypt32.dll").NewProc("CryptProtectData").Call(uintptr(unsafe.Pointer(&in)), 0, uintptr(unsafe.Pointer(&extra)), 0, 0, 1, uintptr(unsafe.Pointer(&out)))
	if r == 0 {
		t.Fatalf("fixture DPAPI encryption: %v", e)
	}
	defer syscall.LocalFree(syscall.Handle(uintptr(unsafe.Pointer(out.Data))))
	return append([]byte(nil), unsafe.Slice(out.Data, out.Size)...)
}
func TestWindowsPairingDPAPIContract(t *testing.T) {
	const entropy = "AWF Windows node pairing v1"
	for _, tc := range []struct {
		name, plain, entropy string
		ok                   bool
	}{
		{"compatible-uppercase", strings.Repeat("AB0123CD", 8), entropy, true},
		{"different-entropy", strings.Repeat("AB0123CD", 8), "other", false},
		{"lowercase-token", strings.Repeat("ab0123cd", 8), entropy, false},
		{"short-token", "ABCD", entropy, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			root := t.TempDir()
			if e := privateRoot(root); e != nil {
				t.Fatal(e)
			}
			path := filepath.Join(root, "node-token.dpapi")
			if e := os.WriteFile(path, protectFixture(t, tc.plain, tc.entropy), 0600); e != nil {
				t.Fatal(e)
			}
			got, e := readNodeToken(path)
			if tc.ok {
				if e != nil || got != tc.plain {
					t.Fatalf("compatible fixture did not decrypt correctly")
				}
			} else if e == nil {
				t.Fatal("invalid credential was accepted")
			}
		})
	}
}
func TestWindowsPrivateACLAndAtomicPointer(t *testing.T) {
	root := t.TempDir()
	if e := protectDirectory(root); e != nil {
		t.Fatal(e)
	}
	p, e := syscall.UTF16PtrFromString(root)
	if e != nil {
		t.Fatal(e)
	}
	var sd uintptr
	advapi := syscall.NewLazyDLL("advapi32.dll")
	result, _, _ := advapi.NewProc("GetNamedSecurityInfoW").Call(uintptr(unsafe.Pointer(p)), 1, 4, 0, 0, 0, 0, uintptr(unsafe.Pointer(&sd)))
	if result != 0 {
		t.Fatalf("read ACL error %d", result)
	}
	defer syscall.LocalFree(syscall.Handle(sd))
	var text *uint16
	result, _, e = advapi.NewProc("ConvertSecurityDescriptorToStringSecurityDescriptorW").Call(sd, 1, 4, uintptr(unsafe.Pointer(&text)), 0)
	if result == 0 {
		t.Fatal(e)
	}
	defer syscall.LocalFree(syscall.Handle(uintptr(unsafe.Pointer(text))))
	var chars []uint16
	for i := uintptr(0); ; i++ {
		c := *(*uint16)(unsafe.Pointer(uintptr(unsafe.Pointer(text)) + i*2))
		if c == 0 {
			break
		}
		chars = append(chars, c)
	}
	sddl := syscall.UTF16ToString(chars)
	u, e := user.Current()
	if e != nil {
		t.Fatal(e)
	}
	if !strings.HasPrefix(sddl, "D:P") || strings.Count(sddl, "(") != 2 || !strings.Contains(sddl, ";;;SY)") || !strings.Contains(sddl, ";;;"+u.Uid+")") {
		t.Fatalf("unexpected private fixture ACL: %s", sddl)
	}
	pointer := filepath.Join(root, "current.json")
	if e = writeJSON(pointer, Pointer{Version: "v1.0.0"}); e != nil {
		t.Fatal(e)
	}
	if e = writeJSON(pointer, Pointer{Version: "v1.0.1"}); e != nil {
		t.Fatal(e)
	}
	got, e := current(root)
	if e != nil || got.Version != "v1.0.1" {
		t.Fatalf("atomic pointer replace: %+v %v", got, e)
	}
	first, e := lockFile(filepath.Join(root, "fixture.lock"))
	if e != nil {
		t.Fatal(e)
	}
	if second, e := lockFile(filepath.Join(root, "fixture.lock")); e == nil {
		second.Close()
		first.Close()
		t.Fatal("concurrent writer lock was accepted")
	}
	first.Close()
}

func TestWindowsRejectsProtectedBroadChildACL(t *testing.T) {
	root := t.TempDir()
	if e := privateRoot(root); e != nil {
		t.Fatal(e)
	}
	child := filepath.Join(root, "versions")
	if e := os.Mkdir(child, 0700); e != nil {
		t.Fatal(e)
	}
	setBroadFixtureACL(t, child)
	// The child's DACL is protected: securing its parent cannot fix it.
	if e := privateRoot(root); e == nil {
		t.Fatal("private parent masked protected broad child ACL")
	}
	if e := validateInstallRoot(root); e == nil {
		t.Fatal("launcher accepted protected broad child ACL")
	}
	if _, e := managedDirectory(root, "versions"); e == nil {
		t.Fatal("staging accepted protected broad child ACL")
	}
}

func TestWindowsRejectsEveryReparseAttribute(t *testing.T) {
	for _, flags := range []uint32{syscall.FILE_ATTRIBUTE_REPARSE_POINT, syscall.FILE_ATTRIBUTE_REPARSE_POINT | syscall.FILE_ATTRIBUTE_DIRECTORY, syscall.FILE_ATTRIBUTE_REPARSE_POINT | syscall.FILE_ATTRIBUTE_ARCHIVE} {
		if e := rejectReparseAttributes(flags); e == nil {
			t.Fatal("reparse attribute accepted, including a non-surrogate/regular-looking reparse point")
		}
	}
	if e := rejectReparseAttributes(syscall.FILE_ATTRIBUTE_DIRECTORY); e != nil {
		t.Fatal(e)
	}
}

func setBroadFixtureACL(t *testing.T, path string) {
	t.Helper()
	u, e := user.Current()
	if e != nil {
		t.Fatal(e)
	}
	sddl, e := syscall.UTF16PtrFromString("D:P(A;OICI;FA;;;WD)(A;OICI;FA;;;" + u.Uid + ")(A;OICI;FA;;;SY)")
	if e != nil {
		t.Fatal(e)
	}
	advapi := syscall.NewLazyDLL("advapi32.dll")
	var sd uintptr
	r, _, e := advapi.NewProc("ConvertStringSecurityDescriptorToSecurityDescriptorW").Call(uintptr(unsafe.Pointer(sddl)), 1, uintptr(unsafe.Pointer(&sd)), 0)
	if r == 0 {
		t.Fatal(e)
	}
	defer syscall.LocalFree(syscall.Handle(sd))
	var present, defaulted int32
	var dacl uintptr
	r, _, e = advapi.NewProc("GetSecurityDescriptorDacl").Call(sd, uintptr(unsafe.Pointer(&present)), uintptr(unsafe.Pointer(&dacl)), uintptr(unsafe.Pointer(&defaulted)))
	if r == 0 || present == 0 {
		t.Fatal("fixture ACL unavailable")
	}
	p, e := syscall.UTF16PtrFromString(path)
	if e != nil {
		t.Fatal(e)
	}
	r, _, _ = advapi.NewProc("SetNamedSecurityInfoW").Call(uintptr(unsafe.Pointer(p)), 1, 0x80000004, 0, 0, dacl, 0)
	if r != 0 {
		t.Fatalf("fixture ACL update: Windows error %d", r)
	}
}

func TestWindowsExternalCredentialRequiresPrivateFileAndParent(t *testing.T) {
	for _, target := range []string{"file", "parent"} {
		t.Run(target, func(t *testing.T) {
			root := t.TempDir()
			if e := privateRoot(root); e != nil {
				t.Fatal(e)
			}
			folder := filepath.Join(root, "paired")
			if e := os.Mkdir(folder, 0700); e != nil {
				t.Fatal(e)
			}
			path := filepath.Join(folder, "node-token.dpapi")
			encrypted := protectFixture(t, strings.Repeat("AB0123CD", 8), "AWF Windows node pairing v1")
			if e := os.WriteFile(path, encrypted, 0600); e != nil {
				t.Fatal(e)
			}
			if _, e := readNodeToken(path); e != nil {
				t.Fatalf("private external fixture rejected: %v", e)
			}
			if target == "file" {
				setBroadFixtureACL(t, path)
			} else {
				setBroadFixtureACL(t, folder)
			}
			if _, e := readNodeToken(path); e == nil || !strings.Contains(e.Error(), "private") {
				t.Fatal("broad external credential boundary was accepted")
			}
		})
	}
}

// A standalone Windows Host does not secure an arbitrary dataDir via POSIX
// mode bits. Verify real files created by core.Open inherit a deliberately
// protected fixture root, and that replacements and nested directories retain
// that DACL. The managed Windows node establishes this boundary itself.
func TestWindowsPrivateRootProtectsInheritedStateAndDirectories(t *testing.T) {
	root := t.TempDir()
	if e := privateRoot(root); e != nil {
		t.Fatal(e)
	}
	hostDir := filepath.Join(root, "host-fixture")
	store, e := core.Open(hostDir)
	if e != nil {
		t.Fatal(e)
	}
	defer store.Close()
	statePath := filepath.Join(hostDir, "state.json")
	if e = checkPrivatePath(statePath); e != nil {
		t.Fatalf("initial Host state DACL: %v", e)
	}
	if e = store.Update(func(st *core.State) error { st.Settings.DefaultBranch = "fixture"; return nil }); e != nil {
		t.Fatal(e)
	}
	if e = checkPrivatePath(statePath); e != nil {
		t.Fatalf("replacement Host state DACL: %v", e)
	}
	planning := filepath.Join(hostDir, "planning", "task-fixture")
	if e = os.MkdirAll(planning, 0700); e != nil {
		t.Fatal(e)
	}
	jobs, e := managedDirectory(root, "state", "jobs")
	if e != nil {
		t.Fatal(e)
	}
	record := filepath.Join(jobs, "fixture.json")
	if e = writeJSON(record, map[string]string{"fixture": "not a real job"}); e != nil {
		t.Fatal(e)
	}
	pointer := filepath.Join(root, "current.json")
	if e = writeJSON(pointer, Pointer{Version: "v1.2.3"}); e != nil {
		t.Fatal(e)
	}
	for _, path := range []string{hostDir, filepath.Dir(planning), planning, filepath.Dir(jobs), jobs, record, pointer} {
		if e = checkPrivatePath(path); e != nil {
			t.Fatalf("inherited fixture DACL for %s: %v", filepath.Base(path), e)
		}
	}
	// Prove this is a real DACL assertion rather than a Windows mode-bit bypass.
	setBroadFixtureACL(t, statePath)
	if e = checkPrivatePath(statePath); e == nil {
		t.Fatal("broad state-file DACL was accepted")
	}
	if e = validateInstallRoot(root); e == nil {
		t.Fatal("managed tree accepted a broadly readable state file")
	}
}

// New pairing writer fixtures stay within t.TempDir. They never use the
// installation's real configured credential, SSH, registry, or a Host.
func TestWindowsNativePairWriterRoundTripAndNoOverwrite(t *testing.T) {
	root := t.TempDir()
	if e := privateRoot(root); e != nil {
		t.Fatal(e)
	}
	path := filepath.Join(root, "credentials", "windows-node", "node-token.dpapi")
	token := strings.Repeat("AB0123CD", 8)
	if e := writeNodeToken(root, path, token); e != nil {
		t.Fatal(e)
	}
	for _, p := range []string{filepath.Dir(filepath.Dir(path)), filepath.Dir(path), path} {
		if e := checkPrivatePath(p); e != nil {
			t.Fatalf("native pairing path is not private: %v", e)
		}
	}
	got, e := readNodeToken(path)
	if e != nil || got != token {
		t.Fatal("native DPAPI pairing did not round trip")
	}
	before, e := os.ReadFile(path)
	if e != nil {
		t.Fatal(e)
	}
	if strings.Contains(string(before), token) {
		t.Fatal("credential file contains plaintext")
	}
	if e := writeNodeToken(root, path, strings.Repeat("F", 64)); e == nil {
		t.Fatal("existing identity overwritten")
	}
	after, e := os.ReadFile(path)
	if e != nil || string(after) != string(before) {
		t.Fatal("existing encrypted file changed")
	}
	// A ciphertext generated by the native writer is exactly the same raw
	// CurrentUser/entropy format accepted from the historical helper.
	if e := os.WriteFile(path, protectFixture(t, token, "AWF Windows node pairing v1"), 0600); e != nil {
		t.Fatal(e)
	}
	got, e = readNodeToken(path)
	if e != nil || got != token {
		t.Fatal("historical helper identity became incompatible")
	}
}

func TestWindowsNativePairWriterRejectsUnsafeExternalParent(t *testing.T) {
	root := t.TempDir()
	if e := privateRoot(root); e != nil {
		t.Fatal(e)
	}
	external := t.TempDir()
	if e := privateRoot(external); e != nil {
		t.Fatal(e)
	}
	path := filepath.Join(external, "node-token.dpapi")
	setBroadFixtureACL(t, external)
	if e := writeNodeToken(root, path, strings.Repeat("AB0123CD", 8)); e == nil {
		t.Fatal("broad external parent accepted")
	}
	if _, e := os.Stat(path); !os.IsNotExist(e) {
		t.Fatal("unsafe external destination created")
	}
	for _, p := range []string{`\\server\share\token.dpapi`, filepath.Join(root, "node.dpapi:stream")} {
		if e := validateCredentialAncestors(p); e == nil {
			t.Fatal("UNC/alternate stream path accepted")
		}
	}
}
