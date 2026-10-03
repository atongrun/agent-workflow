//go:build !windows

package lifecycle

import "errors"

func nativeDoctorPlatform() doctorPlatform {
	unavailable := errors.New("native Windows inspection unavailable")
	return doctorPlatform{
		context:        func() (string, string) { return "unknown", "package identity requires native Windows" },
		programsFolder: func() (string, error) { return "", unavailable },
		physical:       func(string) (string, error) { return "", unavailable },
		acl:            func(string) (string, error) { return "Windows ACL metadata unavailable", unavailable },
		reparse:        func(string) error { return nil },
	}
}

func knownProgramsFolder() (string, error) {
	return "", errors.New("Windows per-user Programs known folder requires native Windows")
}
