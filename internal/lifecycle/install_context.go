package lifecycle

import (
	"errors"
	"fmt"
	"strings"
)

const (
	appModelErrorNoPackage  uint32 = 15700
	errorInsufficientBuffer uint32 = 122
	installerShellGuidance         = "Open a normal Windows PowerShell window from the Start menu, outside any packaged app, then rerun the installer."
)

// GetCurrentPackageFullName returns a status directly, not via GetLastError.
// With a zero-sized buffer, both success and insufficient buffer establish
// package identity. Only APPMODEL_ERROR_NO_PACKAGE establishes its absence.
func validateInstallerPackage(status uint32, queryErr error) error {
	if queryErr != nil {
		return fmt.Errorf("cannot verify the installer's Windows package identity; installation stopped. %s GetCurrentPackageFullName: %w", installerShellGuidance, queryErr)
	}
	switch status {
	case appModelErrorNoPackage:
		return nil
	case 0, errorInsufficientBuffer:
		return errors.New("AWF installation cannot run inside a Windows packaged app because Windows can redirect LocalAppData writes. " + installerShellGuidance)
	default:
		return fmt.Errorf("cannot verify the installer's Windows package identity; installation stopped. %s GetCurrentPackageFullName returned Windows error %d", installerShellGuidance, status)
	}
}

// Both paths must already be canonical. Strip the DOS extended-path prefix
// returned by GetFinalPathNameByHandleW without accepting a different location.
func validateInstallerPath(expected, actual string, queryErr error) error {
	if queryErr != nil {
		return fmt.Errorf("cannot verify the physical AWF installation path; installation stopped. %s %w", installerShellGuidance, queryErr)
	}
	normalize := func(p string) string {
		p = strings.ReplaceAll(p, "/", `\`)
		if len(p) >= 8 && strings.EqualFold(p[:8], `\\?\UNC\`) {
			p = `\\` + p[8:]
		} else {
			p = strings.TrimPrefix(p, `\\?\`)
		}
		return strings.TrimRight(p, `\`)
	}
	if expected == "" || actual == "" || !strings.EqualFold(normalize(expected), normalize(actual)) {
		return errors.New("the AWF installation path is redirected or resolves to a different location; installation stopped. " + installerShellGuidance)
	}
	return nil
}
