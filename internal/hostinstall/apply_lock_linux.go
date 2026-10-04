//go:build linux

package hostinstall

import (
	"errors"
	"os"
	"syscall"
)

// Kernel ownership is released on process exit; no stale PID-file deletion.
func fixtureLock(root *os.Root) (*os.File, error) {
	if info, err := root.Lstat(".apply.lock"); err == nil {
		if !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 {
			return nil, errors.New("invalid fixture lock")
		}
	} else if !os.IsNotExist(err) {
		return nil, err
	}
	f, err := root.OpenFile(".apply.lock", os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	if err = syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		f.Close()
		return nil, err
	}
	return f, nil
}
