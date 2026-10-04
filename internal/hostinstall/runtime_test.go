package hostinstall

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha1"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"
	"time"
)

func TestRuntimeRejectsUnauditedInputsBeforeExecution(t *testing.T) {
	m, _ := manifestFixture()
	dir := privateParent(t)
	if _, err := ApplyRuntimeFixture(context.Background(), m, "missing", dir, &recorder{}, RuntimeInput{}); err == nil {
		t.Fatal("unreviewed executable admitted")
	}
	entries, err := os.ReadDir(dir)
	if err != nil || len(entries) != 0 {
		t.Fatal("rejection mutated sandbox", err)
	}
}

func TestRuntimeArchiveBoundaries(t *testing.T) {
	good := []tarEntry{{name: "package/package.json", payload: []byte(`{"name":"fixture","version":"1.0.2","bin":{"fixture":"run.js"}}`)}, {name: "package/run.js", payload: []byte("// no code is executed")}}
	for _, mode := range []string{"valid", "entry-limit", "expanded-limit", "file-limit", "traversal", "symlink", "hardlink", "setuid", "duplicate", "wrong-name", "bin-escape", "nonzero-tail"} {
		t.Run(mode, func(t *testing.T) {
			entries := append([]tarEntry(nil), good...)
			budget := &extractionBudget{maxEntries: maxRuntimeEntries}
			switch mode {
			case "entry-limit":
				budget.entries = maxRuntimeEntries - 1
			case "expanded-limit":
				budget.expanded = maxExpandedBytes - 512
			case "file-limit":
				entries[1].size = maxNpmTarballBytes + 1
			case "traversal":
				entries[1].name = "package/../escape"
			case "symlink":
				entries[1] = tarEntry{name: "package/run.js", kind: tar.TypeSymlink, link: "/tmp/escape"}
			case "hardlink":
				entries[1] = tarEntry{name: "package/run.js", kind: tar.TypeLink, link: "package/package.json"}
			case "setuid":
				entries[1].mode = 04755
			case "duplicate":
				entries = append(entries, entries[1])
			case "wrong-name":
				entries[0].payload = []byte(`{"name":"other","version":"1.0.2"}`)
			case "bin-escape":
				entries[0].payload = []byte(`{"name":"fixture","version":"1.0.2","bin":{"fixture":"../escape"}}`)
			case "nonzero-tail": // a second gzip stream after the tar EOF, below
			}
			archive := fixtureArchive(t, "tar.gz", entries)
			if mode == "nonzero-tail" {
				var extra bytes.Buffer
				gz := gzip.NewWriter(&extra)
				gz.Write([]byte("hidden tar suffix"))
				gz.Close()
				archive = append(archive, extra.Bytes()...)
			}
			expected := map[string]InstalledFile{}
			err := scanNpmTar(context.Background(), bytes.NewReader(archive), "node_modules/fixture", runtimePackage{Version: "1.0.2"}, expected, budget)
			if mode != "valid" {
				if err == nil {
					t.Fatal("unsafe archive accepted")
				}
				return
			}
			if err != nil || len(expected) != 3 || expected[piReleaseDir+"/node_modules/.bin/fixture"].LinkTarget != "../fixture/run.js" {
				t.Fatal(expected, err)
			}
		})
	}
}

func TestRuntimePAXAndPlatformPolicy(t *testing.T) {
	for _, records := range []map[string]string{{"path": "package/run.js", "size": "3", "uid": "0", "NODETAR.depth": "1"}, {"linkpath": "/etc/passwd"}, {"GNU.sparse.size": "42"}, {"path": "../escape"}, {"size": "4"}, {"unknown": "yes"}, {"NODETAR.large": strings.Repeat("x", 4097)}} {
		h := &tar.Header{Name: "package/run.js", Size: 3, PAXRecords: records}
		if npmPAX(h) != (records["uid"] == "0") {
			t.Fatal("PAX policy", records)
		}
	}
	for _, tc := range []struct {
		rules   []string
		allowed bool
	}{{nil, true}, {[]string{"linux"}, true}, {[]string{"darwin"}, false}, {[]string{"!darwin"}, true}, {[]string{"!linux"}, false}, {[]string{"any", "!linux"}, false}} {
		if runtimePlatform(tc.rules, "linux") != tc.allowed {
			t.Fatal(tc)
		}
	}
}

