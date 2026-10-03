package lifecycle

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"unsafe"
)

func systemSSH() (string, error) {
	root := os.Getenv("SystemRoot")
	if !filepath.IsAbs(root) {
		return "", errors.New("Windows SystemRoot is unavailable")
	}
	p := filepath.Join(root, "System32", "OpenSSH", "ssh.exe")
	st, e := os.Stat(p)
	if e != nil || !st.Mode().IsRegular() {
		return "", errors.New("native Windows OpenSSH client is required")
	}
	return p, nil
}
func validateCredentialAncestors(p string) error {
	volume := filepath.VolumeName(p)
	if len(volume) != 2 || volume[1] != ':' || strings.ContainsAny(strings.TrimPrefix(p, volume), ":\r\n\x00") {
		return errors.New("pairing requires a local drive path without alternate data streams")
	}
	for current := p; ; current = filepath.Dir(current) {
		if e := rejectReparsePath(current); e != nil && !os.IsNotExist(e) {
			return errors.New("credential path has a reparse point or inaccessible ancestor")
		}
		if filepath.Dir(current) == current {
			return nil
		}
	}
}
func writeNodeToken(root, path, token string) error {
	if e := validatePairLocalPath(root, path); e != nil {
		return e
	}
	if path == filepath.Join(root, "credentials", "windows-node", "node-token.dpapi") {
		if _, e := managedDirectory(root, "credentials", "windows-node"); e != nil {
			return e
		}
	}
	if e := checkPrivatePath(filepath.Dir(path)); e != nil {
		return errors.New("credential parent must be private to the current user and SYSTEM")
	}
	if len(token) != 64 || strings.IndexFunc(token, func(c rune) bool { return !(c >= '0' && c <= '9' || c >= 'A' && c <= 'F') }) >= 0 {
		return errors.New("invalid new credential format")
	}
	plain := []byte(token)
	defer func() {
		for i := range plain {
			plain[i] = 0
		}
	}()
	input, entropy := bytesBlob(plain), bytesBlob([]byte("AWF Windows node pairing v1"))
	var output blob
	r, _, _ := syscall.NewLazyDLL("crypt32.dll").NewProc("CryptProtectData").Call(uintptr(unsafe.Pointer(&input)), 0, uintptr(unsafe.Pointer(&entropy)), 0, 0, 1, uintptr(unsafe.Pointer(&output)))
	if r == 0 {
		return errors.New("CurrentUser DPAPI protection failed")
	}
	defer syscall.LocalFree(syscall.Handle(uintptr(unsafe.Pointer(output.Data))))
	encrypted := unsafe.Slice(output.Data, output.Size)
	// CREATE_NEW semantics: never replace an identity, including an interrupted
	// file or one concurrently created after the user reviewed the plan.
	f, e := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if e != nil {
		return errors.New("credential destination already exists or cannot be created; nothing was overwritten")
	}
	defer f.Close()
	if e = checkPrivatePath(path); e != nil {
		return errors.New("new credential file did not inherit private permissions; it was retained for explicit recovery")
	}
	if _, e = f.Write(encrypted); e != nil {
		return errors.New("encrypted credential write failed; file retained for explicit recovery")
	}
	if e = f.Sync(); e != nil {
		return errors.New("encrypted credential sync failed; file retained for explicit recovery")
	}
	if e = f.Close(); e != nil {
		return errors.New("encrypted credential close failed; file retained for explicit recovery")
	}
	// Read through the same privacy/DPAPI contract the managed node uses.
	read, e := readNodeToken(path)
	if e != nil || read != token {
		return errors.New("new encrypted credential failed verification; file retained for explicit recovery")
	}
	return nil
}
