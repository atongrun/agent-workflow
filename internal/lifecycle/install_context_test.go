package lifecycle

import (
	"errors"
	"strings"
	"testing"
)

func TestInstallerPackageStatusFailsClosed(t *testing.T) {
	for _, tc := range []struct {
		name   string
		status uint32
		want   string
	}{
		{"no-package", 15700, ""},
		{"success-is-packaged", 0, "inside a Windows packaged app"},
		{"buffer-required-is-packaged", 122, "inside a Windows packaged app"},
		{"access-denied", 5, "Windows error 5"},
		{"invalid-parameter", 87, "Windows error 87"},
		{"different-appmodel-error", 15701, "Windows error 15701"},
		{"unknown-status", ^uint32(0), "Windows error 4294967295"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			err := validateInstallerPackage(tc.status, nil)
			if tc.want == "" {
				if err != nil {
					t.Fatalf("process without package identity rejected: %v", err)
				}
				return
			}
			if err == nil || !strings.Contains(err.Error(), tc.want) {
				t.Fatalf("status %d: got %v, want %q", tc.status, err, tc.want)
			}
			if !strings.Contains(err.Error(), "normal Windows PowerShell") || !strings.Contains(err.Error(), "Start menu") {
				t.Fatalf("missing recovery guidance: %v", err)
			}
		})
	}
}

func TestInstallerPackageQueryFailureCannotAllowInstall(t *testing.T) {
	lookupErr := errors.New("package identity API unavailable")
	for _, status := range []uint32{0, 122, 15700} {
		err := validateInstallerPackage(status, lookupErr)
		if !errors.Is(err, lookupErr) || !strings.Contains(err.Error(), "installation stopped") || !strings.Contains(err.Error(), "normal Windows PowerShell") {
			t.Fatalf("lookup failure with status %d did not fail closed: %v", status, err)
		}
	}
}

func TestInstallerPhysicalRootMustMatchEvenWithoutPackageIdentity(t *testing.T) {
	// Real redirected processes can return APPMODEL_ERROR_NO_PACKAGE. The
	// filesystem check must independently reject a redirected final path.
	if err := validateInstallerPackage(15700, nil); err != nil {
		t.Fatal(err)
	}
	const intended = `C:\Users\fixture\AppData\Local\AWF`
	for _, tc := range []struct {
		name, expected, actual string
		ok                     bool
	}{
		{"same", intended, intended, true},
		{"DOS-prefix-and-case", intended, `\\?\c:\users\fixture\appdata\local\awf`, true},
		{"separators", `C:/Users/fixture/AppData/Local/AWF`, intended, true},
		{"trailing-separator", intended + `\`, `\\?\` + intended, true},
		{"extended-UNC", `\\server\share\AWF`, `\\?\UNC\server\share\AWF`, true},
		{"redirected", intended, `\\?\C:\Users\fixture\AppData\Local\Packages\fixture\LocalCache\Local\AWF`, false},
		{"another-drive", intended, `\\?\D:\Users\fixture\AppData\Local\AWF`, false},
		{"sibling-prefix", intended, `\\?\` + intended + `-other`, false},
		{"child", intended, `\\?\` + intended + `\child`, false},
		{"missing-final-path", intended, "", false},
		{"both-missing", "", "", false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			err := validateInstallerPath(tc.expected, tc.actual, nil)
			if (err == nil) != tc.ok {
				t.Fatalf("physical path check: %v; want allowed=%t", err, tc.ok)
			}
			if err != nil && (!strings.Contains(err.Error(), "redirected") || !strings.Contains(err.Error(), "normal Windows PowerShell")) {
				t.Fatalf("missing redirect recovery guidance: %v", err)
			}
		})
	}
	queryErr := errors.New("handle path query failed")
	if err := validateInstallerPath(intended, intended, queryErr); !errors.Is(err, queryErr) {
		t.Fatalf("failed physical-path query did not fail closed: %v", err)
	}
}
