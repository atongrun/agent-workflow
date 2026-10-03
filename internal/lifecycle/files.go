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
	"strconv"
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
		return nil
	}
	if e := validGoReleaseVersion(v); e != nil {
		return e
	}
	if prereleaseVersion(v) && !allowPrerelease {
		return errors.New("preview releases require explicit --allow-prerelease opt-in or saved channel approval")
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

// privateRoot retains its historical name for callers. The program root now
// keeps its ordinary per-user permissions; only dedicated data trees are private.
// Existing roots and descendants are inspected, never repaired or re-ACL'd.
func privateRoot(root string) error {
	if !filepath.IsAbs(root) {
		return errors.New("installation root must be absolute")
	}
	if e := os.MkdirAll(root, 0700); e != nil {
		return e
	}
	return validateInstallRoot(root)
}

// Legacy installs are deliberately not adopted or migrated. In particular,
// old control tokens at the program root must not be ignored as stopped state.
func rejectLegacyLayout(root string) error {
	for _, name := range []string{"data", "runtime.json", "starting.json"} {
		if _, e := os.Lstat(filepath.Join(root, name)); !os.IsNotExist(e) {
			if e != nil {
				return e
			}
			return fmt.Errorf("historical installation layout (%s) requires explicit recovery; fresh install does not migrate existing data", name)
		}
	}
	return nil
}

func validateInstallRoot(root string) error {
	st, e := os.Lstat(root)
	if e != nil {
		return e
	}
	if !st.IsDir() || st.Mode()&os.ModeSymlink != 0 {
		return errors.New("installation root must be a real directory, not a link")
	}
	if e = checkProgramPath(root); e != nil {
		return e
	}
	if e = rejectLegacyLayout(root); e != nil {
		return e
	}
	// Inspect by role without changing any descriptor. Never follow links or
	// accept a broad protected child merely because its parent is acceptable.
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
		role := pathPermissionRole(root, path)
		if err = checkPathPermissions(path, role); err != nil {
			return fmt.Errorf("installation %s permissions are unsafe: %s: %w", role, path, err)
		}
		return nil
	})
}

type permissionRole string

const (
	programPermissionRole permissionRole = "program"
	privatePermissionRole permissionRole = "private"
)

// Program files may be read by identities inherited from the user profile.
// Secrets, durable state and any AWF logs retain a strict private boundary.
func pathPermissionRole(root, path string) permissionRole {
	rel, e := filepath.Rel(root, path)
	if e != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return privatePermissionRole
	}
	first := strings.SplitN(rel, string(filepath.Separator), 2)[0]
	switch strings.ToLower(first) {
	case "credentials", "state", "private", "logs", "runtime.json", "starting.json":
		return privatePermissionRole
	}
	return programPermissionRole
}

func checkPathPermissions(path string, role permissionRole) error {
	if role == privatePermissionRole {
		return checkPrivatePath(path)
	}
	return checkProgramPath(path)
}

