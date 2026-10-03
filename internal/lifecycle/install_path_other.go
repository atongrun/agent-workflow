//go:build !windows

package lifecycle

import "errors"

func registerInstallPath(string) error {
	return errors.New("AWF user PATH registration requires Windows")
}

func installPathPreview(string) (bool, error) {
	return false, errors.New("AWF user PATH inspection requires Windows")
}
