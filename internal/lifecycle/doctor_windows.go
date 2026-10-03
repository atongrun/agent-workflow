package lifecycle

import (
	"errors"
	"fmt"
	"syscall"
	"unsafe"
)

func nativeDoctorPlatform() doctorPlatform {
	return doctorPlatform{
		context: func() (string, string) {
			status, err := currentPackageIdentity()
			if err != nil {
				return "unknown", "package identity API unavailable"
			}
			switch status {
			case appModelErrorNoPackage:
				return "unpackaged", "NO_PACKAGE; this alone does not establish unredirected storage"
			case 0, errorInsufficientBuffer:
				return "packaged", "package identity present; installation is blocked in this context"
			default:
				return "unknown", fmt.Sprintf("package identity API status %d", status)
			}
		},
		programsFolder: knownProgramsFolder,
		physical:       finalInstallerPath,
		aclDetails:     inspectDoctorACL,
		reparse:        rejectReparsePath,
	}
}

func knownProgramsFolder() (string, error) {
	// FOLDERID_UserProgramFiles; DONT_VERIFY resolves an absent Programs folder
	// without creating it. Install creates it only after consent.
	id := syscall.GUID{Data1: 0x5CD7AEE2, Data2: 0x2219, Data3: 0x4A67, Data4: [8]byte{0xB8, 0x5D, 0x6C, 0x9C, 0xE1, 0x56, 0x60, 0xCB}}
	var path *uint16
	proc := syscall.NewLazyDLL("shell32.dll").NewProc("SHGetKnownFolderPath")
	if err := proc.Find(); err != nil {
		return "", err
	}
	r, _, _ := proc.Call(uintptr(unsafe.Pointer(&id)), 0x4000, 0, uintptr(unsafe.Pointer(&path)))
	if r != 0 || path == nil {
		return "", errors.New("known folder unavailable")
	}
	defer syscall.NewLazyDLL("ole32.dll").NewProc("CoTaskMemFree").Call(uintptr(unsafe.Pointer(path)))
	// Windows known-folder paths are NUL-terminated and MAX_LONG_PATH bounded.
	var units []uint16
	for i := 0; i < 32768; i++ {
		v := *(*uint16)(unsafe.Add(unsafe.Pointer(path), uintptr(i)*2))
		if v == 0 {
			return syscall.UTF16ToString(units), nil
		}
		units = append(units, v)
	}
	return "", errors.New("known folder path exceeds limit")
}
