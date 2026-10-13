//go:build linux

package host

import (
	"errors"
	"net"
	"os"
	"path/filepath"
	"strings"
	"syscall"
)

func validateProviderPeer(connection net.Conn) error {
	failed := errors.New("private provider peer unavailable")
	unix, ok := connection.(*net.UnixConn)
	if !ok {
		return failed
	}
	raw, err := unix.SyscallConn()
	if err != nil {
		return failed
	}
	var credential *syscall.Ucred
	var controlError error
	if raw.Control(func(fd uintptr) {
		credential, controlError = syscall.GetsockoptUcred(int(fd), syscall.SOL_SOCKET, syscall.SO_PEERCRED)
	}) != nil || controlError != nil || credential == nil || credential.Uid != 0 {
		return failed
	}
	return nil
}

func validateProviderSocket(path string) error {
	fail := errors.New("private provider broker unavailable")
	if !filepath.IsAbs(path) || filepath.Clean(path) != path || !strings.HasPrefix(path, "/run/") {
		return fail
	}
	info, e := os.Lstat(path)
	if e != nil || info.Mode()&os.ModeSocket == 0 || info.Mode().Perm() != 0600 {
		return fail
	}
	st, ok := info.Sys().(*syscall.Stat_t)
	if !ok || st.Uid != uint32(os.Geteuid()) {
		return fail
	}
	for p := filepath.Dir(path); ; p = filepath.Dir(p) {
		i, e := os.Lstat(p)
		if e != nil || !i.IsDir() || i.Mode()&os.ModeSymlink != 0 || i.Mode().Perm()&0022 != 0 {
			return fail
		}
		st, ok := i.Sys().(*syscall.Stat_t)
		if !ok || st.Uid != 0 {
			return fail
		}
		if p == "/" {
			break
		}
	}
	return nil
}
