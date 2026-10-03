package lifecycle

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"unsafe"
)

func checkInstallerContext() error {
	return validateInstallerPackage(currentPackageIdentity())
}

func currentPackageIdentity() (uint32, error) {
	proc := syscall.NewLazyDLL("kernel32.dll").NewProc("GetCurrentPackageFullName")
	if e := proc.Find(); e != nil {
		return 0, e
	}
	var length uint32
	status, _, _ := proc.Call(uintptr(unsafe.Pointer(&length)), 0)
	return uint32(status), nil
}

func checkInstallerPath(path string, allowMissing bool) error {
	actual, e := finalInstallerPath(path)
	if allowMissing && os.IsNotExist(e) {
		return nil
	}
	return validateInstallerPath(filepath.Clean(path), actual, e)
}

func finalInstallerPath(path string) (string, error) {
	proc := syscall.NewLazyDLL("kernel32.dll").NewProc("GetFinalPathNameByHandleW")
	if e := proc.Find(); e != nil {
		return "", e
	}
	p, e := syscall.UTF16PtrFromString(path)
	if e != nil {
		return "", e
	}
	h, e := syscall.CreateFile(p, 0, syscall.FILE_SHARE_READ|syscall.FILE_SHARE_WRITE|syscall.FILE_SHARE_DELETE, nil, syscall.OPEN_EXISTING, syscall.FILE_FLAG_BACKUP_SEMANTICS, 0)
	if e != nil {
		return "", e
	}
	defer syscall.CloseHandle(h)
	// Windows paths are bounded to 32,767 UTF-16 code units. Request the
	// normalized DOS path (flags=0), including a slot for the terminator.
	b := make([]uint16, 32768)
	n, _, callErr := proc.Call(uintptr(h), uintptr(unsafe.Pointer(&b[0])), uintptr(len(b)), 0)
	if n == 0 {
		return "", fmt.Errorf("GetFinalPathNameByHandleW: %w", callErr)
	}
	if n >= uintptr(len(b)) {
		return "", errors.New("GetFinalPathNameByHandleW returned an oversized path")
	}
	return syscall.UTF16ToString(b[:n]), nil
}

func replaceFile(a, b string) error {
	ap, e := syscall.UTF16PtrFromString(a)
	if e != nil {
		return e
	}
	bp, e := syscall.UTF16PtrFromString(b)
	if e != nil {
		return e
	}
	r, _, e := syscall.NewLazyDLL("kernel32.dll").NewProc("MoveFileExW").Call(uintptr(unsafe.Pointer(ap)), uintptr(unsafe.Pointer(bp)), 0x1|0x8)
	if r == 0 {
		return e
	}
	return nil
}
func rejectReparsePath(p string) error {
	path, e := syscall.UTF16PtrFromString(p)
	if e != nil {
		return e
	}
	attributes, e := syscall.GetFileAttributes(path)
	if e != nil {
		return e
	}
	return rejectReparseAttributes(attributes)
}
func rejectReparseAttributes(attributes uint32) error {
	if attributes&syscall.FILE_ATTRIBUTE_REPARSE_POINT != 0 {
		return errors.New("installation paths must not be Windows reparse points")
	}
	return nil
}

// createPrivateDirectory installs its protected DACL in the same Win32 call
// that creates the directory. Existing paths are never opened for ACL writes.
func createPrivateDirectory(p string) error {
	token, e := syscall.OpenCurrentProcessToken()
	if e != nil {
		return e
	}
	defer token.Close()
	current, e := token.GetTokenUser()
	if e != nil {
		return e
	}
	id, e := current.User.Sid.String()
	if e != nil {
		return e
	}
	sddl, e := syscall.UTF16PtrFromString("O:" + id + "D:P(A;OICI;FA;;;" + id + ")(A;OICI;FA;;;SY)")
	if e != nil {
		return e
	}
	var sd uintptr
	advapi := syscall.NewLazyDLL("advapi32.dll")
	r, _, callErr := advapi.NewProc("ConvertStringSecurityDescriptorToSecurityDescriptorW").Call(uintptr(unsafe.Pointer(sddl)), 1, uintptr(unsafe.Pointer(&sd)), 0)
	if r == 0 {
		return fmt.Errorf("cannot create private AWF directory ACL: %w", callErr)
	}
	defer syscall.LocalFree(syscall.Handle(sd))
	path, e := syscall.UTF16PtrFromString(p)
	if e != nil {
		return e
	}
	sa := syscall.SecurityAttributes{Length: uint32(unsafe.Sizeof(syscall.SecurityAttributes{})), SecurityDescriptor: sd}
	r, _, callErr = syscall.NewLazyDLL("kernel32.dll").NewProc("CreateDirectoryW").Call(uintptr(unsafe.Pointer(path)), uintptr(unsafe.Pointer(&sa)))
	if r == 0 {
		return &os.PathError{Op: "CreateDirectoryW", Path: p, Err: callErr}
	}
	return checkPrivatePath(p)
}
func lockFile(p string) (*os.File, error) {
	f, e := os.OpenFile(p, os.O_CREATE|os.O_RDWR, 0600)
	if e != nil {
		return nil, e
	}
	var o syscall.Overlapped
	r, _, e := syscall.NewLazyDLL("kernel32.dll").NewProc("LockFileEx").Call(f.Fd(), 3, 0, 1, 0, uintptr(unsafe.Pointer(&o)))
	if r == 0 {
		f.Close()
		return nil, e
	}
	return f, nil
}
func detach(c *exec.Cmd) {
	c.SysProcAttr = &syscall.SysProcAttr{CreationFlags: 0x00000008 | 0x00000200, HideWindow: true}
}

