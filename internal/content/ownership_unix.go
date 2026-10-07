//go:build linux || darwin

package content

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"syscall"
)

func privateFile(path string) (*os.File, error) {
	fd, err := syscall.Open(path, syscall.O_RDWR|syscall.O_CREAT|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0600)
	if err != nil {
		return nil, err
	}
	f := os.NewFile(uintptr(fd), path)
	info, err := f.Stat()
	if err != nil || validateContentFile(info) != nil {
		_ = f.Close()
		return nil, fmt.Errorf("content file must be private and regular")
	}
	return f, nil
}

func validateContentFile(info os.FileInfo) error {
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 || stat.Uid != uint32(os.Geteuid()) || stat.Nlink != 1 {
		return fmt.Errorf("content file must be private, singly linked and service-owned")
	}
	return nil
}

func validateDataDirectory(dir string, allowMissing bool) error {
	dir = filepath.Clean(dir)
	path := "/"
	parts := strings.Split(strings.TrimPrefix(dir, "/"), "/")
	for i := 0; i <= len(parts); i++ {
		if i > 0 {
			path = filepath.Join(path, parts[i-1])
		}
		info, err := os.Lstat(path)
		if allowMissing && os.IsNotExist(err) {
			return nil
		}
		if err != nil {
			return err
		}
		stat, ok := info.Sys().(*syscall.Stat_t)
		if !ok || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return fmt.Errorf("untrusted content directory ancestor")
		}
		trustedOwner := stat.Uid == 0 || stat.Uid == uint32(os.Geteuid())
		// SQLite reopens a pathname. A read-only bind view does not prove that
		// its backing inode cannot be replaced through another writable view.
		if !trustedOwner {
			return fmt.Errorf("content ancestor ownership cannot be trusted")
		}
		if info.Mode().Perm()&0022 != 0 && !(stat.Uid == 0 && info.Mode()&os.ModeSticky != 0) {
			return fmt.Errorf("mutable content directory ancestor")
		}
		if i == len(parts) && (stat.Uid != uint32(os.Geteuid()) || info.Mode().Perm()&0077 != 0) {
			return fmt.Errorf("content data directory must be private and service-owned")
		}
	}
	return nil
}

func acquireContentLock(path string) (func() error, error) {
	f, err := privateFile(path)
	if err != nil {
		return nil, err
	}
	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		_ = f.Close()
		return nil, fmt.Errorf("content ledger already owned: %w", err)
	}
	return f.Close, nil
}
