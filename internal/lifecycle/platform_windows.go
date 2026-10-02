package lifecycle

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"syscall"
	"unsafe"
)

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
func protectDirectory(p string) error {
	if e := rejectReparsePath(p); e != nil {
		return e
	}
	u, e := user.Current()
	if e != nil {
		return e
	}

	// Replace the entire DACL, including old explicit entries; chmod and granting
	// two identities alone do not make an existing Windows directory private.
	sddl, e := syscall.UTF16PtrFromString("D:P(A;OICI;FA;;;" + u.Uid + ")(A;OICI;FA;;;SY)")
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
	var present, defaulted int32
	var dacl uintptr
	r, _, callErr = advapi.NewProc("GetSecurityDescriptorDacl").Call(sd, uintptr(unsafe.Pointer(&present)), uintptr(unsafe.Pointer(&dacl)), uintptr(unsafe.Pointer(&defaulted)))
	if r == 0 || present == 0 {
		return errors.New("cannot inspect private AWF directory ACL")
	}
	path, e := syscall.UTF16PtrFromString(p)
	if e != nil {
		return e
	}
	r, _, _ = advapi.NewProc("SetNamedSecurityInfoW").Call(uintptr(unsafe.Pointer(path)), 1, 0x80000004, 0, 0, dacl, 0)
	if r != 0 {
		return fmt.Errorf("cannot protect AWF directory: Windows error %d", r)
	}

	return nil
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
		return "", errors.New("paired node credential is missing or unreadable; run your user-approved pairing helper first")
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

func checkPrivatePath(p string) error {
	if e := rejectReparsePath(p); e != nil {
		return e
	}
	u, e := user.Current()
	if e != nil {
		return e
	}
	path, e := syscall.UTF16PtrFromString(p)
	if e != nil {
		return e
	}
	var sd, dacl uintptr
	var owner *syscall.SID
	advapi := syscall.NewLazyDLL("advapi32.dll")
	r, _, _ := advapi.NewProc("GetNamedSecurityInfoW").Call(uintptr(unsafe.Pointer(path)), 1, 5, uintptr(unsafe.Pointer(&owner)), 0, uintptr(unsafe.Pointer(&dacl)), 0, uintptr(unsafe.Pointer(&sd)))
	if r != 0 {
		return fmt.Errorf("cannot inspect path ACL: Windows error %d", r)
	}
	defer syscall.LocalFree(syscall.Handle(sd))
	if owner == nil {
		return errors.New("path owner is unknown")
	}
	ownerID, e := owner.String()
	if e != nil {
		return e
	}
	if ownerID != u.Uid && ownerID != "S-1-5-18" {
		return errors.New("path is owned by an identity other than the current user or SYSTEM")
	}
	if dacl == 0 {
		return errors.New("unrestricted path DACL is not allowed")
	}
	var info struct{ Count, Used, Free uint32 }
	r, _, callErr := advapi.NewProc("GetAclInformation").Call(dacl, uintptr(unsafe.Pointer(&info)), unsafe.Sizeof(info), 2)
	if r == 0 {
		return callErr
	}
	seen := map[string]bool{}
	for i := uint32(0); i < info.Count; i++ {
		var ace unsafe.Pointer
		r, _, callErr = advapi.NewProc("GetAce").Call(dacl, uintptr(i), uintptr(unsafe.Pointer(&ace)))
		if r == 0 {
			return callErr
		}
		header := (*struct {
			Type, Flags uint8
			Size        uint16
		})(ace)
		if header.Type != 0 || header.Flags&8 != 0 || header.Size < 16 {
			return errors.New("path has unsupported or ineffective access rules")
		}
		mask := *(*uint32)(unsafe.Add(ace, 4))
		sid := (*syscall.SID)(unsafe.Add(ace, 8))
		identity, e := sid.String()
		if e != nil {
			return e
		}
		if identity != u.Uid && identity != "S-1-5-18" {
			return errors.New("path permits an identity other than the current user or SYSTEM")
		}
		if mask != 0x1f01ff && mask != 0x10000000 {
			return errors.New("path lacks the required full-control private access rule")
		}
		seen[identity] = true
	}
	if !seen[u.Uid] || !seen["S-1-5-18"] {
		return errors.New("path must explicitly permit the current user and SYSTEM")
	}
	return nil
}