type blob struct {
	Size uint32
	Data *byte
}

func bytesBlob(b []byte) blob {
	if len(b) == 0 {
		return blob{}
	}
	return blob{uint32(len(b)), &b[0]}
}
func readNodeToken(path string) (string, error) {
	// Explicit credential locations outside the installation follow the same
	// helper privacy contract. Inspection never rewrites those external ACLs.
	if e := checkPrivatePath(filepath.Dir(path)); e != nil {
		return "", errors.New("paired credential directory must be private to the current user and SYSTEM, with no reparse point")
	}
	if e := checkPrivatePath(path); e != nil {
		return "", errors.New("paired credential file must be private to the current user and SYSTEM, with no reparse point")
	}
	b, e := readBounded(path, 64<<10)
	if e != nil {
		return "", errors.New("paired node credential is missing or unreadable; run awf pair first")
	}
	if len(b) == 0 || len(b) > 64<<10 {
		return "", errors.New("invalid DPAPI credential size")
	}
	in := bytesBlob(b)
	entropy := bytesBlob([]byte("AWF Windows node pairing v1"))
	var out blob
	r, _, _ := syscall.NewLazyDLL("crypt32.dll").NewProc("CryptUnprotectData").Call(uintptr(unsafe.Pointer(&in)), 0, uintptr(unsafe.Pointer(&entropy)), 0, 0, 1, uintptr(unsafe.Pointer(&out)))
	if r == 0 {
		return "", errors.New("cannot decrypt paired node credential as this Windows user")
	}
	defer syscall.LocalFree(syscall.Handle(uintptr(unsafe.Pointer(out.Data))))
	plain := unsafe.Slice(out.Data, out.Size)
	defer func() {
		for i := range plain {
			plain[i] = 0
		}
	}()
	if len(plain) != 64 {
		return "", errors.New("paired credential has invalid format")
	}
	for _, c := range plain {
		if !(c >= '0' && c <= '9' || c >= 'A' && c <= 'F') {
			return "", errors.New("paired credential has invalid format")
		}
	}
	return string(plain), nil
}
func setAutostart(root string, enable bool) error {
	// A per-user Run value needs no scheduler service, administrator, or shell.
	// The launcher path and arguments are quoted by Windows' documented argv rules.
	value := "AWF Native Node"
	key := `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
	systemRoot := os.Getenv("SystemRoot")
	if !filepath.IsAbs(systemRoot) {
		return errors.New("Windows SystemRoot is unavailable")
	}
	registryTool := filepath.Join(systemRoot, "System32", "reg.exe")
	var c *exec.Cmd
	if enable {
		c = exec.Command(registryTool, "ADD", key, "/v", value, "/t", "REG_SZ", "/d", syscall.EscapeArg(filepath.Join(root, "bin", "awf.exe"))+" start", "/f")
	} else {
		c = exec.Command(registryTool, "DELETE", key, "/v", value, "/f")
	}
	if e := c.Run(); e != nil {
		return fmt.Errorf("could not update per-user login autostart: %w", e)
	}
	return nil
}

func checkPrivatePath(p string) error { return inspectPathPermissions(p, privatePermissionRole) }
func checkProgramPath(p string) error { return inspectPathPermissions(p, programPermissionRole) }

func inspectPathPermissions(p string, role permissionRole) error {
	if e := rejectReparsePath(p); e != nil {
		return e
	}
	m := inspectDoctorACL(p)
	issues := permissionPolicyIssues(&m, role)
	if !m.Complete {
		return errors.New("path security descriptor could not be completely inspected")
	}
	if len(issues) != 0 {
		return fmt.Errorf("path does not satisfy %s permissions: %s", role, issues[0])
	}
	return nil
}