// permissionPolicyIssues is shared with the read-only doctor so its findings
// describe the same role-specific policy enforced by lifecycle commands. It is
// intentionally a small supported-ACL policy, not an effective-access engine.
func permissionPolicyIssues(m *doctorACLMetadata, role permissionRole) []string {
	var issues []string
	issue := func(s string) { issues = append(issues, s) }
	trusted := func(sid string) bool {
		return sid == m.CurrentUserSID || sid == "S-1-5-18" || role == programPermissionRole && sid == "S-1-5-32-544"
	}
	if m.OwnerSID == "" || m.CurrentUserSID == "" {
		m.Complete = false
	} else if !trusted(m.OwnerSID) {
		issue("owner is not trusted for this permission role")
	}
	switch m.DACLState {
	case "absent", "null":
		issue("unrestricted DACL is not allowed")
	case "present":
	default:
		m.Complete = false
	}
	seen := map[string]bool{}
	for _, e := range m.Entries {
		prefix := fmt.Sprintf("ACE %d: ", e.Index)
		if e.Type != 0 {
			issue(prefix + "not an ordinary ALLOW rule")
		}
		if e.Flags & ^uint8(0x1f) != 0 {
			issue(prefix + "unsupported access-rule flags")
		}
		mask, err := strconv.ParseUint(strings.TrimPrefix(e.Mask, "0x"), 16, 32)
		if err != nil || e.SID == "" || len(e.Issues) != 0 {
			m.Complete = false
			continue
		}
		full := mask == 0x001f01ff || mask == 0x10000000
		if role == privatePermissionRole {
			if !trusted(e.SID) {
				issue(prefix + "principal is neither current user nor SYSTEM")
			}
			if e.Flags&8 != 0 {
				issue(prefix + "inherit-only rule is ineffective on this object")
			}
			if !full {
				issue(prefix + "mask is not required full control")
			}
			if e.Type == 0 && e.Flags&8 == 0 && full {
				seen[e.SID] = true
			}
			continue
		}
		// FILE_GENERIC_READ/EXECUTE, their generic counterparts, READ_CONTROL
		// and SYNCHRONIZE cannot change a file, its children, or its security.
		const readOnlyMask = uint64(0xa01200a9)
		// A standard inherited CREATOR OWNER template applies only to children,
		// where Windows substitutes their actual owner. It grants no effective
		// access here; descendant owners and descriptors are checked separately.
		if e.Type == 0 && e.SID == "S-1-3-0" && e.Flags&0x18 == 0x18 {
			continue
		}
		if !trusted(e.SID) && (e.Flags&0x10 == 0 || mask & ^readOnlyMask != 0) {
			issue(prefix + "other principals require inherited read-only access")
		}
		// The current user must be able to create/write program files. Trusted
		// SYSTEM/Administrators ALLOW entries need not have an exact full mask.
		if e.Type == 0 && e.Flags&8 == 0 && mask&(0x50000000|0x2) != 0 {
			seen[e.SID] = true
		}
	}
	if m.DACLState == "present" {
		if m.CurrentUserSID != "" && !seen[m.CurrentUserSID] {
			if role == privatePermissionRole {
				issue("current-user full-control ALLOW rule not observed")
			} else {
				issue("current-user write ALLOW rule not observed")
			}
		}
		if role == privatePermissionRole && !seen["S-1-5-18"] {
			issue("SYSTEM full-control ALLOW rule not observed")
		}
	}
	return issues
}
func exclusive(root string) (*os.File, error) {
	f, e := lockFile(filepath.Join(root, "lifecycle.lock"))
	if e != nil {
		return nil, fmt.Errorf("another lifecycle command is running or lock is unavailable: %w", e)
	}
	return f, nil
}

func managedDirectory(root string, parts ...string) (string, error) {
	// Validate all components before creating anything.
	for _, part := range parts {
		if part == "" || part == "." || part == ".." || filepath.Base(part) != part || strings.ContainsAny(part, `\/:`) {
			return "", errors.New("invalid managed directory component")
		}
	}
	st, e := os.Lstat(root)
	if e != nil {
		return "", e
	}
	if !st.IsDir() || st.Mode()&os.ModeSymlink != 0 {
		return "", errors.New("managed root must be a real directory")
	}
	if e = checkProgramPath(root); e != nil {
		return "", e
	}
	if e = rejectLegacyLayout(root); e != nil {
		return "", e
	}
	p := root
	for _, part := range parts {
		p = filepath.Join(p, part)
		role := pathPermissionRole(root, p)
		st, e := os.Lstat(p)
		if os.IsNotExist(e) {
			if role == privatePermissionRole {
				e = createPrivateDirectory(p)
			} else {
				e = os.Mkdir(p, 0700)
			}
			if e != nil {
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
		if e = checkPathPermissions(p, role); e != nil {
			return "", e
		}
	}
	return p, nil
}
