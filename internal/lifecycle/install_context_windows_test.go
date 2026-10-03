package lifecycle

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// These gates query the real process identity. A skip is an untested context,
// not a passing native acceptance result; cross-compilation runs neither gate.
func TestWindowsInstallerNoPackageIdentity(t *testing.T) {
	status, err := currentPackageIdentity()
	if err != nil {
		t.Fatal(err)
	}
	switch status {
	case 0, errorInsufficientBuffer:
		t.Skip("requires APPMODEL_ERROR_NO_PACKAGE; run from normal Windows PowerShell opened from the Start menu")
	case appModelErrorNoPackage:
		if err := checkInstallerContext(); err != nil {
			t.Fatalf("real process without package identity rejected: %v", err)
		}
	default:
		t.Fatalf("cannot establish native process identity: Windows error %d", status)
	}
}

func TestWindowsPackagedInstallerRejectsBeforeWrites(t *testing.T) {
	status, err := currentPackageIdentity()
	if err != nil {
		t.Fatal(err)
	}
	switch status {
	case appModelErrorNoPackage:
		t.Skip("requires real package identity; run from a Windows packaged app, not normal PowerShell")
	case 0, errorInsufficientBuffer:
	default:
		t.Fatalf("cannot establish native process identity: Windows error %d", status)
	}
	for _, existing := range []bool{false, true} {
		name := "absent-root"
		if existing {
			name = "existing-root"
		}
		t.Run(name, func(t *testing.T) {
			root := filepath.Join(t.TempDir(), "AWF")
			marker := filepath.Join(root, "sentinel.txt")
			if existing {
				if err := os.Mkdir(root, 0700); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(marker, []byte("unchanged"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			var out bytes.Buffer
			err := install(root, []string{"--version", "v1.0.0", "--archive", filepath.Join(root, "missing.zip")}, &out)
			if err == nil || !strings.Contains(err.Error(), "inside a Windows packaged app") || !strings.Contains(err.Error(), "normal Windows PowerShell") {
				t.Fatalf("packaged installer was not rejected: %v", err)
			}
			if out.Len() != 0 {
				t.Fatalf("packaged installer produced unexpected output: %s", out.String())
			}
			if !existing {
				if _, err := os.Lstat(root); !os.IsNotExist(err) {
					t.Fatalf("packaged installer created a root: %v", err)
				}
				return
			}
			entries, err := os.ReadDir(root)
			if err != nil || len(entries) != 1 || entries[0].Name() != "sentinel.txt" {
				t.Fatalf("packaged installer changed existing root: %v, %v", entries, err)
			}
			data, err := os.ReadFile(marker)
			if err != nil || string(data) != "unchanged" {
				t.Fatalf("packaged installer changed existing file: %q, %v", data, err)
			}
		})
	}
}

func TestWindowsInstallerFinalPaths(t *testing.T) {
	root := filepath.Join(t.TempDir(), "AWF")
	if err := checkInstallerPath(root, true); err != nil {
		t.Fatalf("absent root preflight: %v", err)
	}
	if err := checkInstallerPath(root, false); err == nil {
		t.Fatal("required root was accepted without a handle")
	}
	if err := os.Mkdir(root, 0700); err != nil {
		t.Fatal(err)
	}
	actual, err := finalInstallerPath(root)
	if err != nil {
		t.Fatalf("real handle final-path query failed: %v", err)
	}
	wantErr := validateInstallerPath(filepath.Clean(root), actual, nil)
	if err := checkInstallerPath(root, false); (err == nil) != (wantErr == nil) {
		t.Fatalf("physical root result differs from final handle path: %v; final path=%q", err, actual)
	}
	launcher := filepath.Join(root, "awf.exe")
	if err := os.WriteFile(launcher, []byte("inert fixture, never executed"), 0600); err != nil {
		t.Fatal(err)
	}
	actual, err = finalInstallerPath(launcher)
	if err != nil {
		t.Fatalf("real file handle final-path query failed: %v", err)
	}
	wantErr = validateInstallerPath(filepath.Clean(launcher), actual, nil)
	if err := checkInstallerPath(launcher, false); (err == nil) != (wantErr == nil) {
		t.Fatalf("physical launcher result differs from final handle path: %v; final path=%q", err, actual)
	}
}

func TestWindowsNoPackageRedirectedInstallerRejectsBeforeWrites(t *testing.T) {
	status, err := currentPackageIdentity()
	if err != nil {
		t.Fatal(err)
	}
	if status == 0 || status == errorInsufficientBuffer {
		t.Skip("requires a redirected process that reports APPMODEL_ERROR_NO_PACKAGE")
	}
	if status != appModelErrorNoPackage {
		t.Fatalf("cannot establish native process identity: Windows error %d", status)
	}
	root := filepath.Join(t.TempDir(), "AWF")
	if err := os.Mkdir(root, 0700); err != nil {
		t.Fatal(err)
	}
	actual, err := finalInstallerPath(root)
	if err != nil {
		t.Fatal(err)
	}
	if validateInstallerPath(filepath.Clean(root), actual, nil) == nil {
		t.Skip("temporary fixture path is not redirected; actual redirected-context acceptance remains untested")
	}
	var out bytes.Buffer
	err = install(root, []string{"--version", "v1.0.0", "--archive", filepath.Join(root, "missing.zip")}, &out)
	if err == nil || !strings.Contains(err.Error(), "installation path is redirected") {
		t.Fatalf("NO_PACKAGE with redirected root was not rejected: %v", err)
	}
	entries, err := os.ReadDir(root)
	if err != nil || len(entries) != 0 || out.Len() != 0 {
		t.Fatalf("redirected installer changed fixture: %v, %v, output=%q", entries, err, out.String())
	}
}