func TestRuntimeGenerationExactLinksAndOwnership(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("Linux owner fixture")
	}
	dir := privateParent(t)
	root, err := os.OpenRoot(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer root.Close()
	file, err := writeSelected(context.Background(), root, "opt/node/lib/run.js", strings.NewReader("fixture"), 7, 0644)
	if err != nil {
		t.Fatal(err)
	}
	link := InstalledFile{Path: "opt/node/bin/npm", Mode: 0777, LinkTarget: "../lib/run.js"}
	if err := createPinnedLink(root, link); err != nil {
		t.Fatal(err)
	}
	receipt := InstallReceipt{Schema: 2, Mode: "sandbox-runtime-fixture", PiRuntime: &PiRuntimeReceipt{OwnerUID: os.Getuid()}, Components: []AppliedComponent{{Files: []InstalledFile{file, link}}}}
	data, _ := json.Marshal(receipt)
	if err := writeSynced(root, "install.json", data); err != nil {
		t.Fatal(err)
	}
	if err := verifyGeneration(dir, receipt, data); err != nil {
		t.Fatal(err)
	}
	receipt.PiRuntime.OwnerUID++
	if verifyGeneration(dir, receipt, data) == nil {
		t.Fatal("mismatched owner receipt accepted")
	}
	receipt.PiRuntime.OwnerUID--
	if err := os.Chmod(filepath.Join(dir, file.Path), 0644|os.ModeSetuid); err != nil {
		t.Fatal(err)
	}
	if verifyGeneration(dir, receipt, data) == nil {
		t.Fatal("privileged file adopted")
	}
	if err := os.Chmod(filepath.Join(dir, file.Path), 0644); err != nil {
		t.Fatal(err)
	}
	for _, target := range []string{"/etc/passwd", "../lib/missing", "../lib/run.js/../other"} {
		if err := os.Remove(filepath.Join(dir, link.Path)); err != nil {
			t.Fatal(err)
		}
		if err := os.Symlink(target, filepath.Join(dir, link.Path)); err != nil {
			t.Fatal(err)
		}
		if verifyGeneration(dir, receipt, data) == nil {
			t.Fatal("modified link accepted")
		}
	}
	if createPinnedLink(root, InstalledFile{Path: "opt/node/bin/bad", LinkTarget: "../../awf/awf"}) == nil {
		t.Fatal("cross-component link accepted")
	}
}

