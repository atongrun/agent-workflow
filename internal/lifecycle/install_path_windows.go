package lifecycle

import (
	"errors"
	"fmt"
	"os"
	"syscall"
	"unsafe"
)

func registerInstallPath(bin string) error {
	return registerInstallPathWith(bin, installPathOps{
		readUser: readInstallUserPath, writeUser: writeInstallUserPath,
		lookupEnv: os.LookupEnv, getProcess: func() string { return os.Getenv("Path") },
		setProcess: func(value string) error { return os.Setenv("Path", value) },
		broadcast:  broadcastInstallEnvironment,
	})
}

func installPathPreview(bin string) (bool, error) {
	return installPathPreviewWith(bin, readInstallUserPath, os.LookupEnv)
}

func readInstallUserPath() (installPathValue, error) {
	name, _ := syscall.UTF16PtrFromString("Environment")
	var key syscall.Handle
	err := syscall.RegOpenKeyEx(syscall.HKEY_CURRENT_USER, name, 0, syscall.KEY_QUERY_VALUE, &key)
	if errors.Is(err, syscall.ERROR_FILE_NOT_FOUND) {
		return installPathValue{kind: installPathREGExpandSZ}, nil
	}
	if err != nil {
		return installPathValue{}, err
	}
	defer syscall.RegCloseKey(key)
	return readInstallUserPathKey(key)
}

func readInstallUserPathKey(key syscall.Handle) (installPathValue, error) {
	name, _ := syscall.UTF16PtrFromString("Path")
	// A single bounded read avoids trusting a registry-controlled allocation
	// size and the size-query/read race. An oversized value fails closed.
	data := make([]byte, maxInstallPathUnits*2)
	size := uint32(len(data))
	var kind uint32
	err := syscall.RegQueryValueEx(key, name, nil, &kind, &data[0], &size)
	if errors.Is(err, syscall.ERROR_FILE_NOT_FOUND) {
		return installPathValue{kind: installPathREGExpandSZ}, nil
	}
	if errors.Is(err, syscall.ERROR_MORE_DATA) || size > uint32(len(data)) {
		return installPathValue{}, errors.New("user PATH exceeds the Windows environment-string limit")
	}
	if err != nil {
		return installPathValue{}, err
	}
	return decodeInstallPathValue(kind, data[:size])
}

func writeInstallUserPath(before, after installPathValue) error {
	data, err := encodeInstallPathValue(after)
	if err != nil {
		return err
	}
	name, _ := syscall.UTF16PtrFromString("Environment")
	var key syscall.Handle
	access := uint32(syscall.KEY_QUERY_VALUE | syscall.KEY_SET_VALUE)
	err = syscall.RegOpenKeyEx(syscall.HKEY_CURRENT_USER, name, 0, access, &key)
	if errors.Is(err, syscall.ERROR_FILE_NOT_FOUND) {
		proc := syscall.NewLazyDLL("advapi32.dll").NewProc("RegCreateKeyExW")
		if err := proc.Find(); err != nil {
			return err
		}
		status, _, _ := proc.Call(uintptr(syscall.HKEY_CURRENT_USER), uintptr(unsafe.Pointer(name)), 0, 0, 0, uintptr(access), 0, uintptr(unsafe.Pointer(&key)), 0)
		if status != 0 {
			return fmt.Errorf("create current-user Environment key: %w", syscall.Errno(status))
		}
	} else if err != nil {
		return err
	}
	defer syscall.RegCloseKey(key)
	// Detect intervening edits instead of deliberately overwriting a newer
	// PATH. Win32 has no atomic compare-and-set for a single registry value.
	current, err := readInstallUserPathKey(key)
	if err != nil {
		return err
	}
	if current != before {
		return errors.New("user PATH changed during registration; rerun the PATH registration")
	}
	pathName, _ := syscall.UTF16PtrFromString("Path")
	proc := syscall.NewLazyDLL("advapi32.dll").NewProc("RegSetValueExW")
	if err := proc.Find(); err != nil {
		return err
	}
	status, _, _ := proc.Call(uintptr(key), uintptr(unsafe.Pointer(pathName)), 0, uintptr(after.kind), uintptr(unsafe.Pointer(&data[0])), uintptr(len(data)))
	if status != 0 {
		return fmt.Errorf("set current-user Path value: %w", syscall.Errno(status))
	}
	return nil
}

func broadcastInstallEnvironment() {
	proc := syscall.NewLazyDLL("user32.dll").NewProc("SendMessageTimeoutW")
	if proc.Find() != nil {
		return
	}
	environment, _ := syscall.UTF16PtrFromString("Environment")
	var result uintptr
	// HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG. This notifies
	// interested applications; it cannot change the parent shell's PATH.
	proc.Call(0xffff, 0x001a, 0, uintptr(unsafe.Pointer(environment)), 0x0002, 1000, uintptr(unsafe.Pointer(&result)))
}
