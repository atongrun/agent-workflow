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
		localAppData: doctorKnownLocalAppData,
		physical:     finalInstallerPath,
		acl: func(path string) (string, error) {
			if err := checkPrivatePath(path); err != nil {
				// The validator inspects ownership and ACE metadata only. Do not
				// The errors below contain only metadata validation reasons/API
				// error codes, never credential bytes or parsed file contents.
				return "private ACL policy not established: " + err.Error(), err
			}
			return "owner and full-control DACL satisfy current-user/SYSTEM-only policy", nil
		},
		reparse: rejectReparsePath,
	}
}

func doctorKnownLocalAppData() (string, error) {
	// SHGetKnownFolderPath without KF_FLAG_CREATE never creates the directory.
	id := syscall.GUID{Data1: 0xF1B32785, Data2: 0x6FBA, Data3: 0x4FCF, Data4: [8]byte{0x9D, 0x55, 0x7B, 0x8E, 0x7F, 0x15, 0x70, 0x91}}
	var path *uint16
	proc := syscall.NewLazyDLL("shell32.dll").NewProc("SHGetKnownFolderPath")
	if err := proc.Find(); err != nil {
		return "", err
	}
	r, _, _ := proc.Call(uintptr(unsafe.Pointer(&id)), 0, 0, uintptr(unsafe.Pointer(&path)))
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
