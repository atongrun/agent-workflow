//go:build !linux

package content

import "os/exec"

func processStartToken(int) (string, error) { return "", ErrUnavailable }

func configureProcess(*exec.Cmd) error { return ErrUnavailable }
func terminateProcessGroup(int) error  { return ErrUnavailable }
func processGroupAlive(int) bool       { return true }
