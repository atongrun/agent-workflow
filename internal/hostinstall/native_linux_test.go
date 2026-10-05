//go:build linux

package hostinstall

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
)

type nativeFixture struct {
	a           *nativeAdapter
	dir         string
	m           Manifest
	account     bool
	piVersion   string
	commands    []string
	maintenance core.Maintenance
	busy        bool
}

func newNativeFixture(t *testing.T) *nativeFixture {
	t.Helper()
	if os.Getuid() == 0 || os.Getgid() == 0 {
		t.Skip("non-root fixture user required; no real service account is created")
	}
	f := &nativeFixture{dir: privateParent(t), piVersion: "1.0.2", maintenance: core.Maintenance{Phase: "open"}}
	for _, name := range []string{"opt", "etc/systemd/system", "var/lib", "var/cache", "usr/local/bin", "sys/fs/cgroup/system.slice", "proc/net"} {
		if err := os.MkdirAll(filepath.Join(f.dir, name), 0755); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(filepath.Join(f.dir, "proc/net/tcp"), []byte("0: 0100007F:1B9E 00000000:0000 0A\n1: 0100007F:0D61 00000000:0000 0A\n"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(f.dir, "proc/net/tcp6"), nil, 0644); err != nil {
		t.Fatal(err)
	}
	r, err := os.OpenRoot(f.dir)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { r.Close() })
	f.m, _ = manifestFixture()
	for i, c := range f.m.Components {
		switch c.ID {
		case "node":
			c.Version = "v22.19.0"
			c.Artifacts = []Artifact{{Name: "node-v22.19.0-linux-x64.tar.gz", URL: "https://nodejs.org/dist/v22.19.0/node-v22.19.0-linux-x64.tar.gz", SHA256: "d36e56998220085782c0ca965f9d51b7726335aed2f5fc7321c6c0ad233aa96d", Bytes: 54907188, Format: "tar.gz"}}
		case "pi":
			for j := range c.Artifacts {
				a := &c.Artifacts[j]
				if a.Name == "package.json" {
					a.Bytes = 317
					a.SHA256 = "491cb1ec4fba98d9547b037cd9dea48ae0bba651a0a80d67dd1660705b60f1c5"
				} else {
					a.Bytes = 63566
					a.SHA256 = "b8e9e6a191bcf1e6e3ff8dafe5c0c9042b48e0087cd6d6816dcaa051222ba680"
				}
			}
		}
		f.m.Components[i] = c
	}
	f.a = &nativeAdapter{root: r, owner: os.Getuid(), observer: &recorder{}}
	f.a.lookPath = func(string) (string, error) { return "", exec.ErrNotFound }
	f.a.lookupGroup = func(string) (*user.Group, error) {
		if !f.account {
			return nil, user.UnknownGroupError("awf")
		}
		return &user.Group{Name: "awf", Gid: strconv.Itoa(os.Getgid())}, nil
	}
	f.a.lookup = func(string) (*user.User, error) {
		if !f.account {
			return nil, user.UnknownUserError("awf")
		}
		return &user.User{Username: "awf", Uid: strconv.Itoa(os.Getuid()), Gid: strconv.Itoa(os.Getgid())}, nil
	}
	// Ownership is recorded as command intent only: this fixture cannot establish
	// root/service separation or native OS account behavior.
	f.a.chown = func(string, int, int) error { return nil }
	f.a.command = func(_ context.Context, name string, args ...string) ([]byte, error) {
		f.commands = append(f.commands, name+" "+strings.Join(args, " "))
		if name == "/usr/sbin/useradd" {
			f.account = true
			return nil, nil
		}
		if name == "/opt/pi-cli/awf-launcher.mjs" {
			return []byte(f.piVersion + "\n"), nil
		}
		if filepath.Base(name) == "awf" && len(args) == 1 && args[0] == "linux-build-identity" {
			return json.Marshal(buildIdentity{1, f.m.Version, f.m.SourceCommit, "linux", "amd64", "v1"})
		}
		if len(args) > 0 && args[0] == "show" {
			if len(args) > 2 && strings.Contains(args[2], "ControlGroup") {
				return []byte("ActiveState=active\nMainPID=42\nControlGroup=/system.slice/" + args[1] + "\n"), nil
			}
			if len(args) > 2 && strings.Contains(args[2], "FragmentPath") {
				return []byte("FragmentPath=/etc/systemd/system/" + args[1] + "\nDropInPaths=\nUser=awf\nGroup=awf\nKillMode=control-group\nSlice=system.slice\n"), nil
			}
			return []byte("ActiveState=inactive\nMainPID=0\nKillMode=control-group\n"), nil
		}
		return nil, nil
	}
	f.a.client = &http.Client{Transport: fixtureTransport(func(req *http.Request) (*http.Response, error) {
		status := 200
		if req.Method == http.MethodPost {
			var in struct {
				RequestID, OwnerRequestID, TargetManifestSHA256 string
				ExpectedRevision                                int
			}
			if err := json.NewDecoder(req.Body).Decode(&in); err != nil {
				return nil, err
			}
			if in.ExpectedRevision != f.maintenance.Revision {
				return nil, errors.New("fixture revision mismatch")
			}
			switch filepath.Base(req.URL.Path) {
			case "begin":
				now := time.Now()
				f.maintenance = core.Maintenance{Phase: "draining", Revision: in.ExpectedRevision + 1, OwnerRequestID: in.RequestID, TargetManifestSHA256: in.TargetManifestSHA256, BeganAt: &now}
			case "seal":
				if f.busy {
					status = 409
				} else {
					f.maintenance.Phase = "sealed"
					f.maintenance.Revision++
				}
			case "end":
				if in.OwnerRequestID != f.maintenance.OwnerRequestID {
					return nil, errors.New("fixture owner mismatch")
				}
				f.maintenance = core.Maintenance{Phase: "open", Revision: in.ExpectedRevision + 1}
			}
		}
		b, _ := json.Marshal(map[string]any{"maintenance": f.maintenance, "build": map[string]any{"available": true, "version": f.m.Version, "sourceCommit": f.m.SourceCommit}})
		return &http.Response{StatusCode: status, Body: io.NopCloser(bytes.NewReader(b)), Header: make(http.Header)}, nil
	})}
	return f
}

func nativePreparedFixture(t *testing.T, m Manifest) (string, InstallReceipt) {
	t.Helper()
	dir := privateParent(t)
	root, err := os.OpenRoot(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer root.Close()
	r := InstallReceipt{Schema: 2, Mode: "sandbox-runtime-fixture", ManifestSHA256: manifestDigest(m), SourceCommit: m.SourceCommit, OS: "linux", Arch: "amd64", FilesPrepared: true, PiRuntime: &PiRuntimeReceipt{OwnerUID: os.Getuid()}}
	// Synthetic bytes and substituted process commands exercise adapter behavior,
	// never establish installed runtimes or root/systemd acceptance.
	files := map[string]map[string]string{
		"node":          {"opt/node/bin/node": "synthetic-node"},
		"pi":            {"opt/pi-cli/awf-launcher.mjs": sharedPiLauncher, "opt/pi-cli/lib/node_modules/@earendil-works/pi-coding-agent/package.json": `{"name":"@earendil-works/pi-coding-agent","version":"1.0.2"}`, "opt/pi-cli/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js": "synthetic-pi"},
		"awf-host":      {"opt/awf/awf": "synthetic-host-" + m.SourceCommit},
		"awf-extension": {"opt/awf/extensions/awf.ts": "synthetic-extension-" + m.SourceCommit},
		"magpie":        {"opt/magpie/magpie": "synthetic-magpie"},
	}
	for _, id := range componentOrder {
		c := AppliedComponent{ID: id, State: "files_prepared"}
		for name, data := range files[id] {
			mode := uint32(0644)
			if name == "opt/pi-cli/awf-launcher.mjs" {
				mode = 0755
			}
			file, err := writeSelected(context.Background(), root, name, strings.NewReader(data), int64(len(data)), mode)
			if err != nil {
				t.Fatal(err)
			}
			c.Files = append(c.Files, file)
		}
		if id == "pi" {
			bin := InstalledFile{Path: "opt/pi-cli/bin/pi", Mode: 0777, LinkTarget: "../lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js"}
			if err := createPinnedLink(root, bin); err != nil {
				t.Fatal(err)
			}
			c.Files = append(c.Files, bin)
		}
		r.Components = append(r.Components, c)
	}
	b, _ := json.Marshal(r)
	if err := writeSynced(root, "install.json", b); err != nil {
		t.Fatal(err)
	}
	return dir, r
}
func (f *nativeFixture) install(t *testing.T) {
	t.Helper()
	dir, r := nativePreparedFixture(t, f.m)
	if err := f.a.installPrepared(context.Background(), f.m, dir, r); err != nil {
		t.Fatal(err)
	}
}

func TestNativeAdapterFreshInstallInitAndOwnedStopStart(t *testing.T) {
	f := newNativeFixture(t)
	f.install(t)
	for _, command := range f.commands {
		if strings.Contains(command, "systemctl start") || strings.Contains(command, "systemctl enable") {
			t.Fatal("install activated service", command)
		}
	}
	if err := f.a.initialize(context.Background()); err != nil {
		t.Fatal(err)
	}
	if err := f.a.initialize(context.Background()); err == nil {
		t.Fatal("existing initialization overwritten")
	}
	if err := f.a.start(context.Background(), false); err != nil {
		t.Fatal(err)
	}
	if err := f.a.stop(context.Background()); err != nil {
		t.Fatal(err)
	}
	if f.maintenance.Phase != "sealed" {
		t.Fatal("stop lost durable seal")
	}
	if err := f.a.start(context.Background(), false); err != nil {
		t.Fatal(err)
	}
	if f.maintenance.Phase != "open" {
		t.Fatal("start did not explicitly release original owner")
	}
	if _, err := os.Stat(filepath.Join(f.dir, "etc/awf/stopped-lease.json")); !os.IsNotExist(err) {
		t.Fatal("released lease not removed")
	}
	config, err := os.ReadFile(filepath.Join(f.dir, "etc/awf/host.json"))
	if err != nil || !strings.Contains(string(config), "/var/lib/awf/pi-agent") || strings.Contains(string(config), ".pi/agent") {
		t.Fatal("service state mixed", err)
	}
	if err := f.a.fresh(); err == nil {
		t.Fatal("existing installation adopted")
	}
}

func TestNativeBusyStopCannotStopUnitsOrClaimCompletion(t *testing.T) {
	f := newNativeFixture(t)
	f.install(t)
	if err := f.a.initialize(context.Background()); err != nil {
		t.Fatal(err)
	}
	f.busy = true
	f.commands = nil
	if err := f.a.stop(context.Background()); err == nil {
		t.Fatal("busy seal admitted")
	}
	for _, command := range f.commands {
		if strings.Contains(command, "systemctl stop") {
			t.Fatal("units stopped before seal")
		}
	}
	if f.maintenance.Phase != "draining" {
		t.Fatal("failed seal released lease")
	}
	owner := f.maintenance.OwnerRequestID
	f.busy = false
	if err := f.a.stop(context.Background()); err != nil {
		t.Fatal("owned drain could not retry", err)
	}
	if f.maintenance.OwnerRequestID != owner || f.maintenance.Phase != "sealed" {
		t.Fatal("retry changed original owner")
	}
}

func TestNativePiUpdateDriftPreservedAcrossAWFReplacement(t *testing.T) {
	f := newNativeFixture(t)
	f.install(t)
	pkg := filepath.Join(f.dir, "opt/pi-cli/lib/node_modules/@earendil-works/pi-coding-agent/package.json")
	if err := os.WriteFile(pkg, []byte(`{"name":"@earendil-works/pi-coding-agent","version":"1.0.3"}`), 0644); err != nil {
		t.Fatal(err)
	}
	f.piVersion = "1.0.3"
	old, err := f.a.installed(context.Background())
	if err != nil {
		t.Fatal("upstream Pi update rejected by immutable receipt", err)
	}
	f.m.SourceCommit = strings.Repeat("b", 40)
	newDir, newReceipt := nativePreparedFixture(t, f.m)
	if err := f.a.replacePrepared(context.Background(), f.m, newDir, newReceipt, old); err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(pkg)
	if !strings.Contains(string(b), "1.0.3") {
		t.Fatal("AWF update replaced Pi")
	}
	if _, err := f.a.installed(context.Background()); err != nil {
		t.Fatal("current receipt invalid after replacement", err)
	}
}

func TestNativeRefusesLinkedParentsAndIncompleteServiceExit(t *testing.T) {
	f := newNativeFixture(t)
	if err := os.RemoveAll(filepath.Join(f.dir, "usr/local/bin")); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(f.dir, filepath.Join(f.dir, "usr/local/bin")); err != nil {
		t.Fatal(err)
	}
	if err := f.a.fresh(); err == nil {
		t.Fatal("linked system parent admitted")
	}
	f = newNativeFixture(t)
	group := filepath.Join(f.dir, "sys/fs/cgroup/system.slice/awf-host.service/subgroup")
	if err := os.MkdirAll(group, 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(group, "cgroup.procs"), []byte("42\n"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := f.a.stopped(context.Background(), "awf-host.service"); err == nil {
		t.Fatal("live descendant process accepted")
	}
	f.a.command = func(context.Context, string, ...string) ([]byte, error) {
		return []byte("ActiveState=failed\nMainPID=0\nKillMode=control-group\n"), nil
	}
	if err := f.a.stopped(context.Background(), "awf-host.service"); err == nil {
		t.Fatal("unknown service shutdown accepted")
	}
}

func TestNativeInstallFailureLeavesNoCompletionReceipt(t *testing.T) {
	f := newNativeFixture(t)
	old := f.a.command
	f.a.command = func(ctx context.Context, name string, args ...string) ([]byte, error) {
		if name == "/usr/sbin/useradd" {
			return nil, fmt.Errorf("fixture account failure")
		}
		return old(ctx, name, args...)
	}
	dir, r := nativePreparedFixture(t, f.m)
	if err := f.a.installPrepared(context.Background(), f.m, dir, r); err == nil {
		t.Fatal("account failure accepted")
	}
	if _, err := os.Stat(filepath.Join(f.dir, "etc/awf/install.json")); !os.IsNotExist(err) {
		t.Fatal("partial install completion claimed")
	}
	if err := f.a.fresh(); err == nil {
		t.Fatal("partial program tree silently adopted")
	}
}

func TestNativeCLIHasNoSystemRootOverride(t *testing.T) {
	var out bytes.Buffer
	handled, err := HandleNative(context.Background(), []string{"install", "--root", "/tmp/example"}, strings.NewReader(""), &out, &out)
	if !handled || err == nil {
		t.Fatal("root override exposed")
	}
}

func TestNativeStartupRefusalsAndCleanupRetainSeal(t *testing.T) {
	for _, bad := range []string{"lan", "settings-link", "unit-override", "public-listener", "wrong-host-port", "unit-inactive"} {
		t.Run(bad, func(t *testing.T) {
			f := newNativeFixture(t)
			f.install(t)
			ctx := context.Background()
			if err := f.a.initialize(ctx); err != nil {
				t.Fatal(err)
			}
			if err := f.a.stop(ctx); err != nil {
				t.Fatal(err)
			}
			owner := f.maintenance.OwnerRequestID
			f.commands = nil
			switch bad {
			case "lan":
				if err := os.WriteFile(filepath.Join(f.dir, "var/lib/awf/magpie-config/magpie/settings.json"), []byte(`{"lan":true}`), 0600); err != nil {
					t.Fatal(err)
				}
			case "settings-link":
				name := filepath.Join(f.dir, "var/lib/awf/magpie-config/magpie/settings.json")
				if err := os.Remove(name); err != nil {
					t.Fatal(err)
				}
				if err := os.Symlink("../../../../../../etc/awf/install.json", name); err != nil {
					t.Fatal(err)
				}
			case "unit-override", "unit-inactive":
				old := f.a.command
				f.a.command = func(ctx context.Context, name string, args ...string) ([]byte, error) {
					if len(args) > 2 && args[0] == "show" && ((bad == "unit-override" && strings.Contains(args[2], "FragmentPath")) || (bad == "unit-inactive" && strings.Contains(args[2], "ControlGroup"))) {
						return []byte("ActiveState=failed\nMainPID=0\nDropInPaths=/etc/systemd/system/awf-host.service.d/override.conf\n"), nil
					}
					return old(ctx, name, args...)
				}
			case "public-listener", "wrong-host-port":
				address, port := "00000000", "1B9E"
				if bad == "wrong-host-port" {
					address, port = "0100007F", "1BAE"
				}
				if err := os.WriteFile(filepath.Join(f.dir, "proc/net/tcp"), []byte("0: "+address+":"+port+" 00000000:0000 0A\n1: 0100007F:0D61 00000000:0000 0A\n"), 0644); err != nil {
					t.Fatal(err)
				}
			}
			if err := f.a.start(ctx, false); err == nil {
				t.Fatal("unsafe/failed startup accepted")
			}
			if f.maintenance.Phase != "sealed" || f.maintenance.OwnerRequestID != owner {
				t.Fatal("failed startup lost original seal")
			}
			if _, err := os.Stat(filepath.Join(f.dir, "etc/awf/stopped-lease.json")); err != nil {
				t.Fatal("failed startup lost lease", err)
			}
			started := false
			for _, command := range f.commands {
				started = started || strings.Contains(command, "systemctl start")
			}
			postStart := bad == "public-listener" || bad == "wrong-host-port" || bad == "unit-inactive"
			if started != postStart {
				t.Fatal("startup happened across wrong refusal boundary", f.commands)
			}
			if postStart {
				for _, unit := range nativeUnits {
					found := false
					for _, command := range f.commands {
						found = found || command == "/usr/bin/systemctl stop "+unit
					}
					if !found {
						t.Fatal("failed startup did not stop both units", f.commands)
					}
				}
			}
		})
	}
}

func TestNativePreparedHostMismatchCannotMutateSystem(t *testing.T) {
	f := newNativeFixture(t)
	m := f.m
	dir, _ := nativePreparedFixture(t, m)
	f.m.SourceCommit = strings.Repeat("e", 40)
	if err := f.a.checkPreparedHost(context.Background(), m, dir); err == nil {
		t.Fatal("different executable identity accepted")
	}
	if err := f.a.fresh(); err != nil {
		t.Fatal("identity check mutated system", err)
	}
}

func TestNativeCacheProgressObservesContentOnly(t *testing.T) {
	dir := privateParent(t)
	for name, data := range map[string]string{"_cacache/content-v2/sha512/aa/blob": "received-bytes", "_logs/log": "not-download-progress"} {
		if err := os.MkdirAll(filepath.Dir(filepath.Join(dir, name)), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(dir, name), []byte(data), 0600); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.Symlink(filepath.Join(dir, "_logs/log"), filepath.Join(dir, "_cacache/content-v2/log-link")); err != nil {
		t.Fatal(err)
	}
	n, err := nativeCacheBytes(dir)
	if err != nil || n != int64(len("received-bytes")) {
		t.Fatal("progress counted logs or followed links", n, err)
	}
}

func TestNativePendingUpdateCannotClaimNoopCompletion(t *testing.T) {
	f := newNativeFixture(t)
	f.install(t)
	if err := f.a.writeNew("etc/awf/update-pending.json", []byte(`{"schema":1,"phase":"sealed-stopped"}`), 0600); err != nil {
		t.Fatal(err)
	}
	if err := f.a.update(context.Background(), f.m); err == nil {
		t.Fatal("same-manifest retry claimed completion across an unresolved update")
	}
}

// Copies the full reproduced inventory under a temporary root, including links
// sorted before their targets. Every machine command is still substituted; this
// test does not create an OS account or run a systemd service or Magpie process.
func TestNativeOfficialInventoryFixture(t *testing.T) {
	audit, installed := os.Getenv("AWF_PUBLIC_AUDIT_FIXTURE_DIR"), os.Getenv("AWF_PI_INSTALLED_FIXTURE_DIR")
	if audit == "" || installed == "" {
		t.Skip("explicit public audit and installed private fixtures required")
	}
	for _, dir := range []string{audit, installed} {
		if err := validateSandbox(dir); err != nil {
			t.Fatal(err)
		}
	}
	read := func(dir, name string) []byte {
		t.Helper()
		data, err := os.ReadFile(filepath.Join(dir, name))
		if err != nil {
			t.Fatal(err)
		}
		return data
	}
	m, payloads := applyFixture(t)
	replacePayload(&m, payloads, "node", read(audit, "node-v22.19.0-linux-x64.tar.gz"))
	replacePayload(&m, payloads, "magpie", read(audit, "magpie-cli-linux-amd64"))
	for i := range m.Components {
		if m.Components[i].ID == "pi" {
			for j := range m.Components[i].Artifacts {
				a := &m.Components[i].Artifacts[j]
				data := read(audit, "pi-official-"+a.Name)
				a.Bytes, a.SHA256 = int64(len(data)), hashBytes(data)
				a.URL = "https://github.com/earendil-works/pi/releases/download/v1.0.2/pi-coding-agent-install-" + a.Name
				payloads[a.URL] = data
			}
		}
	}
	extension := read(filepath.Join("..", ".."), "extensions/awf.ts")
	identity, _ := json.Marshal(extensionIdentity{1, m.Version, m.SourceCommit, m.ExtensionProtocol, m.PiRPCVersion})
	replacePayload(&m, payloads, "awf-extension", fixtureArchive(t, "tar.gz", []tarEntry{{name: "awf.ts", payload: extension}, {name: "extension.json", payload: identity}}))
	var pins []struct{ Name, MetadataSHA256 string }
	if err := json.Unmarshal(read(audit, "pi-supplemental-pins.json"), &pins); err != nil {
		t.Fatal(err)
	}
	in := RuntimeInput{CacheDirectory: filepath.Join(installed, "cache")}
	for _, pin := range pins {
		in.Supplemental = append(in.Supplemental, RegistryMetadata{Data: read(audit, "registry-"+strings.TrimPrefix(pin.Name, "@earendil-works/")+".json"), SHA256: pin.MetadataSHA256})
	}
	stage := stageApplyFixture(t, m, payloads)
	sandbox := privateParent(t)
	r, err := ApplyRuntimeFixture(context.Background(), m, stage, sandbox, &recorder{}, in)
	if err != nil {
		t.Fatal(err)
	}
	f := newNativeFixture(t)
	f.m = m
	if err := f.a.installPrepared(context.Background(), m, generationPath(t, sandbox), r); err != nil {
		t.Fatal("native inventory placement", err)
	}
	if _, err := f.a.installed(context.Background()); err != nil {
		t.Fatal("placed full inventory verification", err)
	}
	if err := f.a.initialize(context.Background()); err != nil {
		t.Fatal("confined service initialization", err)
	}
	for _, command := range f.commands {
		if strings.Contains(command, "systemctl start") || strings.Contains(command, "systemctl enable") {
			t.Fatal("fixture install activated services")
		}
	}
	t.Log("official full Node/Pi/Magpie inventory copied and checked beneath a temporary root; Host bytes and all machine commands remain synthetic; no native acceptance")
}
