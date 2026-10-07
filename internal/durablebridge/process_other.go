//go:build !linux

package durablebridge

import (
	"os"
	"os/exec"
)

func openConfigFile(string) (*os.File, error) { return nil, ErrUnsupported }
func validateSocket(string) error             { return ErrUnsupported }
func configureWorker(*exec.Cmd) error         { return ErrUnsupported }
func signalWorker(*exec.Cmd, bool) error      { return ErrUnsupported }
func validateDirectory(string) error          { return ErrUnsupported }
