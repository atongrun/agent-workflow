//go:build linux

package hostinstall

import (
	"errors"
	"fmt"
	"os"
	"runtime"
	"syscall"
	"unsafe"
)

// The newly created private stage can inherit a default ACL from /opt. Chmod
// narrows current access but leaves that ACL available to future npm mkdir/open.
// Clear only this stage's default ACL, before any children exist or are promoted.
func isolateProgramStage(root *os.Root) error {
	dir, err := root.Open(".")
	if err != nil {
		return err
	}
	defer dir.Close()
	info, err := dir.Stat()
	if err != nil {
		return err
	}
	owner, ok := info.Sys().(*syscall.Stat_t)
	if !ok || int(owner.Uid) != os.Geteuid() || !info.IsDir() || info.Mode().Perm() != 0700 || info.Mode()&(os.ModeSetuid|os.ModeSetgid) != 0 {
		return errors.New("program stage must be a new private owned directory")
	}
	attr, err := syscall.BytePtrFromString("system.posix_acl_default")
	if err != nil {
		return err
	}
	_, _, code := syscall.Syscall(syscall.SYS_FREMOVEXATTR, dir.Fd(), uintptr(unsafe.Pointer(attr)), 0)
	runtime.KeepAlive(attr)
	runtime.KeepAlive(dir)
	if code == 0 || code == syscall.ENODATA || code == syscall.EOPNOTSUPP {
		return nil
	}
	return fmt.Errorf("isolate program staging default ACL: %w", code)
}
