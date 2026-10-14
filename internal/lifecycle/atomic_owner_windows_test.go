package lifecycle

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestAtomicWindowsExplicitUserOwnerPreservesInheritedACL(t *testing.T) {
	dir := privatePermissionFixtureRoot(t)
	parent := inspectDoctorACL(dir)
	baseline := filepath.Join(dir, "baseline.txt")
	if err := os.WriteFile(baseline, []byte("synthetic"), 0600); err != nil {
		t.Fatal(err)
	}
	inherited := inspectDoctorACL(baseline)
	dest := filepath.Join(dir, "starting.json")
	if err := atomicWrite(dest, []byte("synthetic")); err != nil {
		t.Fatal(err)
	}
	actual := inspectDoctorACL(dest)
	if !actual.Complete || actual.OwnerSID != actual.CurrentUserSID {
		t.Fatal("new private file owner is not TokenUser")
	}
	if !reflect.DeepEqual(inherited.Entries, actual.Entries) || !reflect.DeepEqual(inherited.Protected, actual.Protected) {
		t.Fatal("inherited access rules changed")
	}
	if err := checkPrivatePath(dest); err != nil {
		t.Fatal(err)
	}
	if err := atomicWrite(dest, []byte("replacement")); err != nil {
		t.Fatal(err)
	}
	if err := checkPrivatePath(dest); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(dest)
	if err != nil || string(data) != "replacement" {
		t.Fatal("atomic replacement failed")
	}
	if !reflect.DeepEqual(parent, inspectDoctorACL(dir)) {
		t.Fatal("parent descriptor changed")
	}
}

func TestAtomicWindowsProgramFileRetainsProgramInheritedReaders(t *testing.T) {
	root := ordinaryPermissionFixtureRoot(t)
	baseline := filepath.Join(root, "baseline.json")
	if err := os.WriteFile(baseline, []byte("synthetic"), 0600); err != nil {
		t.Fatal(err)
	}
	inherited := inspectDoctorACL(baseline)
	dest := filepath.Join(root, "pointer.json")
	if err := atomicWrite(dest, []byte("synthetic")); err != nil {
		t.Fatal(err)
	}
	actual := inspectDoctorACL(dest)
	if actual.OwnerSID != actual.CurrentUserSID || !reflect.DeepEqual(inherited.Entries, actual.Entries) {
		t.Fatal("program inherited access changed")
	}
	if err := checkProgramPath(dest); err != nil {
		t.Fatal(err)
	}
}
