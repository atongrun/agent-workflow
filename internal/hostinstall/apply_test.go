package hostinstall

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"hash/crc32"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/ulikunitz/xz"
)

type tarEntry struct {
	name    string
	payload []byte
	kind    byte
	link    string
	mode    int64
	size    int64
}

func fixtureArchive(t *testing.T, format string, entries []tarEntry) []byte {
	t.Helper()
	var out bytes.Buffer
	var archive bytes.Buffer
	tw := tar.NewWriter(&archive)
	for _, e := range entries {
		mode := e.mode
		if mode == 0 {
			mode = 0644
		}
		size := int64(len(e.payload))
		if e.size > 0 {
			size = e.size
		}
		kind := e.kind
		if kind == 0 {
			kind = tar.TypeReg
		}
		if err := tw.WriteHeader(&tar.Header{Name: e.name, Mode: mode, Size: size, Typeflag: kind, Linkname: e.link}); err != nil {
			t.Fatal(err)
		}
		if _, err := tw.Write(e.payload); err != nil {
			t.Fatal(err)
		}
	}
	_ = tw.Close() // oversized-header fixtures deliberately have an incomplete body
	if format == "tar.xz" {
		w, err := xz.NewWriter(&out)
		if err != nil {
			t.Fatal(err)
		}
		_, err = w.Write(archive.Bytes())
		if err != nil {
			t.Fatal(err)
		}
		if err = w.Close(); err != nil {
			t.Fatal(err)
		}
	} else {
		w := gzip.NewWriter(&out)
		if _, err := w.Write(archive.Bytes()); err != nil {
			t.Fatal(err)
		}
		if err := w.Close(); err != nil {
			t.Fatal(err)
		}
	}
	return out.Bytes()
}
func applyFixture(t *testing.T) (Manifest, map[string][]byte) {
	t.Helper()
	m, payloads := manifestFixture()
	elfBytes := payloads[m.Components[4].Artifacts[0].URL]
	host, _ := json.Marshal(buildIdentity{1, m.Version, m.SourceCommit, m.OS, m.Arch, m.HostProtocol})
	extension, _ := json.Marshal(extensionIdentity{1, m.Version, m.SourceCommit, m.ExtensionProtocol, m.PiRPCVersion})
	replacePayload(&m, payloads, "node", fixtureArchive(t, "tar.xz", []tarEntry{{name: "node-v22.19.0-linux-x64/bin/node", payload: elfBytes}, {name: "node-v22.19.0-linux-x64/LICENSE", payload: []byte("fixture notice")}, {name: "node-v22.19.0-linux-x64/bin/npm", kind: tar.TypeSymlink, link: "../lib/node_modules/npm/bin/npm-cli.js"}, {name: "node-v22.19.0-linux-x64/lib/node_modules/npm/bin/npm-cli.js", payload: []byte("not installed or executed")}}))
	replacePayload(&m, payloads, "awf-host", fixtureArchive(t, "tar.gz", []tarEntry{{name: "awf", payload: elfBytes}, {name: "build.json", payload: host}}))
	replacePayload(&m, payloads, "awf-extension", fixtureArchive(t, "tar.gz", []tarEntry{{name: "awf.ts", payload: []byte(`import { Type } from "typebox";`)}, {name: "extension.json", payload: extension}}))
	return m, payloads
}
func replacePayload(m *Manifest, payloads map[string][]byte, id string, data []byte) {
	for i := range m.Components {
		if m.Components[i].ID == id {
			a := &m.Components[i].Artifacts[0]
			sum := sha256.Sum256(data)
			a.SHA256 = hex.EncodeToString(sum[:])
			a.Bytes = int64(len(data))
			payloads[a.URL] = data
			return
		}
	}
}
func stageApplyFixture(t *testing.T, m Manifest, payloads map[string][]byte) string {
	t.Helper()
	if runtime.GOOS != "linux" {
		t.Skip("Linux-only fixture apply")
	}
	stage, err := Stage(context.Background(), m, privateParent(t), fixtureClient(m, payloads, nil, false), &recorder{})
	if err != nil {
		t.Fatal(err)
	}
	return stage
}
func generationPath(t *testing.T, sandbox string) string {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(sandbox, "current.json"))
	if err != nil {
		t.Fatal(err)
	}
	var sel fixtureSelection
	if strictJSON(data, &sel) != nil {
		t.Fatal("invalid selector")
	}
	return filepath.Join(sandbox, "releases", sel.Generation)
}
func TestFixtureApplySelectsVerifiedFilesAndTruthfulReceipt(t *testing.T) {
	m, payloads := applyFixture(t)
	stage := stageApplyFixture(t, m, payloads)
	sandbox := privateParent(t)
	observer := &recorder{}
	receipt, err := ApplyFixture(context.Background(), m, stage, sandbox, observer)
	if err != nil {
		t.Fatal(err)
	}
	if receipt.InstallationComplete || !receipt.FilesPrepared || receipt.Mode != "sandbox-fixture" || receipt.PiProgramRoot != "/opt/pi-cli" || receipt.ServicePiAgent != "/var/lib/awf/pi-agent" {
		t.Fatal(receipt)
	}
	for _, c := range receipt.Components {
		if c.RuntimeReady {
			t.Fatal("fixture claimed runtime readiness")
		}
		if c.ID == "pi" && (c.State != "unavailable" || len(c.Files) != 0) {
			t.Fatal("Pi metadata misrepresented")
		}
		if c.ID == "awf-extension" && c.State != "files_prepared_runtime_unavailable" {
			t.Fatal(c)
		}
	}
	generation := generationPath(t, sandbox)
	for _, name := range []string{"opt/node/bin/node", "opt/awf/awf", "opt/awf/build.json", "opt/awf/extensions/awf.ts", "opt/magpie/magpie", "install.json"} {
		if _, err = os.Stat(filepath.Join(generation, name)); err != nil {
			t.Fatal(err)
		}
	}
	for _, name := range []string{"opt/pi-cli", "var/lib/awf/pi-agent", "etc/awf/host.json", "opt/node/bin/npm", "opt/node/lib"} {
		if _, err = os.Lstat(filepath.Join(generation, name)); !os.IsNotExist(err) {
			t.Fatal("unexpected install", name, err)
		}
	}
	for _, event := range observer.events {
		if event.Stage == "install" || event.Stage == "config" || event.Stage == "health" {
			t.Fatal("invented runtime stage", event)
		}
	}
	before, _ := os.ReadFile(filepath.Join(sandbox, "current.json"))
	if _, err = ApplyFixture(context.Background(), m, stage, sandbox, &recorder{}); err != nil {
		t.Fatal("idempotent apply", err)
	}
	after, _ := os.ReadFile(filepath.Join(sandbox, "current.json"))
	if !bytes.Equal(before, after) {
		t.Fatal("selector changed on retry")
	}
}
func TestFixtureApplyRejectsUnsafeArchivesAndIdentity(t *testing.T) {
	for _, mode := range []string{"traversal", "absolute", "backslash", "normalized", "symlink", "hardlink", "device", "duplicate", "setuid", "oversized", "host-arch", "identity", "unknown-file", "bad-gzip", "bad-xz", "huge-xz-dictionary", "node-link"} {
		t.Run(mode, func(t *testing.T) {
			m, payloads := applyFixture(t)
			elfBytes := payloads[m.Components[4].Artifacts[0].URL]
			identity, _ := json.Marshal(buildIdentity{1, m.Version, m.SourceCommit, m.OS, m.Arch, m.HostProtocol})
			entries := []tarEntry{{name: "awf", payload: elfBytes}, {name: "build.json", payload: identity}}
			component := "awf-host"
			format := "tar.gz"
			switch mode {
			case "traversal":
				entries[0].name = "../escape"
			case "absolute":
				entries[0].name = "/tmp/escape"
			case "backslash":
				entries[0].name = "a\\escape"
			case "normalized":
				entries[0].name = "./awf"
			case "symlink":
				entries[0] = tarEntry{name: "awf", kind: tar.TypeSymlink, link: "../../escape"}
			case "hardlink":
				entries[0] = tarEntry{name: "awf", kind: tar.TypeLink, link: "build.json"}
			case "device":
				entries[0] = tarEntry{name: "awf", kind: tar.TypeChar}
			case "duplicate":
				entries = append(entries, entries[0])
			case "setuid":
				entries[0].mode = 04755
			case "oversized":
				entries = []tarEntry{{name: "awf", size: maxExtractedFileBytes + 1}}
			case "host-arch":
				entries[0].payload = append([]byte(nil), elfBytes...)
				binary.LittleEndian.PutUint16(entries[0].payload[18:], 183)
			case "identity":
				entries[1].payload = []byte(`{"schema":1}`)
			case "unknown-file":
				entries = append(entries, tarEntry{name: "run-installer.sh", payload: []byte("not executed")})
			case "node-link":
				component = "node"
				format = "tar.xz"
				entries = []tarEntry{{name: "node-v22.19.0-linux-x64/bin/npm", kind: tar.TypeSymlink, link: "/etc/private-secret"}}
			}
			data := fixtureArchive(t, format, entries)
			if mode == "bad-gzip" {
				data[len(data)-1] ^= 1
			}
			if mode == "bad-xz" || mode == "huge-xz-dictionary" {
				component = "node"
				data = append([]byte(nil), payloads[m.Components[0].Artifacts[0].URL]...)
				if mode == "bad-xz" {
					data[len(data)-1] ^= 1
				} else {
					n := (int(data[12]) + 1) * 4
					data[16] = 40
					binary.LittleEndian.PutUint32(data[12+n-4:], crc32.ChecksumIEEE(data[12:12+n-4]))
				}
			}
			replacePayload(&m, payloads, component, data)
			stage := stageApplyFixture(t, m, payloads)
			sandbox := privateParent(t)
			_, err := ApplyFixture(context.Background(), m, stage, sandbox, &recorder{})
			if err == nil {
				t.Fatal("unsafe payload accepted")
			}
			if strings.Contains(err.Error(), "private-secret") {
				t.Fatal("unsafe payload path leaked")
			}
			if _, err = os.Stat(filepath.Join(sandbox, "current.json")); !os.IsNotExist(err) {
				t.Fatal("failed apply selected a generation")
			}
		})
	}
}
func TestFixtureApplyRejectsTamperingAndMalformedSelectors(t *testing.T) {
	for _, mode := range []string{"bytes", "missing", "extra", "link", "receipt", "selector-path", "selector-unknown", "selector-digest", "release-link"} {
		t.Run(mode, func(t *testing.T) {
			m, payloads := applyFixture(t)
			stage := stageApplyFixture(t, m, payloads)
			sandbox := privateParent(t)
			if _, err := ApplyFixture(context.Background(), m, stage, sandbox, &recorder{}); err != nil {
				t.Fatal(err)
			}
			generation := generationPath(t, sandbox)
			program := filepath.Join(generation, "opt/awf/awf")
			switch mode {
			case "bytes":
				_ = os.WriteFile(program, []byte("tampered"), 0755)
			case "missing":
				_ = os.Remove(program)
			case "extra":
				_ = os.WriteFile(filepath.Join(generation, "unexpected"), []byte("x"), 0600)
			case "link":
				_ = os.Remove(program)
				_ = os.Symlink("/tmp/private-secret", program)
			case "receipt":
				_ = os.WriteFile(filepath.Join(generation, "install.json"), []byte(`{"schema":1}`), 0600)
			case "selector-path":
				_ = os.WriteFile(filepath.Join(sandbox, "current.json"), []byte(`{"schema":1,"mode":"sandbox-fixture","generation":"../../escape"}`), 0600)
			case "selector-unknown":
				data, _ := os.ReadFile(filepath.Join(sandbox, "current.json"))
				data = append([]byte(`{"unexpected":true,`), data[1:]...)
				_ = os.WriteFile(filepath.Join(sandbox, "current.json"), data, 0600)
			case "selector-digest":
				data, _ := os.ReadFile(filepath.Join(sandbox, "current.json"))
				var sel fixtureSelection
				_ = json.Unmarshal(data, &sel)
				sel.ReceiptSHA256 = strings.Repeat("a", 64)
				data, _ = json.Marshal(sel)
				_ = os.WriteFile(filepath.Join(sandbox, "current.json"), data, 0600)
			case "release-link":
				_ = os.RemoveAll(filepath.Join(sandbox, "releases"))
				_ = os.Symlink(t.TempDir(), filepath.Join(sandbox, "releases"))
			}
			before, _ := os.ReadFile(filepath.Join(sandbox, "current.json"))
			if _, err := ApplyFixture(context.Background(), m, stage, sandbox, &recorder{}); err == nil {
				t.Fatal("tampering adopted")
			}
			after, _ := os.ReadFile(filepath.Join(sandbox, "current.json"))
			if !bytes.Equal(before, after) {
				t.Fatal("failure changed current")
			}
		})
	}
}
func TestFixtureApplyCancelRecoverAndConcurrentLock(t *testing.T) {
	m, payloads := applyFixture(t)
	stage := stageApplyFixture(t, m, payloads)
	for _, boundary := range []string{"extract", "activate"} {
		t.Run(boundary, func(t *testing.T) {
			sandbox := privateParent(t)
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			o := callbackObserver(func(e ProgressEvent) {
				if e.Stage == boundary && e.State == "started" {
					cancel()
				}
			})
			if _, err := ApplyFixture(ctx, m, stage, sandbox, o); err == nil {
				t.Fatal("cancelled apply succeeded")
			}
			if _, err := os.Stat(filepath.Join(sandbox, "current.json")); !os.IsNotExist(err) {
				t.Fatal("cancel selected generation")
			}
			if _, err := ApplyFixture(context.Background(), m, stage, sandbox, &recorder{}); err != nil {
				t.Fatal("retry recovery failed", err)
			}
		})
	}
	sandbox := privateParent(t)
	started := make(chan struct{})
	release := make(chan struct{})
	done := make(chan error, 1)
	go func() {
		o := callbackObserver(func(e ProgressEvent) {
			if e.Component == "node" && e.Stage == "extract" && e.State == "started" {
				close(started)
				<-release
			}
		})
		_, err := ApplyFixture(context.Background(), m, stage, sandbox, o)
		done <- err
	}()
	<-started
	_, err := ApplyFixture(context.Background(), m, stage, sandbox, &recorder{})
	close(release)
	if err == nil {
		t.Fatal("concurrent apply bypassed lock")
	}
	if err = <-done; err != nil {
		t.Fatal(err)
	}
	if _, err = ApplyFixture(context.Background(), m, stage, sandbox, &recorder{}); err != nil {
		t.Fatal("lock not released", err)
	}
}
func TestFixtureApplyCrashHelper(t *testing.T) {
	if os.Getenv("AWF_FIXTURE_CRASH_HELPER") != "1" {
		return
	}
	data, err := os.ReadFile(os.Getenv("AWF_FIXTURE_MANIFEST"))
	if err != nil {
		os.Exit(24)
	}
	m, err := ParseManifest(data)
	if err != nil {
		os.Exit(24)
	}
	_, _ = ApplyFixture(context.Background(), m, os.Getenv("AWF_FIXTURE_STAGE"), os.Getenv("AWF_FIXTURE_SANDBOX"), callbackObserver(func(e ProgressEvent) {
		if e.Stage == "activate" && e.State == "started" {
			os.Exit(23)
		}
	}))
	os.Exit(24)
}
func TestFixtureApplyRecoversAfterProcessDeath(t *testing.T) {
	m, payloads := applyFixture(t)
	stage := stageApplyFixture(t, m, payloads)
	sandbox := privateParent(t)
	manifest := filepath.Join(t.TempDir(), "manifest.json")
	data, _ := json.Marshal(m)
	if err := os.WriteFile(manifest, data, 0600); err != nil {
		t.Fatal(err)
	}
	child := exec.Command(os.Args[0], "-test.run=^TestFixtureApplyCrashHelper$")
	child.Env = append(os.Environ(), "AWF_FIXTURE_CRASH_HELPER=1", "AWF_FIXTURE_MANIFEST="+manifest, "AWF_FIXTURE_STAGE="+stage, "AWF_FIXTURE_SANDBOX="+sandbox)
	err := child.Run()
	var exit *exec.ExitError
	if !errors.As(err, &exit) || exit.ExitCode() != 23 {
		t.Fatal("crash helper failed", err)
	}
	if _, err = os.Stat(filepath.Join(sandbox, "current.json")); !os.IsNotExist(err) {
		t.Fatal("crash published selector")
	}
	if _, err = ApplyFixture(context.Background(), m, stage, sandbox, &recorder{}); err != nil {
		t.Fatal("crash recovery/lock release failed", err)
	}
}
func TestFixtureApplyRefusesRealRootsAndLinkedSandbox(t *testing.T) {
	m, payloads := applyFixture(t)
	stage := stageApplyFixture(t, m, payloads)
	for _, root := range []string{"/opt/awf", "/etc/awf", "/var/lib/awf", "/tmp", "relative", privateParent(t) + "/../bad"} {
		if _, err := ApplyFixture(context.Background(), m, stage, root, &recorder{}); err == nil {
			t.Fatal("unsafe root accepted", root)
		}
	}
	parent := privateParent(t)
	real := privateParent(t)
	if err := os.Symlink(real, filepath.Join(parent, "link")); err != nil {
		t.Fatal(err)
	}
	if _, err := ApplyFixture(context.Background(), m, stage, filepath.Join(parent, "link"), &recorder{}); err == nil {
		t.Fatal("symlink root accepted")
	}
	nested := filepath.Join(real, "child")
	if err := os.Mkdir(nested, 0700); err != nil {
		t.Fatal(err)
	}
	if _, err := ApplyFixture(context.Background(), m, stage, filepath.Join(parent, "link", "child"), &recorder{}); err == nil {
		t.Fatal("symlink ancestor accepted")
	}
}

func TestFixtureApplyIgnoresInterruptedScratchWithoutAdoption(t *testing.T) {
	m, payloads := applyFixture(t)
	stage := stageApplyFixture(t, m, payloads)
	sandbox := privateParent(t)
	partial := filepath.Join(sandbox, ".fixture-apply-selection-crashed")
	if err := os.WriteFile(partial, []byte(`{"generation":"../../private-secret"`), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(filepath.Join(sandbox, ".fixture-apply-crashed"), 0700); err != nil {
		t.Fatal(err)
	}
	if _, err := ApplyFixture(context.Background(), m, stage, sandbox, &recorder{}); err != nil {
		t.Fatal("scratch blocked recovery", err)
	}
	data, err := os.ReadFile(filepath.Join(sandbox, "current.json"))
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(data, []byte("private-secret")) {
		t.Fatal("partial selector adopted")
	}
	if _, err = os.Stat(partial); err != nil {
		t.Fatal("unowned scratch silently removed")
	}
}
