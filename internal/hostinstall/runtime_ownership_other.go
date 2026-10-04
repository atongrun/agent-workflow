//go:build !linux

package hostinstall

import (
	"errors"
	"os"
	"os/exec"
)

func requireFixtureOwner(os.FileInfo) error { return errors.New("runtime preparation requires Linux") }
func configureRuntimeCommand(*exec.Cmd)     {}