// Explicit opt-in: official downloaded programs are never run by default tests.
// All five component files are prepared; Host/identity are synthetic fixtures,
// while the independent extension contains this checkout's actual AWF source.
func TestRuntimeOfficialOfflineFixture(t *testing.T) {
	audit, installed := os.Getenv("AWF_PUBLIC_AUDIT_FIXTURE_DIR"), os.Getenv("AWF_PI_INSTALLED_FIXTURE_DIR")
	if audit == "" || installed == "" {
		t.Skip("explicit public audit and installed private fixtures required")
	}
	if runtime.GOOS != "linux" || runtime.GOARCH != "amd64" {
		t.Fatal("Linux amd64 only")
	}
	for _, dir := range []string{audit, installed} {
		if err := validateSandbox(dir); err != nil {
			t.Fatal(err)
		}
	}
	read := func(dir, name string) []byte {
		t.Helper()
		b, err := os.ReadFile(filepath.Join(dir, name))
		if err != nil {
			t.Fatal(err)
		}
		return b
	}
	m, payloads := applyFixture(t)
	replacePayload(&m, payloads, "node", read(audit, "node-v22.19.0-linux-x64.tar.gz"))
	replacePayload(&m, payloads, "magpie", read(audit, "magpie-cli-linux-amd64"))
	for i := range m.Components {
		if m.Components[i].ID == "pi" {
			for j := range m.Components[i].Artifacts {
				a := &m.Components[i].Artifacts[j]
				b := read(audit, "pi-official-"+a.Name)
				a.Bytes = int64(len(b))
				a.SHA256 = hashBytes(b)
				a.URL = "https://github.com/earendil-works/pi/releases/download/v1.0.2/pi-coding-agent-install-" + a.Name
				payloads[a.URL] = b
			}
		}
	}
	extension := read(filepath.Join("..", ".."), "extensions/awf.ts")
	identity, _ := json.Marshal(extensionIdentity{1, m.Version, m.SourceCommit, m.ExtensionProtocol, m.PiRPCVersion})
	replacePayload(&m, payloads, "awf-extension", fixtureArchive(t, "tar.gz", []tarEntry{{name: "awf.ts", payload: extension}, {name: "extension.json", payload: identity}}))
	var pins []struct {
		Name           string `json:"name"`
		MetadataSHA256 string `json:"metadataSHA256"`
	}
	if err := json.Unmarshal(read(audit, "pi-supplemental-pins.json"), &pins); err != nil {
		t.Fatal(err)
	}
	in := RuntimeInput{CacheDirectory: filepath.Join(installed, "cache")}
	for _, p := range pins {
		in.Supplemental = append(in.Supplemental, RegistryMetadata{Data: read(audit, "registry-"+strings.TrimPrefix(p.Name, "@earendil-works/")+".json"), SHA256: p.MetadataSHA256})
	}
	stage := stageApplyFixture(t, m, payloads)
	if _, err := planPiRuntime(context.Background(), stage, RuntimeInput{CacheDirectory: in.CacheDirectory, Supplemental: in.Supplemental[:7]}, &extractionBudget{}); err == nil {
		t.Fatal("missing supplementary integrity admitted")
	}
	sandbox := privateParent(t)
	observer := &recorder{}
	receipt, err := ApplyRuntimeFixture(context.Background(), m, stage, sandbox, observer, in)
	if err != nil {
		t.Fatal(err)
	}
	if receipt.Schema != 2 || receipt.InstallationComplete || receipt.PiRuntime == nil || receipt.PiRuntime.LockedPackages != 147 || receipt.PiRuntime.InstalledPackages != 122 || receipt.PiRuntime.SkippedPlatformOptional != 25 || receipt.PiRuntime.LifecycleScriptsRun || receipt.PiRuntime.NativeAcceptance || receipt.PiRuntime.OwnerUID != os.Getuid() {
		t.Fatal(receipt.PiRuntime)
	}
	links := 0
	for _, c := range receipt.Components {
		if c.RuntimeReady || c.State != "files_prepared" {
			t.Fatal(c.ID, c.State)
		}
		for _, f := range c.Files {
			if f.LinkTarget != "" {
				links++
			}
		}
	}
	if links != 12 {
		t.Fatal("Node/Pi link count", links)
	}
	sawNpm, sawClosure := false, false
	for _, e := range observer.events {
		if e.Stage == "npm-ci-offline" && e.State == "completed" {
			sawNpm = true
		}
		if e.Stage == "closure-verify" && e.State == "completed" {
			sawClosure = true
		}
	}
	if !sawNpm || !sawClosure {
		t.Fatal("missing real phases")
	}
	generation := generationPath(t, sandbox)
	node := filepath.Join(generation, "opt/node/bin/node")
	launcher := filepath.Join(generation, "opt/pi-cli/bin/pi")
	checkPiOffline(t, privateParent(t), node, launcher, filepath.Join(generation, "opt/awf/extensions/awf.ts"))
	// Verify the exact prepared AWF extension, outside the Pi release tree.
	if !bytes.Equal(read(generation, "opt/awf/extensions/awf.ts"), extension) {
		t.Fatal("extension changed")
	}
	for _, tc := range []struct{ cli, want string }{{"opt/node/lib/node_modules/npm/bin/npm-cli.js", "10.9.3"}, {"opt/pi-cli/releases/1.0.2/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js", "1.0.2"}} {
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		cmd := exec.CommandContext(ctx, node, filepath.Join(generation, tc.cli), "--version")
		cmd.Env = []string{"PATH=" + filepath.Dir(node) + ":/usr/bin:/bin", "PI_CODING_AGENT_DIR=" + filepath.Join(privateParent(t), "agent")}
		out, err := cmd.Output()
		cancel()
		if err != nil || strings.TrimSpace(string(out)) != tc.want {
			t.Fatal(string(out), err)
		}
	}
	checkRuntimeImports(t, node, generation)
	checkManagedUpdateRejection(t, node, launcher)
	before := read(sandbox, "current.json")
	again, err := ApplyRuntimeFixture(context.Background(), m, stage, sandbox, &recorder{}, in)
	if err != nil || !reflect.DeepEqual(receipt, again) || !bytes.Equal(before, read(sandbox, "current.json")) {
		t.Fatal("fresh idempotent rebuild", err)
	}
	// Runtime data/launcher cannot be adopted from a mutable receipt on retry.
	if err := os.WriteFile(launcher, []byte("tampered"), 0755); err != nil {
		t.Fatal(err)
	}
	if _, err := ApplyRuntimeFixture(context.Background(), m, stage, sandbox, &recorder{}, in); err == nil {
		t.Fatal("mutated runtime accepted")
	}
	if !bytes.Equal(before, read(sandbox, "current.json")) {
		t.Fatal("failed retry changed selection")
	}
	// Cancellation at the actual npm phase does not select a generation and cleans
	// this call's scratch. Existing cache bytes and caller-owned inputs stay intact.
	cancelled := privateParent(t)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	_, err = ApplyRuntimeFixture(ctx, m, stage, cancelled, callbackObserver(func(e ProgressEvent) {
		if e.Stage == "npm-ci-offline" && e.State == "started" {
			cancel()
		}
	}), in)
	if err == nil {
		t.Fatal("cancelled npm selected runtime")
	}
	if _, err := os.Stat(filepath.Join(cancelled, "current.json")); !os.IsNotExist(err) {
		t.Fatal("cancel selected generation")
	}
	entries, err := os.ReadDir(cancelled)
	if err != nil || len(entries) != 1 || entries[0].Name() != ".apply.lock" {
		t.Fatal("scratch not cleaned", entries, err)
	}
	// The same apply lock fences runtime preparation before executing npm.
	concurrent := privateParent(t)
	running, release := make(chan struct{}), make(chan struct{})
	done := make(chan error, 1)
	lockCtx, stop := context.WithCancel(context.Background())
	defer stop()
	go func() {
		_, err := ApplyRuntimeFixture(lockCtx, m, stage, concurrent, callbackObserver(func(e ProgressEvent) {
			if e.Component == "node" && e.Stage == "extract" && e.State == "started" {
				close(running)
				<-release
				stop()
			}
		}), in)
		done <- err
	}()
	<-running
	_, secondErr := ApplyRuntimeFixture(context.Background(), m, stage, concurrent, &recorder{}, in)
	close(release)
	firstErr := <-done
	if secondErr == nil || firstErr == nil {
		t.Fatal("runtime concurrency or cancellation fence", firstErr, secondErr)
	}
	if _, err := os.Stat(filepath.Join(concurrent, "current.json")); !os.IsNotExist(err) {
		t.Fatal("concurrent cancellation selected runtime")
	}
	t.Logf("runtime schema2: 147 lock entries / 122 verified installed / 25 optional skipped / 12 exact Node+Pi links; launcher PID+stdio and force-update route verified; no native acceptance")
}

