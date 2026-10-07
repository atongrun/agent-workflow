//go:build linux

package durablebridge

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
)

func openConfigFile(path string) (*os.File, error) {
	if err := validateDirectoryAncestry(filepath.Dir(path), false); err != nil {
		return nil, err
	}
	return openPrivateConfig(path)
}

func openPrivateConfig(path string) (*os.File, error) {
	fd, err := syscall.Open(path, syscall.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0)
	if err != nil {
		return nil, err
	}
	f := os.NewFile(uintptr(fd), path)
	info, err := f.Stat()
	if err == nil {
		stat, ok := info.Sys().(*syscall.Stat_t)
		if !ok || !info.Mode().IsRegular() || info.Mode().Perm() != 0600 || (stat.Uid != 0 && stat.Uid != uint32(os.Geteuid())) || stat.Nlink != 1 {
			err = ErrInvalid
		}
	}
	if err != nil {
		f.Close()
		return nil, err
	}
	return f, nil
}

func validateSocket(path string) error {
	info, err := os.Lstat(path)
	if err != nil {
		return err
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || info.Mode()&os.ModeSocket == 0 || info.Mode().Perm() != 0600 || stat.Uid != uint32(os.Geteuid()) || stat.Nlink != 1 {
		return ErrInvalid
	}
	return nil
}

func configureWorker(cmd *exec.Cmd) error {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true, Pdeathsig: syscall.SIGTERM}
	return nil
}

func signalWorker(cmd *exec.Cmd, force bool) error {
	if cmd.Process == nil {
		return fmt.Errorf("worker was not started")
	}
	if !force {
		return cmd.Process.Signal(syscall.SIGTERM)
	}
	// Native tools may detach into other process groups. This kills only the
	// owned worker group; systemd KillMode=control-group remains a native gate.
	err := syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	if err == syscall.ESRCH {
		return nil
	}
	return err
}
