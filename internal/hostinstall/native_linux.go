//go:build linux

package hostinstall

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"net/http"
	"os"
	"os/exec"
	"os/user"
	"path"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
	"github.com/atongrun/agent-workflow/internal/host"
)

var programRoots = []string{"opt/node", "opt/pi-cli", "opt/awf", "opt/magpie"}
var nativeUnits = []string{"awf-host.service", "awf-magpie.service"}
var nativeCommandLinks = map[string]string{
	"usr/local/bin/awf": "/opt/awf/awf", "usr/local/bin/pi": "/opt/pi-cli/awf-launcher.mjs",
	"usr/local/bin/magpie": "/opt/magpie/magpie",
}

type nativeReceipt struct {
	Schema            int            `json:"schema"`
	Mode              string         `json:"mode"`
	Manifest          Manifest       `json:"manifest"`
	Preparation       InstallReceipt `json:"preparation"`
	ProgramsInstalled bool           `json:"programsInstalled"`
	NativeAcceptance  bool           `json:"nativeAcceptance"`
	AllowPrerelease   bool           `json:"allowPrerelease"`
}

// Internal dependency injection only. The public entry point always opens /;
// no environment variable or flag can redirect system writes to another root.
type nativeAdapter struct {
	root            *os.Root
	owner           int
	command         func(context.Context, string, ...string) ([]byte, error)
	lookup          func(string) (*user.User, error)
	lookupGroup     func(string) (*user.Group, error)
	lookPath        func(string) (string, error)
	chown           func(string, int, int) error
	client          *http.Client
	observer        Observer
	allowPrerelease bool
}

func openNative(o Observer) (*nativeAdapter, error) {
	if os.Geteuid() != 0 || os.Getuid() != 0 {
		return nil, errors.New("Linux machine lifecycle requires root")
	}
	e := ObserveEnvironment()
	if e.OS != "linux" || e.Arch != "amd64" || !supportedDistribution(e.Distribution, e.Release) || !e.Glibc || !e.Systemd {
		return nil, errors.New("requires Ubuntu 22.04/24.04 or Debian 12 glibc systemd amd64; no machine changes made")
	}
	if info, err := os.Stat("/sys/fs/cgroup/cgroup.controllers"); err != nil || !info.Mode().IsRegular() {
		return nil, errors.New("unified systemd cgroup v2 required for process shutdown verification")
	}
	r, err := os.OpenRoot("/")
	if err != nil {
		return nil, err
	}
	a := &nativeAdapter{root: r, owner: 0, lookup: user.Lookup, lookupGroup: user.LookupGroup, lookPath: exec.LookPath, observer: o, client: &http.Client{Timeout: 5 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}}
	systemctlPath, err := a.systemctlExecutable()
	if err != nil {
		r.Close()
		return nil, err
	}
	for _, name := range []string{"usr/sbin/useradd", "usr/sbin/nologin"} {
		if err := a.trustedExecutable(name); err != nil {
			r.Close()
			return nil, err
		}
	}
	a.chown = func(name string, uid, gid int) error { return os.Chown("/"+name, uid, gid) }
	a.command = func(ctx context.Context, name string, args ...string) ([]byte, error) {
		if name == "/usr/bin/systemctl" {
			name = systemctlPath
		}
		ctx, cancel := context.WithTimeout(ctx, 90*time.Second)
		defer cancel()
		c := exec.CommandContext(ctx, name, args...)
		c.Env = []string{"PATH=/opt/node/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL=C", "PI_CODING_AGENT_DIR=/var/lib/awf/pi-agent"}
		configureRuntimeCommand(c)
		var out limitedOutput
		c.Stdout = &out
		c.Stderr = io.Discard
		if err := c.Run(); err != nil {
			return nil, fmt.Errorf("native command %s failed", filepath.Base(name))
		}
		return out.Bytes(), nil
	}
	return a, nil
}

func (a *nativeAdapter) trustedExecutable(name string) error {
	if err := a.parents(name); err != nil {
		return err
	}
	if err := a.trusted(name, false); err != nil {
		return err
	}
	info, err := a.root.Lstat(name)
	if err != nil || info.Mode().Perm()&0111 == 0 {
		return errors.New("required native executable unavailable")
	}
	return nil
}

// Debian package lists use /bin/systemctl; usr-merged machines resolve the
// /usr/bin location. Support either fixed trusted executable without PATH search.
func (a *nativeAdapter) systemctlExecutable() (string, error) {
	for _, name := range []string{"usr/bin/systemctl", "bin/systemctl"} {
		if _, err := a.root.Lstat(name); os.IsNotExist(err) {
			continue
		}
		if err := a.trustedExecutable(name); err != nil {
			return "", err
		}
		return "/" + name, nil
	}
	return "", errors.New("trusted systemctl is required")
}

