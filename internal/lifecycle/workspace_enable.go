package lifecycle

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/atongrun/agent-workflow/internal/node"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
)

// Run owns the existing lifecycle lock. A child supervisor also takes the
// startup/runtime locks; hold them and the native writer lease until commit.
func enableWorkspace(root string, out io.Writer) error {
	return enableWorkspaceWith(root, out, atomicWrite)
}
func enableWorkspaceWith(root string, out io.Writer, save func(string, []byte) error) error {
	startup, err := lockFile(filepath.Join(root, "startup.lock"))
	if err != nil {
		return errors.New("startup ownership is unknown; workspace was not changed")
	}
	defer startup.Close()
	runtimeGuard, err := lockFile(filepath.Join(root, "runtime.lock"))
	if err != nil {
		return errors.New("runtime is active or unknown; stop AWF while idle before enabling workspace")
	}
	defer runtimeGuard.Close()
	if err = noPendingStartup(root); err != nil {
		return err
	}
	if _, err = os.Lstat(runtimePath(root)); !os.IsNotExist(err) {
		return errors.New("runtime identity exists or is unknown; stop AWF safely before enabling workspace")
	}
	original, err := readBounded(filepath.Join(root, "config.json"), 2<<20)
	if err != nil {
		return errors.New("configuration snapshot unavailable")
	}
	cfg, err := parseWorkspaceConfig(root, original)
	if err != nil {
		return errors.New("existing configuration could not be validated; workspace was not changed")
	}
	if _, reserved := cfg.Node.Projects["managed"]; reserved {
		return errors.New("managed is a reserved project ID; workspace was not changed")
	}
	idle, err := node.OfflineIdle(cfg.Node)
	if err != nil {
		return errors.New("native job state is active or unknown; workspace was not changed")
	}
	defer idle.Close()
	target := filepath.Join(root, "private", "managed-workspaces")
	realRoot, err := filepath.EvalSymlinks(root)
	if err != nil {
		return errors.New("installation root could not be resolved")
	}
	realTarget := filepath.Join(realRoot, "private", "managed-workspaces")
	for _, project := range cfg.Node.Projects {
		project, err = filepath.EvalSymlinks(project)
		if err != nil {
			return errors.New("existing project path could not be verified")
		}
		for _, pair := range [][2]string{{realTarget, project}, {project, realTarget}} {
			rel, e := filepath.Rel(pair[0], pair[1])
			if e == nil && (rel == "." || rel != ".." && !isOutsideRelative(rel)) {
				return errors.New("default managed workspace overlaps an existing project; nothing was changed")
			}
		}
	}
	if cfg.Node.ManagedRoot != "" {
		if !sameWorkspacePath(cfg.Node.ManagedRoot, target) {
			return errors.New("another managed root is already configured; relocation is not supported")
		}
		if err = checkPrivatePath(target); err != nil {
			return errors.New("configured default managed workspace cannot be verified")
		}
		st, e := os.Stat(target)
		if e != nil || !st.IsDir() {
			return errors.New("configured default managed workspace is missing")
		}
		fmt.Fprintln(out, "Default managed workspace is already enabled. Existing projects and identity were preserved.")
		return nil
	}
	if _, err = os.Lstat(target); !os.IsNotExist(err) {
		return errors.New("default workspace path already exists or is unknown; existing content was not adopted")
	}
	if _, err = managedDirectory(root, "private"); err != nil {
		return err
	}
	if err = createPrivateDirectory(target); err != nil {
		return errors.New("default private workspace could not be created")
	}
	committed := false
	defer func() {
		if !committed {
			_ = os.Remove(target)
		}
	}()
	next := cfg
	next.Node.ManagedRoot = target
	data, err := json.MarshalIndent(next, "", "  ")
	data = append(data, '\n')
	if err != nil {
		return err
	}
	path := filepath.Join(root, "config.json")
	latest, e := readBounded(path, 2<<20)
	if e != nil || !bytes.Equal(latest, original) {
		return errors.New("configuration changed before commit; workspace was not enabled")
	}
	if err = save(path, data); err != nil {
		if restore := atomicWrite(path, original); restore != nil {
			committed = true // preserve the directory when rollback is unconfirmed
			return errors.New("workspace save failed and configuration rollback is unconfirmed; do not start AWF")
		}
		return errors.New("workspace save failed; original configuration restored")
	}
	stored, err := loadWorkspaceConfig(root)
	if err != nil || !reflect.DeepEqual(stored, next) {
		if restore := atomicWrite(path, original); restore != nil {
			committed = true // preserve the directory when rollback is unconfirmed
			return errors.New("workspace verification failed and rollback is unconfirmed; do not start AWF")
		}
		return errors.New("workspace verification failed; original configuration restored")
	}
	committed = true
	fmt.Fprintln(out, "Default managed workspace enabled. Existing projects, identity and history were preserved. Start AWF to advertise the capability.")
	return nil
}
func isOutsideRelative(rel string) bool {
	return len(rel) > 3 && rel[:3] == ".."+string(filepath.Separator)
}
func sameWorkspacePath(a, b string) bool {
	if runtime.GOOS == "windows" {
		return strings.EqualFold(filepath.Clean(a), filepath.Clean(b))
	}
	return filepath.Clean(a) == filepath.Clean(b)
}

// This command never inspects excluded volumes, including existing configured
// workspaces, before validating the normal internal configuration.
func loadWorkspaceConfig(root string) (Config, error) {
	data, err := readBounded(filepath.Join(root, "config.json"), 2<<20)
	if err != nil {
		return Config{}, err
	}
	return parseWorkspaceConfig(root, data)
}
func parseWorkspaceConfig(root string, data []byte) (Config, error) {
	var cfg Config
	d := json.NewDecoder(bytes.NewReader(data))
	d.DisallowUnknownFields()
	if err := d.Decode(&cfg); err != nil {
		return cfg, err
	}
	if d.Decode(new(any)) != io.EOF {
		return cfg, errors.New("expected exactly one JSON object")
	}
	if runtime.GOOS == "windows" {
		credentialVolume := filepath.VolumeName(cfg.CredentialFile)
		if !strings.EqualFold(credentialVolume, "C:") && !strings.EqualFold(credentialVolume, "D:") {
			return cfg, errors.New("workspace configuration references an excluded volume")
		}
		paths := []string{root, cfg.OpenCodeBinary, cfg.Node.StateDir}
		for _, p := range cfg.Node.Projects {
			paths = append(paths, p)
		}
		if cfg.Node.ManagedRoot != "" {
			paths = append(paths, cfg.Node.ManagedRoot)
		}
		for _, p := range paths {
			volume := filepath.VolumeName(p)
			if !strings.EqualFold(volume, "C:") && !strings.EqualFold(volume, "D:") {
				return cfg, errors.New("workspace configuration references an excluded volume")
			}
			// Walk metadata from the volume outward before any operation that
			// follows links; a C: junction must not redirect inspection to Z:.
			if err := doctorAncestors(p, nativeDoctorPlatform().reparse); err != nil {
				return cfg, errors.New("workspace configuration has an unverifiable path boundary")
			}
		}
	}
	return cfg, validateConfig(root, cfg)
}