func checkManagedUpdateRejection(t *testing.T, node, launcher string) {
	t.Helper()
	work := privateParent(t)
	guard := filepath.Join(work, "guard.mjs")
	if err := os.WriteFile(guard, []byte(piOfflineGuard), 0600); err != nil {
		t.Fatal(err)
	}
	root := filepath.Dir(filepath.Dir(launcher))
	before, err := os.ReadFile(filepath.Join(root, "current-version"))
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, node, launcher, "update", "self", "--force")
	cmd.Env = []string{"PATH=/nonexistent", "PI_INSTALLER_API_BASE=http://127.0.0.1:1/forbidden", "PI_CODING_AGENT_DIR=" + filepath.Join(work, "agent"), "NODE_OPTIONS=--import=" + guard}
	cmd.Dir = work
	out, err := cmd.CombinedOutput()
	var exit *exec.ExitError
	if !errors.As(err, &exit) || exit.ExitCode() != 1 || !strings.Contains(string(out), "Managed pi installations do not support --force") || strings.Contains(string(out), "awf_network_denied") || !strings.Contains(string(out), `"blockedNetworkCalls":0`) {
		t.Fatal("official managed update contract", string(out), err)
	}
	after, err := os.ReadFile(filepath.Join(root, "current-version"))
	if err != nil || !bytes.Equal(before, after) {
		t.Fatal("rejected update changed selector")
	}
}

