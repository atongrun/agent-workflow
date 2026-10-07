//go:build linux

package content

import (
	"bytes"
	"fmt"
	"os"
	"os/exec"
	"syscall"
)

func configureProcess(cmd *exec.Cmd) error {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true, Pdeathsig: syscall.SIGKILL}
	return nil
}
func terminateProcessGroup(pid int) error {
	if pid <= 0 {
		return ErrInvalid
	}
	return syscall.Kill(-pid, syscall.SIGKILL)
}

func processStartToken(pid int) (string, error) {
	if pid <= 0 {
		return "", ErrInvalid
	}
	b, err := os.ReadFile(fmt.Sprintf("/proc/%d/stat", pid))
	if err != nil {
		return "", err
	}
	i := bytes.LastIndexByte(b, ')')
	if i < 0 {
		return "", ErrInvalid
	}
	fields := bytes.Fields(b[i+1:])
	if len(fields) < 20 {
		return "", ErrInvalid
	}
	token := string(fields[19])
	if token == "" || len(token) > 32 {
		return "", ErrInvalid
	}
	for _, c := range token {
		if c < '0' || c > '9' {
			return "", ErrInvalid
		}
	}
	return token, nil
}
func processGroupAlive(pid int) bool {
	if pid <= 0 {
		return true
	}
	err := syscall.Kill(-pid, 0)
	return err != syscall.ESRCH
}