type limitedOutput struct{ bytes.Buffer }

func (b *limitedOutput) Write(p []byte) (int, error) {
	if b.Len()+len(p) > 1<<20 {
		return 0, errors.New("command output limit")
	}
	return b.Buffer.Write(p)
}

func (a *nativeAdapter) event(component, stage, state string) {
	a.observer.Event(ProgressEvent{Component: component, Stage: stage, State: state})
}
func (a *nativeAdapter) phase(component, stage string, fn func() error) error {
	a.event(component, stage, "started")
	if err := fn(); err != nil {
		a.event(component, stage, "failed")
		return err
	}
	a.event(component, stage, "completed")
	return nil
}

func (a *nativeAdapter) trusted(name string, directory bool) error {
	info, err := a.root.Lstat(name)
	if err != nil {
		return err
	}
	st, ok := info.Sys().(*syscall.Stat_t)
	if !ok || int(st.Uid) != a.owner || info.Mode()&(os.ModeSymlink|os.ModeSetuid|os.ModeSetgid) != 0 || info.Mode().Perm()&0022 != 0 || directory != info.IsDir() || (!directory && !info.Mode().IsRegular()) {
		return errors.New("system path ownership, type or permissions require inspection")
	}
	return nil
}
func (a *nativeAdapter) parents(name string) error {
	for p := path.Dir(name); p != "."; p = path.Dir(p) {
		if err := a.trusted(p, true); err != nil {
			return err
		}
	}
	return nil
}
func (a *nativeAdapter) absent(name string) error {
	if err := a.parents(name); err != nil {
		return err
	}
	if _, err := a.root.Lstat(name); !os.IsNotExist(err) {
		return fmt.Errorf("existing or unreadable %s requires inspection; no adoption", name)
	}
	return nil
}
func (a *nativeAdapter) mkdir(name string, mode os.FileMode) error {
	if err := a.absent(name); err != nil {
		return err
	}
	if err := a.root.Mkdir(name, mode); err != nil {
		return err
	}
	f, err := a.root.Open(name)
	if err != nil {
		return err
	}
	defer f.Close()
	return f.Chmod(mode)
}
func (a *nativeAdapter) writeNew(name string, data []byte, mode os.FileMode) error {
	if err := a.absent(name); err != nil {
		return err
	}
	f, err := a.root.OpenFile(name, os.O_WRONLY|os.O_CREATE|os.O_EXCL, mode)
	if err != nil {
		return err
	}
	defer f.Close()
	if _, err = f.Write(data); err != nil {
		return err
	}
	if err = f.Chmod(mode); err != nil {
		return err
	}
	if err := f.Sync(); err != nil {
		return err
	}
	return a.syncParent(name)
}

func (a *nativeAdapter) syncParent(name string) error {
	f, err := a.root.Open(path.Dir(name))
	if err != nil {
		return err
	}
	defer f.Close()
	return f.Sync()
}

// Replace only trusted native metadata, with the same-directory temporary file
// and both file/directory syncs before callers act on the durable result.
func (a *nativeAdapter) replaceMetadata(name string, data []byte, mode os.FileMode, gid int) error {
	if err := a.parents(name); err != nil {
		return err
	}
	if err := a.trusted(name, false); err != nil {
		return err
	}
	var nonce [16]byte
	if _, err := rand.Read(nonce[:]); err != nil {
		return err
	}
	tmp := name + ".tmp-" + hex.EncodeToString(nonce[:])
	defer a.root.Remove(tmp)
	if err := a.writeNew(tmp, data, mode); err != nil {
		return err
	}
	if err := a.chown(tmp, a.owner, gid); err != nil {
		return err
	}
	f, err := a.root.Open(tmp)
	if err != nil {
		return err
	}
	err = f.Sync()
	f.Close()
	if err != nil {
		return err
	}
	if err := a.root.Rename(tmp, name); err != nil {
		return err
	}
	return a.syncParent(name)
}
func (a *nativeAdapter) read(name string, out any) error {
	if err := a.parents(name); err != nil {
		return err
	}
	if err := a.trusted(name, false); err != nil {
		return err
	}
	f, err := a.root.Open(name)
	if err != nil {
		return err
	}
	defer f.Close()
	b, err := io.ReadAll(io.LimitReader(f, 32<<20))
	if err != nil || len(b) >= 32<<20 {
		return errors.New("native metadata bound")
	}
	if uniqueJSON(b) != nil {
		return errors.New("native metadata invalid")
	}
	d := json.NewDecoder(bytes.NewReader(b))
	d.DisallowUnknownFields()
	return d.Decode(out)
}
func (a *nativeAdapter) lock() (*os.File, error) {
	name := "var/cache/awf-installer"
	if _, err := a.root.Lstat(name); os.IsNotExist(err) {
		if err := a.mkdir(name, 0700); err != nil {
			return nil, err
		}
	}
	if err := a.trusted(name, true); err != nil {
		return nil, err
	}
	info, _ := a.root.Lstat(name)
	if info.Mode().Perm() != 0700 {
		return nil, errors.New("installer lock directory must be private")
	}
	r, err := os.OpenRoot(filepath.Join(a.root.Name(), name))
	if err != nil {
		return nil, err
	}
	defer r.Close()
	return fixtureLock(r)
}