func hashBytes(data []byte) string { sum := sha256.Sum256(data); return hex.EncodeToString(sum[:]) }

func TestRuntimeRootMetadataMustRemainPinned(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("Linux only")
	}
	for _, name := range []string{"package.json", "package-lock.json"} {
		t.Run(name, func(t *testing.T) {
			dir := privateParent(t)
			root, err := os.OpenRoot(dir)
			if err != nil {
				t.Fatal(err)
			}
			defer root.Close()
			plan := &piRuntimePlan{pkg: []byte("original package"), lock: []byte("original lock")}
			for key, b := range map[string][]byte{"package.json": plan.pkg, "package-lock.json": plan.lock} {
				if _, err := writeSelected(context.Background(), root, piReleaseDir+"/"+key, bytes.NewReader(b), int64(len(b)), 0644); err != nil {
					t.Fatal(err)
				}
			}
			if err := verifyPiRootMetadata(root, plan); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(filepath.Join(dir, piReleaseDir, name), []byte("mutated metadata"), 0644); err != nil {
				t.Fatal(err)
			}
			if verifyPiRootMetadata(root, plan) == nil {
				t.Fatal("mutable root metadata adopted")
			}
		})
	}
}
func TestRuntimeCacheRequiresURLBoundIntegrity(t *testing.T) {
	for _, kind := range []string{"valid", "missing", "url", "integrity", "digest", "link"} {
		t.Run(kind, func(t *testing.T) {
			dir := privateParent(t)
			root, err := os.OpenRoot(dir)
			if err != nil {
				t.Fatal(err)
			}
			defer root.Close()
			if err := root.Mkdir("_cacache", 0700); err != nil {
				t.Fatal(err)
			}
			if err := root.Mkdir("_cacache/index-v5", 0700); err != nil {
				t.Fatal(err)
			}
			url, integrity := "https://registry.npmjs.org/fixture/-/fixture-1.0.2.tgz", "sha512-reviewed"
			key, actual := url, integrity
			if kind == "url" {
				key += "-other"
			}
			if kind == "integrity" {
				actual += "-other"
			}
			data, _ := json.Marshal(map[string]string{"key": "make-fetch-happen:request-cache:" + key, "integrity": actual})
			hash := sha1.Sum(data)
			line := hex.EncodeToString(hash[:]) + "\t" + string(data) + "\n"
			if kind == "digest" {
				line = "bad" + line
			}
			if kind == "missing" {
				line = ""
			}
			name := filepath.Join(dir, "_cacache/index-v5/entry")
			if err := os.WriteFile(name, []byte(line), 0600); err != nil {
				t.Fatal(err)
			}
			if kind == "link" {
				if err := os.Rename(name, name+"-real"); err != nil {
					t.Fatal(err)
				}
				if err := os.Symlink("entry-real", name); err != nil {
					t.Fatal(err)
				}
			}
			err = verifyRuntimeCacheIndex(root, map[string]runtimePackage{"node_modules/fixture": {Resolved: url, Integrity: integrity}})
			if (err == nil) != (kind == "valid") {
				t.Fatal("cache binding", kind, err)
			}
		})
	}
}
func TestRuntimeKnownAliasesRequireIdenticalBytes(t *testing.T) {
	for _, kind := range []string{"valid", "different", "third", "unknown-version"} {
		t.Run(kind, func(t *testing.T) {
			first := tarEntry{name: "package/./dist/index.js", payload: []byte("same")}
			second := tarEntry{name: "package/dist/index.js", payload: []byte("same")}
			entries := []tarEntry{{name: "package/package.json", payload: []byte(`{"name":"agent-base","version":"7.1.4"}`)}, first, second}
			version := "7.1.4"
			if kind == "different" {
				entries[2].payload = []byte("diff")
			}
			if kind == "third" {
				entries = append(entries, second)
			}
			if kind == "unknown-version" {
				version = "7.1.5"
			}
			err := scanNpmTar(context.Background(), bytes.NewReader(fixtureArchive(t, "tar.gz", entries)), "node_modules/agent-base", runtimePackage{Version: version}, map[string]InstalledFile{}, &extractionBudget{})
			if (err == nil) != (kind == "valid") {
				t.Fatal(kind, err)
			}
		})
	}
}

