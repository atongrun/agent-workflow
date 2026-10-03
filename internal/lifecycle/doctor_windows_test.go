package lifecycle

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

// Only disposable test inputs are created. This does not establish acceptance
// of a real user's root or package context.
func TestDoctorNativeMetadataReadOnly(t *testing.T) {
	local := t.TempDir()
	root := filepath.Join(local, "AWF")
	if err := os.Mkdir(root, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "config.json"), []byte("not parsed"), 0600); err != nil {
		t.Fatal(err)
	}
	before := doctorSnapshot(t, local)
	report := inspectDoctor(local, nativeDoctorPlatform(), doctorNoCommand)
	if !reflect.DeepEqual(before, doctorSnapshot(t, local)) {
		t.Fatal("native doctor changed fixture")
	}
	if !doctorHas(report, "root", "present") {
		t.Fatal(report)
	}
	if !doctorHas(report, "root.physical", "observed") && !doctorHas(report, "root.physical", "mismatch") && !doctorHas(report, "root.physical", "unknown") {
		t.Fatal(report)
	}
	t.Logf("native metadata observations: %+v", report.Findings)
}