func (a *nativeAdapter) fresh() error {
	if err := a.freshUnits(context.Background()); err != nil {
		return err
	}
	if err := a.unoccupiedPorts(); err != nil {
		return err
	}
	for _, name := range []string{"awf", "pi", "magpie"} {
		if _, err := a.lookPath(name); err == nil {
			return fmt.Errorf("existing %s command requires inspection; fresh installation does not adopt programs", name)
		}
	}
	for _, name := range append(append([]string{}, programRoots...), "etc/awf", "var/lib/awf", "var/cache/awf", "etc/systemd/system/awf-host.service", "etc/systemd/system/awf-magpie.service") {
		if err := a.absent(name); err != nil {
			return err
		}
	}
	for name := range nativeCommandLinks {
		if err := a.absent(name); err != nil {
			return err
		}
	}
	if _, err := a.lookup("awf"); err == nil {
		return errors.New("existing awf account requires inspection")
	} else {
		var unknown user.UnknownUserError
		if !errors.As(err, &unknown) {
			return errors.New("awf account lookup unavailable")
		}
	}
	if _, err := a.lookupGroup("awf"); err == nil {
		return errors.New("existing awf group requires inspection")
	} else {
		var unknown user.UnknownGroupError
		if !errors.As(err, &unknown) {
			return errors.New("awf group lookup unavailable")
		}
	}
	return nil
}

