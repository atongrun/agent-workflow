//go:build !windows

package privatefile

import "os"

// Create creates a new read/write file and never replaces an existing object.
func Create(path string) (*os.File, error) {
	return os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_RDWR, 0600)
}

func openExisting(path string) (*os.File, error) {
	return os.OpenFile(path, os.O_RDWR, 0)
}
