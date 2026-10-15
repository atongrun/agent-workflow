// Package privatefile creates new private files without changing existing
// objects or their permissions. Callers must provide and validate a safe parent
// directory; this package does not establish or repair a directory boundary.
package privatefile

import (
	"crypto/rand"
	"encoding/hex"
	"os"
	"path/filepath"
	"strings"
)

// CreateTemp creates an exclusive, randomly named private file in dir. Prefix
// is a filename prefix, not a path or an os.CreateTemp wildcard pattern.
func CreateTemp(dir, prefix string) (*os.File, error) {
	if strings.ContainsAny(prefix, `/\\`) {
		return nil, &os.PathError{Op: "createtemp", Path: dir, Err: os.ErrInvalid}
	}
	for i := 0; i < 10; i++ {
		var nonce [16]byte
		if _, err := rand.Read(nonce[:]); err != nil {
			return nil, err
		}
		f, err := Create(filepath.Join(dir, prefix+hex.EncodeToString(nonce[:])))
		if !os.IsExist(err) {
			return f, err
		}
	}
	return nil, &os.PathError{Op: "createtemp", Path: dir, Err: os.ErrExist}
}

// OpenLock gives a new lock file private ownership. An existing lock is opened
// without truncation, replacement, or any ACL/owner write; caller validation and
// locking remain responsible for accepting and protecting that existing object.
func OpenLock(path string) (*os.File, error) {
	f, err := Create(path)
	if os.IsExist(err) {
		return openExisting(path)
	}
	return f, err
}
