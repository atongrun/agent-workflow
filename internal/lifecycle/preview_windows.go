package lifecycle

import (
	"io"
	"os"
	"syscall"
)

func interactiveUpdateInput(in io.Reader) bool {
	file, ok := in.(*os.File)
	if !ok {
		return false
	}
	var mode uint32
	return syscall.GetConsoleMode(syscall.Handle(file.Fd()), &mode) == nil
}