// Copy only a freshly revalidated preparation inventory. Fresh installation has
// no running services and no existing program roots; completion is a final marker.
// A failure can leave partial roots for inspection, never silently repaired.
func (a *nativeAdapter) installPrepared(ctx context.Context, m Manifest, generation string, r InstallReceipt) error {
	if m.Validate() != nil || !auditedRuntimeManifest(m) || r.Schema != 2 || r.Mode != "sandbox-runtime-fixture" || r.PiRuntime == nil || r.ManifestSHA256 != manifestDigest(m) || !r.FilesPrepared || r.InstallationComplete {
		return errors.New("verified runtime preparation required")
	}
	b, _ := json.Marshal(r)
	if err := verifyGeneration(generation, r, b); err != nil {
		return err
	}
	if err := a.checkPreparedHost(ctx, m, generation); err != nil {
		return err
	}
	if err := a.fresh(); err != nil {
		return err
	}
	work, err := os.MkdirTemp(filepath.Join(a.root.Name(), "opt"), ".awf-install-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(work)
	dest, err := os.OpenRoot(work)
	if err != nil {
		return err
	}
	defer dest.Close()
	if err := isolateProgramStage(dest); err != nil {
		return err
	}
	if err := a.phase("bundle", "prepare-system-programs", func() error {
		var links []InstalledFile
		for _, c := range r.Components {
			for _, f := range c.Files {
				if ctx.Err() != nil {
					return ctx.Err()
				}
				if f.LinkTarget != "" {
					links = append(links, f)
					continue
				}
				in, err := os.Open(filepath.Join(generation, f.Path))
				if err != nil {
					return err
				}
				copied, err := writeSelected(ctx, dest, f.Path, in, f.Bytes, f.Mode)
				in.Close()
				if err != nil {
					return err
				}
				if copied.SHA256 != f.SHA256 {
					return errors.New("program changed during copy")
				}
			}
		}
		for _, link := range links {
			if err := createPinnedLink(dest, link); err != nil {
				return err
			}
		}
		return filepath.WalkDir(work, func(name string, e fs.DirEntry, err error) error {
			if err != nil {
				return err
			}
			if e.IsDir() {
				return os.Chmod(name, 0755)
			}
			return nil
		})
	}); err != nil {
		return err
	}
	if err := syncTreeDirectories(work); err != nil {
		return err
	}
	if err := a.fresh(); err != nil {
		return err
	}
	for _, name := range programRoots {
		name := name
		if err := a.phase(path.Base(name), "install", func() error {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			if err := a.absent(name); err != nil {
				return err
			}
			return os.Rename(filepath.Join(work, name), filepath.Join(a.root.Name(), name))
		}); err != nil {
			return err
		}
	}
	if err := syncDirectory(filepath.Join(a.root.Name(), "opt")); err != nil {
		return err
	}
	if err := a.phase("awf-host", "service-account", func() error {
		_, err := a.command(ctx, "/usr/sbin/useradd", "--system", "--user-group", "--home-dir", "/var/lib/awf", "--no-create-home", "--shell", "/usr/sbin/nologin", "awf")
		return err
	}); err != nil {
		return err
	}
	u, err := a.lookup("awf")
	if err != nil {
		return err
	}
	uid, err := strconv.Atoi(u.Uid)
	if err != nil {
		return err
	}
	gid, err := strconv.Atoi(u.Gid)
	if err != nil {
		return err
	}
	if uid <= 0 || gid <= 0 {
		return errors.New("dedicated non-root service account required")
	}
	if err := a.mkdir("etc/awf", 0750); err != nil {
		return err
	}
	if err := a.chown("etc/awf", a.owner, gid); err != nil {
		return err
	}
	for _, name := range []string{"var/lib/awf", "var/cache/awf"} {
		if err := a.mkdir(name, 0700); err != nil {
			return err
		}
		if err := a.chown(name, uid, gid); err != nil {
			return err
		}
	}
	for name, target := range nativeCommandLinks {
		if err := a.absent(name); err != nil {
			return err
		}
		if err := a.root.Symlink(target, name); err != nil {
			return err
		}
	}
	for name, data := range map[string]string{"awf-host.service": hostUnitProposal, "awf-magpie.service": magpieUnitProposal} {
		if err := a.writeNew("etc/systemd/system/"+name, []byte(data), 0644); err != nil {
			return err
		}
	}
	if err := a.phase("awf-host", "unit-reload", func() error { _, err := a.command(ctx, "/usr/bin/systemctl", "daemon-reload"); return err }); err != nil {
		return err
	}
	nr := nativeReceipt{Schema: 1, Mode: "linux-host-native-v1", Manifest: m, Preparation: r, ProgramsInstalled: true, AllowPrerelease: a.allowPrerelease}
	data, _ := json.Marshal(nr)
	return a.phase("bundle", "install-receipt", func() error { return a.writeNew("etc/awf/install.json", data, 0600) })
}

func (a *nativeAdapter) checkPreparedHost(ctx context.Context, m Manifest, generation string) error {
	return a.phase("awf-host", "build-identity", func() error {
		out, err := a.command(ctx, filepath.Join(generation, "opt/awf/awf"), "linux-build-identity")
		if err != nil {
			return err
		}
		var identity buildIdentity
		if uniqueJSON(out) != nil || json.Unmarshal(out, &identity) != nil || identity != (buildIdentity{1, m.Version, m.SourceCommit, "linux", "amd64", "v1"}) {
			return errors.New("native executable build identity differs from manifest")
		}
		return nil
	})
}

func manifestDigest(m Manifest) string { b, _ := json.Marshal(m); return hashData(b) }
func hashData(b []byte) string         { s := sha256.Sum256(b); return hex.EncodeToString(s[:]) }

func (a *nativeAdapter) installed(ctx context.Context) (nativeReceipt, error) {
	var r nativeReceipt
	if err := a.read("etc/awf/install.json", &r); err != nil {
		return r, err
	}
	if r.Schema != 1 || r.Mode != "linux-host-native-v1" || !r.ProgramsInstalled || r.Manifest.Validate() != nil || r.Preparation.Schema != 2 || r.Preparation.Mode != "sandbox-runtime-fixture" || !r.Preparation.FilesPrepared || r.Preparation.InstallationComplete || r.Preparation.PiRuntime == nil || r.Preparation.ManifestSHA256 != manifestDigest(r.Manifest) {
		return r, errors.New("native receipt invalid")
	}
	for name, target := range nativeCommandLinks {
		if err := a.parents(name); err != nil {
			return r, err
		}
		info, err := a.root.Lstat(name)
		if err != nil {
			return r, err
		}
		st, ok := info.Sys().(*syscall.Stat_t)
		value, err := a.root.Readlink(name)
		if err != nil || !ok || int(st.Uid) != a.owner || value != target {
			return r, errors.New("installed command link changed")
		}
	}
	// Pi's initial file hashes are provenance. Its official updater owns the
	// mutable global prefix; retaining those hashes as an active pin disables updates.
	for _, c := range r.Preparation.Components {
		if c.ID == "pi" {
			continue
		}
		for _, f := range c.Files {
			if err := a.parents(f.Path); err != nil {
				return r, err
			}
			if f.LinkTarget != "" {
				v, err := a.root.Readlink(f.Path)
				if err != nil || v != f.LinkTarget {
					return r, errors.New("program command link changed")
				}
				continue
			}
			if err := a.trusted(f.Path, false); err != nil {
				return r, err
			}
			info, err := a.root.Lstat(f.Path)
			if err != nil || uint32(info.Mode().Perm()) != f.Mode {
				return r, errors.New("fixed program mode differs from install provenance")
			}
			file, err := a.root.Open(f.Path)
			if err != nil {
				return r, err
			}
			h := sha256.New()
			n, err := io.Copy(h, io.LimitReader(file, f.Bytes+1))
			file.Close()
			if err != nil || n != f.Bytes || hex.EncodeToString(h.Sum(nil)) != f.SHA256 {
				return r, errors.New("fixed program differs from install provenance")
			}
		}
	}
	var pkg struct {
		Name    string `json:"name"`
		Version string `json:"version"`
	}
	// npm package.json has upstream fields beyond these identity fields.
	if err := a.trusted("opt/pi-cli/lib/node_modules/@earendil-works/pi-coding-agent/package.json", false); err != nil {
		return r, err
	}
	f, err := a.root.Open("opt/pi-cli/lib/node_modules/@earendil-works/pi-coding-agent/package.json")
	if err != nil {
		return r, err
	}
	b, err := io.ReadAll(io.LimitReader(f, 1<<20))
	f.Close()
	if err != nil || json.Unmarshal(b, &pkg) != nil || pkg.Name != "@earendil-works/pi-coding-agent" || !versionPattern.MatchString(pkg.Version) {
		return r, errors.New("current official Pi package identity invalid")
	}
	if err := a.parents("opt/pi-cli/lib/node_modules/@earendil-works/pi-coding-agent/package.json"); err != nil {
		return r, err
	}
	if err := a.trusted("opt/pi-cli/awf-launcher.mjs", false); err != nil {
		return r, err
	}
	launcher, err := a.root.Open("opt/pi-cli/awf-launcher.mjs")
	if err != nil {
		return r, err
	}
	b, err = io.ReadAll(io.LimitReader(launcher, int64(len(sharedPiLauncher))+1))
	launcher.Close()
	if err != nil || string(b) != sharedPiLauncher {
		return r, errors.New("stable Pi launcher changed; upstream npm owns only its package tree")
	}
	info, err := a.root.Lstat("opt/pi-cli/awf-launcher.mjs")
	if err != nil || info.Mode().Perm() != 0755 {
		return r, errors.New("stable Pi launcher must be executable")
	}
	// Validate current prefix ownership, not stale initial Pi content hashes.
	if err := fs.WalkDir(a.root.FS(), "opt/pi-cli", func(name string, e fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		info, err := a.root.Lstat(name)
		if err != nil {
			return err
		}
		if info.Mode()&os.ModeSymlink != 0 {
			target, err := a.root.Readlink(name)
			if err != nil || path.IsAbs(target) {
				return errors.New("Pi prefix has an external link")
			}
			resolved := path.Clean(path.Join(path.Dir(name), target))
			if !strings.HasPrefix(resolved, "opt/pi-cli/") {
				return errors.New("Pi prefix link escapes")
			}
			return nil
		}
		return a.trusted(name, e.IsDir())
	}); err != nil {
		return r, err
	}
	out, err := a.command(ctx, "/opt/pi-cli/awf-launcher.mjs", "--version")
	if err != nil || strings.TrimSpace(string(out)) != pkg.Version {
		return r, errors.New("current Pi package and executable version disagree")
	}
	return r, nil
}

func (a *nativeAdapter) initialize(ctx context.Context) error {
	r, err := a.installed(ctx)
	if err != nil {
		return err
	}
	for _, name := range []string{"etc/awf/host.json", "etc/awf/host.env", "etc/awf/magpie-settings.json", "etc/awf/native-initialized.json", "etc/awf/native-magpie-loopback.json"} {
		if err := a.absent(name); err != nil {
			return err
		}
	}
	u, err := a.lookup("awf")
	if err != nil {
		return err
	}
	uid, _ := strconv.Atoi(u.Uid)
	gid, _ := strconv.Atoi(u.Gid)
	if uid <= 0 || gid <= 0 {
		return errors.New("service identity invalid")
	}
	for _, name := range []string{"var/lib/awf", "var/cache/awf"} {
		info, err := a.root.Lstat(name)
		if err != nil || !info.IsDir() || info.Mode().Perm() != 0700 {
			return errors.New("private service state directory required")
		}
		st, ok := info.Sys().(*syscall.Stat_t)
		if !ok || int(st.Uid) != uid || int(st.Gid) != gid {
			return errors.New("service state ownership requires inspection")
		}
	}
	plan, err := BuildInitializationPlan(r.Manifest)
	if err != nil {
		return err
	}
	state, err := os.OpenRoot(filepath.Join(a.root.Name(), "var/lib/awf"))
	if err != nil {
		return err
	}
	defer state.Close()
	return a.phase("awf-host", "initialize", func() error {
		// Create only this service's new private state; no user config is imported.
		for _, name := range []string{"pi-agent", "magpie-config", "magpie-config/magpie"} {
			// Parents may be service-owned; root controls the fresh leaves here.
			if _, err := state.Lstat(name); !os.IsNotExist(err) {
				return errors.New("service initialization state already exists; inspect partial initialization")
			}
			if err := state.Mkdir(name, 0700); err != nil {
				return err
			}
			dir, err := state.Open(name)
			if err != nil {
				return err
			}
			err = dir.Chown(uid, gid)
			dir.Close()
			if err != nil {
				return err
			}
		}
		settings := []byte(`{"lan":false,"noAutoUpdate":true,"noStats":true}`)
		f, err := state.OpenFile("magpie-config/magpie/settings.json", os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
		if err != nil {
			return err
		}
		_, err = f.Write(settings)
		if err == nil {
			err = f.Chown(uid, gid)
		}
		if err == nil {
			err = f.Sync()
		}
		f.Close()
		if err != nil {
			return err
		}
		if err := a.writeNew("etc/awf/magpie-settings.json", settings, 0640); err != nil {
			return err
		}
		if err := a.chown("etc/awf/magpie-settings.json", a.owner, gid); err != nil {
			return err
		}
		var token [64]byte
		if _, err := rand.Read(token[:]); err != nil {
			return err
		}
		env := []byte("AWF_HOST_TOKEN=" + hex.EncodeToString(token[:32]) + "\nAWF_EXTENSION_TOKEN=" + hex.EncodeToString(token[32:]) + "\n")
		if err := a.writeNew("etc/awf/host.env", env, 0600); err != nil {
			return err
		}
		data, _ := json.MarshalIndent(plan.HostConfig, "", "  ")
		if err := a.writeNew("etc/awf/host.json", data, 0640); err != nil {
			return err
		}
		if err := a.chown("etc/awf/host.json", a.owner, gid); err != nil {
			return err
		}
		if err := a.writeNew("etc/awf/native-magpie-loopback.json", []byte(`{"schema":1,"configuredLoopback":true,"nativeAcceptance":false}`), 0600); err != nil {
			return err
		}
		return a.writeNew("etc/awf/native-initialized.json", []byte(`{"schema":1,"initialized":true,"nativeAcceptance":false}`), 0600)
	})
}

func (a *nativeAdapter) token() (string, error) {
	if err := a.trusted("etc/awf/host.env", false); err != nil {
		return "", err
	}
	info, err := a.root.Lstat("etc/awf/host.env")
	if err != nil || info.Mode().Perm() != 0600 {
		return "", errors.New("Host token file must remain private")
	}
	f, err := a.root.Open("etc/awf/host.env")
	if err != nil {
		return "", err
	}
	defer f.Close()
	b, err := io.ReadAll(io.LimitReader(f, 4096))
	if err != nil {
		return "", err
	}
	for _, line := range strings.Split(string(b), "\n") {
		if strings.HasPrefix(line, "AWF_HOST_TOKEN=") {
			v := strings.TrimPrefix(line, "AWF_HOST_TOKEN=")
			if digestPattern.MatchString(v) {
				return v, nil
			}
		}
	}
	return "", errors.New("Host token unavailable")
}

type maintenanceStatus struct {
	Maintenance core.Maintenance `json:"maintenance"`
	Build       struct {
		Available             bool
		Version, SourceCommit string
	} `json:"build"`
}

func (a *nativeAdapter) maintenance(ctx context.Context, action string, body any) (maintenanceStatus, error) {
	var result maintenanceStatus
	token, err := a.token()
	if err != nil {
		return result, err
	}
	method, url := http.MethodGet, "http://127.0.0.1:7070/v1/maintenance"
	var input io.Reader
	if action != "" {
		method = http.MethodPost
		url += "/" + action
		b, _ := json.Marshal(body)
		input = bytes.NewReader(b)
	}
	req, _ := http.NewRequestWithContext(ctx, method, url, input)
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	response, err := a.client.Do(req)
	if err != nil {
		return result, errors.New("loopback Host maintenance unavailable")
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		return result, errors.New("maintenance refused; settle work or inspect existing lease")
	}
	if err := json.NewDecoder(io.LimitReader(response.Body, 1<<20)).Decode(&result); err != nil {
		return result, errors.New("invalid maintenance response")
	}
	return result, nil
}

func (a *nativeAdapter) stop(ctx context.Context) error {
	return a.stopFor(ctx, "")
}
func (a *nativeAdapter) stopFor(ctx context.Context, target string) error {
	r, err := a.installed(ctx)
	if err != nil {
		return err
	}
	if target == "" {
		target = manifestDigest(r.Manifest)
	}
	// Refuse changed definitions before interacting with a running maintenance
	// endpoint. Only these exact trusted units may ever be stopped.
	for _, unit := range nativeUnits {
		if err := a.unit(ctx, unit); err != nil {
			return err
		}
	}
	var lease core.Maintenance
	hasLease := false
	if _, err := a.root.Lstat("etc/awf/stopped-lease.json"); err == nil {
		if err := a.read("etc/awf/stopped-lease.json", &lease); err != nil {
			return err
		}
		if core.ValidateMaintenance(&lease) != nil || lease.Phase == "open" || lease.TargetManifestSHA256 != target {
			return errors.New("existing maintenance lease requires its explicit owner/target")
		}
		hasLease = true
	} else if !os.IsNotExist(err) {
		return err
	}
	if err := a.hostListenerOwned(ctx); err != nil {
		if !hasLease || lease.Phase != "sealed" {
			return err
		}
		if err := a.stopped(ctx, "awf-host.service"); err != nil {
			return err
		}
		return a.phase("bundle", "service-stop-retry", func() error { return a.stopUnits(ctx) })
	}
	s, err := a.maintenance(ctx, "", nil)
	if err != nil {
		// An interrupted shutdown may already have stopped Host. Offline retry
		// requires the previously synced sealed lease AND a verified empty Host
		// cgroup; never infer a seal from an unavailable endpoint alone.
		if !hasLease || lease.Phase != "sealed" {
			return err
		}
		if err := a.stopped(ctx, "awf-host.service"); err != nil {
			return err
		}
		return a.phase("bundle", "service-stop-retry", func() error { return a.stopUnits(ctx) })
	}
	if !s.Build.Available || s.Build.Version != r.Manifest.Version || s.Build.SourceCommit != r.Manifest.SourceCommit {
		return errors.New("running Host build does not match installed identity")
	}
	if hasLease {
		if lease.OwnerRequestID != s.Maintenance.OwnerRequestID || lease.TargetManifestSHA256 != s.Maintenance.TargetManifestSHA256 {
			return errors.New("existing maintenance lease requires its explicit owner/target")
		}
	} else {
		if s.Maintenance.Phase != "open" {
			return errors.New("existing maintenance lease requires its explicit owner")
		}
		var random [16]byte
		if _, err := rand.Read(random[:]); err != nil {
			return err
		}
		owner := "linux-stop-" + hex.EncodeToString(random[:])
		s, err = a.maintenance(ctx, "begin", map[string]any{"requestId": owner, "expectedRevision": s.Maintenance.Revision, "targetManifestSHA256": target})
		if err != nil {
			return err
		}
		lease = s.Maintenance
		if core.ValidateMaintenance(&lease) != nil || lease.OwnerRequestID != owner || lease.TargetManifestSHA256 != target || lease.Phase != "draining" {
			return errors.New("invalid owned maintenance response")
		}
		data, _ := json.Marshal(lease)
		if err := a.writeNew("etc/awf/stopped-lease.json", data, 0600); err != nil {
			return err
		}
	}
	owner := lease.OwnerRequestID
	if s.Maintenance.Phase == "draining" {
		s, err = a.maintenance(ctx, "seal", map[string]any{"requestId": owner + "-seal", "ownerRequestId": owner, "expectedRevision": s.Maintenance.Revision})
		if err != nil {
			return err
		}
	}
	if core.ValidateMaintenance(&s.Maintenance) != nil || s.Maintenance.Phase != "sealed" || s.Maintenance.OwnerRequestID != owner || s.Maintenance.TargetManifestSHA256 != target {
		return errors.New("Host did not establish the owned seal")
	}
	data, _ := json.Marshal(s.Maintenance)
	if err := a.replaceMetadata("etc/awf/stopped-lease.json", data, 0600, a.owner); err != nil {
		return err
	}
	return a.phase("bundle", "service-stop", func() error { return a.stopUnits(ctx) })
}
func (a *nativeAdapter) stopped(ctx context.Context, unit string) error {
	out, err := a.command(ctx, "/usr/bin/systemctl", "show", unit, "--property=ActiveState,MainPID,KillMode", "--no-pager")
	if err != nil {
		return err
	}
	text := string(out)
	if !strings.Contains(text, "ActiveState=inactive\n") || !strings.Contains(text, "MainPID=0\n") || !strings.Contains(text, "KillMode=control-group\n") {
		return errors.New("systemd shutdown is not established")
	}
	group := "sys/fs/cgroup/system.slice/" + unit
	err = fs.WalkDir(a.root.FS(), group, func(name string, e fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if e.Name() != "cgroup.procs" {
			return nil
		}
		f, err := a.root.Open(name)
		if err != nil {
			return err
		}
		b, err := io.ReadAll(io.LimitReader(f, 4096))
		f.Close()
		if err != nil || len(strings.TrimSpace(string(b))) > 0 {
			return errors.New("systemd control group still contains processes")
		}
		return nil
	})
	if os.IsNotExist(err) {
		return nil
	}
	return err
}

func (a *nativeAdapter) start(ctx context.Context, enable bool) error {
	r, err := a.installed(ctx)
	if err != nil {
		return err
	}
	var initialized struct {
		Schema                        int
		Initialized, NativeAcceptance bool
	}
	if err := a.read("etc/awf/native-initialized.json", &initialized); err != nil || initialized.Schema != 1 || !initialized.Initialized {
		return errors.New("run awf init before start")
	}
	if err := a.hostConfiguration(); err != nil {
		return err
	}
	for _, unit := range nativeUnits {
		if err := a.unit(ctx, unit); err != nil {
			return err
		}
	}
	// Refresh the administrator snapshot only while both units are stopped.
	// An already running pair may be verified without replacing its mount.
	active := 0
	for _, unit := range nativeUnits {
		if _, err := a.activePID(ctx, unit); err == nil {
			active++
		}
	}
	if active == 1 {
		return errors.New("partially running service pair requires awf stop before start")
	}
	if active == 0 {
		for _, unit := range nativeUnits {
			if err := a.stopped(ctx, unit); err != nil {
				return err
			}
		}
		if err := a.unoccupiedPorts(); err != nil {
			return err
		}
		if err := a.snapshotMagpie(); err != nil {
			return err
		}
	}
	if err := a.serviceCheck("magpie", false); err != nil {
		return err
	}
	var lease core.Maintenance
	hasLease := false
	if _, err := a.root.Lstat("etc/awf/stopped-lease.json"); err == nil {
		if err := a.read("etc/awf/stopped-lease.json", &lease); err != nil {
			return err
		}
		if core.ValidateMaintenance(&lease) != nil || lease.Phase != "sealed" || lease.TargetManifestSHA256 != manifestDigest(r.Manifest) {
			return errors.New("stopped maintenance target differs from installed receipt")
		}
		hasLease = true
	} else if !os.IsNotExist(err) {
		return err
	}
	if err := a.phase("bundle", "service-start", func() error {
		if active == 2 {
			return nil
		}
		for _, unit := range []string{"awf-magpie.service", "awf-host.service"} {
			if _, err := a.command(ctx, "/usr/bin/systemctl", "start", unit); err != nil {
				return err
			}
		}
		return nil
	}); err != nil {
		return a.failedStart(ctx, err)
	}
	if err := a.phase("awf-host", "health", func() error {
		var s maintenanceStatus
		var err error
		for i := 0; i < 20; i++ {
			s, err = a.maintenance(ctx, "", nil)
			if err == nil && (!s.Build.Available || s.Build.Version != r.Manifest.Version || s.Build.SourceCommit != r.Manifest.SourceCommit) {
				err = errors.New("started Host build identity differs")
			}
			if err == nil {
				err = a.magpieHealth(ctx, r.Manifest)
			}
			if err == nil {
				err = a.loopbackListeners(ctx)
			}
			if err == nil {
				break
			}
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-time.After(250 * time.Millisecond):
			}
		}
		if err != nil {
			return err
		}
		// HTTP readiness may have waited while processes changed. Associate
		// current listeners/processes again immediately before releasing a seal.
		if err := a.loopbackListeners(ctx); err != nil {
			return err
		}
		if hasLease {
			if s.Maintenance.OwnerRequestID != lease.OwnerRequestID || s.Maintenance.Phase != "sealed" {
				return errors.New("stopped maintenance owner/seal changed")
			}
			_, err = a.maintenance(ctx, "end", map[string]any{"requestId": lease.OwnerRequestID + "-end", "ownerRequestId": lease.OwnerRequestID, "expectedRevision": s.Maintenance.Revision})
			if err != nil {
				return err
			}
			if err := a.root.Remove("etc/awf/stopped-lease.json"); err != nil {
				return err
			}
			return a.syncParent("etc/awf/stopped-lease.json")
		}
		if s.Maintenance.Phase != "open" {
			return errors.New("existing maintenance lease requires explicit owner release")
		}
		return nil
	}); err != nil {
		return a.failedStart(ctx, err)
	}
	if enable {
		return a.phase("bundle", "enable-autostart", func() error {
			_, err := a.command(ctx, "/usr/bin/systemctl", append([]string{"enable"}, nativeUnits...)...)
			return err
		})
	}
	return nil
}

// Keep the release's existing build identity fields; packaging sets these only
// for Linux releases and does not change the Windows lifecycle version contract.
func NativeBuildIdentity() buildIdentity {
	return buildIdentity{1, host.BuildVersion, host.BuildSourceCommit, "linux", "amd64", "v1"}
}