func checkRuntimeImports(t *testing.T, node, generation string) {
	t.Helper()
	work := privateParent(t)
	guard, script := filepath.Join(work, "guard.mjs"), filepath.Join(work, "imports.mjs")
	for name, data := range map[string]string{guard: piOfflineGuard, script: runtimeImportProbe} {
		if err := os.WriteFile(name, []byte(data), 0600); err != nil {
			t.Fatal(err)
		}
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, node, "--experimental-import-meta-resolve", script, filepath.Join(generation, piReleaseDir, "package.json"))
	cmd.Env = []string{"PATH=" + filepath.Dir(node) + ":/usr/bin:/bin", "NODE_OPTIONS=--import=" + guard, "PI_CODING_AGENT_DIR=" + filepath.Join(work, "agent")}
	cmd.Dir = work
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	out, err := cmd.Output()
	if err != nil || strings.TrimSpace(string(out)) != "12" || strings.Contains(stderr.String(), "awf_network_denied") || !strings.Contains(stderr.String(), `"blockedNetworkCalls":0`) {
		t.Fatal("prepared dependency imports", string(out), stderr.String(), err)
	}
}

const runtimeImportProbe = `import {pathToFileURL} from "node:url";
const parent=pathToFileURL(process.argv[2]).href;
const names=["typebox","typebox/compile","typebox/value","jiti","esbuild","protobufjs","@google/genai","@silvia-odwyer/photon-node","@earendil-works/pi-ai","@earendil-works/pi-agent-core","@earendil-works/pi-tui","@earendil-works/pi-coding-agent"];
for(const name of names)await import(import.meta.resolve(name,parent));
console.log(names.length);
`

func TestRuntimeArchiveBombsFailClosed(t *testing.T) {
	// A real small-compressed archive with more than the allowed entry count.
	entries := []tarEntry{{name: "package/package.json", payload: []byte(`{"name":"fixture","version":"1.0.2"}`)}}
	for i := 0; i < maxRuntimeEntries; i++ {
		entries = append(entries, tarEntry{name: fmt.Sprintf("package/dir-%05d", i), kind: tar.TypeDir})
	}
	data := fixtureArchive(t, "tar.gz", entries)
	err := scanNpmTar(context.Background(), bytes.NewReader(data), "node_modules/fixture", runtimePackage{Version: "1.0.2"}, map[string]InstalledFile{}, &extractionBudget{})
	if err == nil || !strings.Contains(err.Error(), "entry limit") {
		t.Fatal("entry bomb", err)
	}
	// A compressed zero suffix can consume only the remaining shared expanded
	// allowance, even though it has no additional declared tar entries/files.
	data = fixtureArchive(t, "tar.gz", entries[:1])
	var extra bytes.Buffer
	gz := gzip.NewWriter(&extra)
	for i := 0; i < 64; i++ {
		if _, err := gz.Write(make([]byte, 32<<10)); err != nil {
			t.Fatal(err)
		}
	}
	if err := gz.Close(); err != nil {
		t.Fatal(err)
	}
	data = append(data, extra.Bytes()...)
	budget := &extractionBudget{expanded: maxExpandedBytes - (1 << 20)}
	err = scanNpmTar(context.Background(), bytes.NewReader(data), "node_modules/fixture", runtimePackage{Version: "1.0.2"}, map[string]InstalledFile{}, budget)
	if err == nil || !strings.Contains(err.Error(), "expanded byte limit") {
		t.Fatal("expanded compression bomb", err)
	}
}
