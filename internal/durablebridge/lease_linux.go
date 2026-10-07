//go:build linux

package durablebridge

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"syscall"
)

// AcquireStorageLease requires a provisioned private directory. It does not
// create, migrate, open or recover native agent storage.
func AcquireStorageLease(dir string) (*StorageLease, error) {
	if !filepath.IsAbs(dir) || filepath.Clean(dir) != dir || dir == "/" {
		return nil, fmt.Errorf("Durable storage directory must be an absolute canonical path")
	}
	if err := validateDirectory(dir); err != nil {
		return nil, err
	}
	return acquireLeaseFile(filepath.Join(dir, ".awf-owner.lock"))
}

func validateDirectory(dir string) error {
	path := "/"
	parts := strings.Split(strings.TrimPrefix(dir, "/"), "/")
	for i := 0; i <= len(parts); i++ {
		if i > 0 {
			path = filepath.Join(path, parts[i-1])
		}
		info, err := os.Lstat(path)
		if err != nil {
			return err
		}
		stat, ok := info.Sys().(*syscall.Stat_t)
		if !ok || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return fmt.Errorf("Durable directory ancestry must contain only directories")
		}
		if stat.Uid != 0 && stat.Uid != uint32(os.Geteuid()) {
			return fmt.Errorf("Durable directory ancestry must be root or service-owned")
		}
		if info.Mode().Perm()&0022 != 0 && !(stat.Uid == 0 && info.Mode()&os.ModeSticky != 0) {
			return fmt.Errorf("Durable directory ancestry is writable by another principal")
		}
		if i == len(parts) && (stat.Uid != uint32(os.Geteuid()) || info.Mode().Perm() != 0700) {
			return fmt.Errorf("Durable directory must be service-owned with mode 0700")
		}
	}
	return nil
}

func acquireLeaseFile(path string) (*StorageLease, error) {
	fd, err := syscall.Open(path, syscall.O_CREAT|syscall.O_RDWR|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0600)
	if err != nil {
		return nil, err
	}
	f := os.NewFile(uintptr(fd), path)
	info, err := f.Stat()
	if err == nil {
		stat, ok := info.Sys().(*syscall.Stat_t)
		if !ok || !info.Mode().IsRegular() || info.Mode().Perm() != 0600 || stat.Uid != uint32(os.Geteuid()) || stat.Nlink != 1 {
			err = fmt.Errorf("Durable owner lease must be private, service-owned and singly linked")
		}
	}
	if err == nil {
		err = syscall.Flock(fd, syscall.LOCK_EX|syscall.LOCK_NB)
		if errors.Is(err, syscall.EWOULDBLOCK) || errors.Is(err, syscall.EAGAIN) {
			err = ErrStorageOwned
		}
	}
	if err != nil {
		_ = f.Close()
		return nil, err
	}
	return &StorageLease{file: f}, nil
}
