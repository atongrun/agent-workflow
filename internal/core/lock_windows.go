package core

import (
	"fmt"
	"os"
	"syscall"
	"unsafe"

	"github.com/atongrun/agent-workflow/internal/privatefile"
)

func lockState(path string) (*os.File, error) {
	f, err := privatefile.OpenLock(path)
	if err != nil {
		return nil, err
	}
	var overlap syscall.Overlapped
	result, _, callErr := syscall.NewLazyDLL("kernel32.dll").NewProc("LockFileEx").Call(f.Fd(), 3, 0, 1, 0, uintptr(unsafe.Pointer(&overlap)))
	if result == 0 {
		f.Close()
		return nil, fmt.Errorf("host state is in use or cannot be locked: %w", callErr)
	}
	return f, nil
}

// Windows does not support fsync on directory handles opened by os.Open.
func syncDirectory(string) error { return nil }
