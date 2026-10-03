//go:build !windows

package lifecycle

import (
	"errors"
	"os"
	"os/exec"
	"syscall"
)

// Native lifecycle dispatch remains Windows-only; allow portable install tests.
func checkInstallerContext() error          { return nil }
func checkInstallerPath(string, bool) error { return nil }

func replaceFile(a, b string) error   { return os.Rename(a, b) }
func protectDirectory(p string) error { return os.Chmod(p, 0700) }
func lockFile(p string) (*os.File, error) {
	f, e := os.OpenFile(p, os.O_CREATE|os.O_RDWR, 0600)
	if e != nil {
		return nil, e
	}
	if e = syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); e != nil {
		f.Close()
		return nil, e
	}
	return f, nil
}
func detach(c *exec.Cmd) { c.SysProcAttr = &syscall.SysProcAttr{Setsid: true} }
func readNodeToken(string) (string, error) {
	return "", errors.New("CurrentUser DPAPI node credentials require native Windows")
}
func setAutostart(string, bool) error { return errors.New("login autostart requires native Windows") }

func checkPrivatePath(p string) error {
	st, e := os.Stat(p)
	if e != nil {
		return e
	}
	if st.Mode().Perm()&0077 != 0 {
		return errors.New("path grants permissions to other users")
	}
	return nil
}
