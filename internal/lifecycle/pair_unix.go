//go:build !windows

package lifecycle

import (
	"errors"
	"os"
	"path/filepath"
)

func systemSSH() (string, error) {
	return "", errors.New("managed pairing requires native Windows OpenSSH")
}
func writeNodeToken(string, string, string) error {
	return errors.New("CurrentUser DPAPI node credentials require native Windows")
}
func validateCredentialAncestors(p string) error {
	for current := p; ; current = filepath.Dir(current) {
		st, e := os.Lstat(current)
		if e != nil && !os.IsNotExist(e) {
			return errors.New("credential path has an inaccessible ancestor")
		}
		if e == nil && st.Mode()&os.ModeSymlink != 0 {
			return errors.New("credential path must not contain links")
		}
		if filepath.Dir(current) == current {
			return nil
		}
	}
}
