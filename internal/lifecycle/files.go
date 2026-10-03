// Package lifecycle implements the opt-in, per-user native Windows CLI lifecycle.
// Credential pairing is separately confirmed. It does not install OpenCode, change firewall policy, or run Git.
package lifecycle

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

const Repository = "atongrun/agent-workflow"

var Version = "dev" // Set by the release packaging script.
var versionRE = regexp.MustCompile(`^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-rc\.(0|[1-9][0-9]*))?$`)

type Pointer struct {
	Version string `json:"version"`
}
type Manifest struct {
	Version string `json:"version"`
	OS      string `json:"os"`
	Arch    string `json:"arch"`
}

func validVersion(v string) error {
	if !versionRE.MatchString(v) {
		return errors.New("version must be an exact canonical vX.Y.Z or vX.Y.Z-rc.N release tag")
	}
	return nil
}
func prereleaseVersion(v string) bool { return strings.Contains(v, "-rc.") }
func validateReleaseRequest(v string, allowPrerelease bool) error {
	if v == "" {
		if allowPrerelease {
			return errors.New("--allow-prerelease requires an explicit --version vX.Y.Z-rc.N")
		}
		return nil
	}
	if e := validVersion(v); e != nil {
		return e
	}
	if prereleaseVersion(v) && !allowPrerelease {
		return errors.New("a pinned RC requires explicit --allow-prerelease opt-in")
	}
	return nil
}

// Canonical numeric strings avoid integer overflow when comparing release tags.
func compareReleaseVersions(a, b string) (int, error) {
	x, y := versionRE.FindStringSubmatch(a), versionRE.FindStringSubmatch(b)
	if x == nil || y == nil {
		return 0, errors.New("cannot compare invalid release versions")
	}
	compare := func(a, b string) int {
		if len(a) < len(b) {
			return -1
		}
		if len(a) > len(b) {
			return 1
		}
		return strings.Compare(a, b)
	}
	for i := 1; i <= 3; i++ {
		if c := compare(x[i], y[i]); c != 0 {
			return c, nil
		}
	}
	if x[4] == "" && y[4] == "" {
		return 0, nil
	}
	if x[4] == "" {
		return 1, nil
	}
	if y[4] == "" {
		return -1, nil
	}
	return compare(x[4], y[4]), nil
}

func DefaultRoot() (string, error) {
	p := os.Getenv("LOCALAPPDATA")
	if p == "" || !filepath.IsAbs(p) {
		return "", errors.New("LOCALAPPDATA must be an absolute per-user directory")
	}
	return filepath.Join(p, "AWF"), nil
}
func readJSON(path string, v any) error {
	b, e := readBounded(path, 2<<20)
	if e != nil {
		return e
	}
	d := json.NewDecoder(bytes.NewReader(b))
	d.DisallowUnknownFields()
	if e = d.Decode(v); e != nil {
		return e
	}
	if d.Decode(new(any)) != io.EOF {
		return errors.New("expected exactly one JSON object")
	}
	return nil
}
func readBounded(path string, limit int64) ([]byte, error) {
	f, e := os.Open(path)
	if e != nil {
		return nil, e
	}
	defer f.Close()
	st, e := f.Stat()
	if e != nil {
		return nil, e
	}
	if !st.Mode().IsRegular() || st.Size() > limit {
		return nil, errors.New("input must be a bounded regular file")
	}
	b, e := io.ReadAll(io.LimitReader(f, limit+1))
	if e != nil {
		return nil, e
	}
	if int64(len(b)) > limit {
		return nil, errors.New("input exceeds size limit")
	}
	return b, nil
}

func writeJSON(path string, v any) error {
	b, e := json.MarshalIndent(v, "", "  ")
	if e != nil {
		return e
	}
	return atomicWrite(path, append(b, '\n'))
}
func atomicWrite(path string, b []byte) error {
	f, e := os.CreateTemp(filepath.Dir(path), ".awf-*")
	if e != nil {
		return e
	}
	name := f.Name()
	defer os.Remove(name)
	if e = f.Chmod(0600); e == nil {
		_, e = f.Write(b)
	}
	if e == nil {
		e = f.Sync()
	}
	ce := f.Close()
	if e == nil {
		e = ce
	}
	if e != nil {
		return e
	}
	return replaceFile(name, path)
}
func current(root string) (Pointer, error) {
	var p Pointer
	e := readJSON(filepath.Join(root, "current.json"), &p)
	if e == nil {
		e = validVersion(p.Version)
	}
	return p, e
}
func binary(root, v string) string { return filepath.Join(root, "versions", v, "awf.exe") }
func privateRoot(root string) error {
	if !filepath.IsAbs(root) {
		return errors.New("installation root must be absolute")
	}
	if e := os.MkdirAll(root, 0700); e != nil {
		return e
	}
	st, e := os.Lstat(root)
	if e != nil {
		return e
	}
	if !st.IsDir() || st.Mode()&os.ModeSymlink != 0 {
		return errors.New("installation root must be a real directory, not a link")
	}
	if e = protectDirectory(root); e != nil {
		return e
	}
	return validateInstallRoot(root)
}
func validateInstallRoot(root string) error {
	st, e := os.Lstat(root)
	if e != nil {
		return e
	}
	if !st.IsDir() || st.Mode()&os.ModeSymlink != 0 {
		return errors.New("installation root must be a real directory, not a link")
	}
	if e = checkPrivatePath(root); e != nil {
		return e
	}
	// Existing protected or explicitly broad children must not be trusted merely
	// because their parent is private. Never follow installation reparse points.
	return filepath.WalkDir(root, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if path == root {
			return nil
		}
		if entry.Type()&os.ModeSymlink != 0 {
			return errors.New("installation contains a linked/reparse path; explicit recovery is required")
		}
		info, err := entry.Info()
		if err != nil {
			return err
		}
		if !info.IsDir() && !info.Mode().IsRegular() {
			return errors.New("installation contains a non-regular path")
		}
		if err = checkPrivatePath(path); err != nil {
			return fmt.Errorf("installation descendant is not private: %s: %w", path, err)
		}
		return nil
	})
}
func exclusive(root string) (*os.File, error) {
	f, e := lockFile(filepath.Join(root, "lifecycle.lock"))
	if e != nil {
		return nil, fmt.Errorf("another lifecycle command is running or lock is unavailable: %w", e)
	}
	return f, nil
}

func managedDirectory(root string, parts ...string) (string, error) {
	p := root
	for _, part := range parts {
		if part == "" || part == "." || part == ".." || filepath.Base(part) != part {
			return "", errors.New("invalid managed directory component")
		}
		p = filepath.Join(p, part)
		st, e := os.Lstat(p)
		if os.IsNotExist(e) {
			if e = os.Mkdir(p, 0700); e != nil {
				return "", e
			}
			st, e = os.Lstat(p)
		}
		if e != nil {
			return "", e
		}
		if st.Mode()&os.ModeSymlink != 0 || !st.IsDir() {
			return "", errors.New("managed directory must be a real directory, never a reparse point")
		}
		if e = checkPrivatePath(p); e != nil {
			return "", e
		}
	}
	return p, nil
}
