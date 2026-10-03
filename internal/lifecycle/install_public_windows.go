package lifecycle

import (
	"errors"
	"syscall"
	"unsafe"
)

func nativeFreshInstallOps() freshInstallOps {
	return freshInstallOps{context: checkInstallerContext, knownFolder: knownProgramsFolder, architecture: nativeInstallArchitecture, path: checkInstallerPath, reparse: rejectReparsePath, checkParent: checkProgramPath, checkRoot: validateInstallRoot, finish: finishInstall, registerPath: registerInstallPath, previewPath: installPathPreview}
}
func nativeInstallArchitecture() (string, error) {
	var processMachine, nativeMachine uint16
	proc := syscall.NewLazyDLL("kernel32.dll").NewProc("IsWow64Process2")
	if err := proc.Find(); err != nil {
		return "", errors.New("cannot detect native architecture; Windows 10/Server 1709 or newer is required")
	}
	r, _, _ := proc.Call(^uintptr(0), uintptr(unsafe.Pointer(&processMachine)), uintptr(unsafe.Pointer(&nativeMachine)))
	if r == 0 {
		return "", errors.New("native Windows architecture lookup failed")
	}
	switch nativeMachine {
	case 0x8664:
		return "amd64", nil
	case 0xaa64:
		return "arm64", nil
	}
	return "", errors.New("native Windows AMD64 or ARM64 is required")
}
