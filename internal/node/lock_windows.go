package node

import (
	"fmt"
	"os"
	"syscall"
	"unsafe"
)

func lockState(path string) (*os.File, error) {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	var overlap syscall.Overlapped
	result, _, callErr := syscall.NewLazyDLL("kernel32.dll").NewProc("LockFileEx").Call(f.Fd(), 3, 0, 1, 0, uintptr(unsafe.Pointer(&overlap)))
	if result == 0 {
		f.Close()
		return nil, fmt.Errorf("node state is in use or cannot be locked: %w", callErr)
	}
	return f, nil
}

// Windows does not support fsync on directory handles opened by os.Open.
func syncDirectory(string) error { return nil }
