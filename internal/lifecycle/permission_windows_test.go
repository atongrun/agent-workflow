package lifecycle

import (
	"os"
	"path/filepath"
	"reflect"
	"syscall"
	"testing"
	"unsafe"
)

func privatePermissionFixtureRoot(t *testing.T) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "private-fixture")
	if err := createPrivateDirectory(path); err != nil {
		t.Fatal(err)
	}
	return path
}

// Fixture descriptors are supplied only at creation, just like production
// private trees. No existing directory is changed by this fixture helper.
func createPermissionFixtureDirectory(t *testing.T, path, descriptor string) {
	t.Helper()
	sddl, err := syscall.UTF16PtrFromString(descriptor)
	if err != nil {
		t.Fatal(err)
	}
	var sd uintptr
	r, _, err := syscall.NewLazyDLL("advapi32.dll").NewProc("ConvertStringSecurityDescriptorToSecurityDescriptorW").Call(uintptr(unsafe.Pointer(sddl)), 1, uintptr(unsafe.Pointer(&sd)), 0)
	if r == 0 {
		t.Fatal(err)
	}
	defer syscall.LocalFree(syscall.Handle(sd))
	p, err := syscall.UTF16PtrFromString(path)
	if err != nil {
		t.Fatal(err)
	}
	sa := syscall.SecurityAttributes{Length: uint32(unsafe.Sizeof(syscall.SecurityAttributes{})), SecurityDescriptor: sd}
	r, _, err = syscall.NewLazyDLL("kernel32.dll").NewProc("CreateDirectoryW").Call(uintptr(unsafe.Pointer(p)), uintptr(unsafe.Pointer(&sa)))
	if r == 0 {
		t.Fatal(err)
	}
}

func ordinaryPermissionFixtureRoot(t *testing.T) string {
	t.Helper()
	parent := filepath.Join(t.TempDir(), "profile-fixture")
	token, err := syscall.OpenCurrentProcessToken()
	if err != nil {
		t.Fatal(err)
	}
	defer token.Close()
	user, err := token.GetTokenUser()
	if err != nil {
		t.Fatal(err)
	}
	sid, err := user.User.Sid.String()
	if err != nil {
		t.Fatal(err)
	}
	createPermissionFixtureDirectory(t, parent, "D:P(A;OICI;FA;;;"+sid+")(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;GRGX;;;BU)")
	root := filepath.Join(parent, "AWF")
	if err := os.Mkdir(root, 0700); err != nil {
		t.Fatal(err)
	}
	return root
}

func TestPermissionWindowsProgramRootDACLNeverChanges(t *testing.T) {
	root := ordinaryPermissionFixtureRoot(t)
	before := inspectDoctorACL(root)
	if !before.Complete || before.Protected == nil || *before.Protected {
		t.Fatal("ordinary inherited fixture is not observable")
	}
	if err := privateRoot(root); err != nil {
		t.Fatalf("ordinary inherited program root rejected: %v", err)
	}
	for _, name := range []string{"credentials", "state", "private", "logs"} {
		path, err := managedDirectory(root, name, "nested")
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(path, "fixture.txt"), []byte("synthetic"), 0600); err != nil {
			t.Fatal(err)
		}
		for _, p := range []string{filepath.Dir(path), path, filepath.Join(path, "fixture.txt")} {
			if err := checkPrivatePath(p); err != nil {
				t.Fatalf("private path not atomically protected: %v", err)
			}
		}
	}
	if err := validateInstallRoot(root); err != nil {
		t.Fatal(err)
	}
	if after := inspectDoctorACL(root); !reflect.DeepEqual(before, after) {
		t.Fatal("program root descriptor changed during private-tree creation")
	}
}

func TestPermissionWindowsExistingPrivateDirectoryIsNotRepaired(t *testing.T) {
	root := ordinaryPermissionFixtureRoot(t)
	path := filepath.Join(root, "private")
	if err := os.Mkdir(path, 0700); err != nil {
		t.Fatal(err)
	}
	before := inspectDoctorACL(path)
	if err := createPrivateDirectory(path); err == nil {
		t.Fatal("existing directory was adopted by creation helper")
	}
	if _, err := managedDirectory(root, "private"); err == nil {
		t.Fatal("broad existing private directory accepted")
	}
	if err := validateInstallRoot(root); err == nil {
		t.Fatal("broad private descendant accepted")
	}
	if after := inspectDoctorACL(path); !reflect.DeepEqual(before, after) {
		t.Fatal("existing private descriptor was modified")
	}
}
