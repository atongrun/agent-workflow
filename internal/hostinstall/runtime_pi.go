package hostinstall

import (
	"archive/tar"
	"bufio"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha1"
	"crypto/sha256"
	"crypto/sha512"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

const maxRuntimeEntries = 32768
const maxNpmTarballBytes int64 = 64 << 20
const maxNpmCompressedBytes int64 = 256 << 20
const piReleaseDir = "opt/pi-cli/releases/1.0.2"

// RuntimeInput contains a caller-reviewed supplementary public metadata pin set
// and a private npm cache. It grants no network, script or system-write authority.
type RuntimeInput struct {
	CacheDirectory string
	Supplemental   []RegistryMetadata
}
type PiRuntimeReceipt struct {
	ArchiveEntries          int    `json:"archiveEntries"`
	ExpandedBytes           int64  `json:"expandedBytes"`
	ArchiveEntryLimit       int    `json:"archiveEntryLimit"`
	ExpandedByteLimit       int64  `json:"expandedByteLimit"`
	OwnerUID                int    `json:"ownerUid"`
	Ownership               string `json:"ownership"`
	InputSHA256             string `json:"inputSHA256"`
	LockedPackages          int    `json:"lockedPackages"`
	InstalledPackages       int    `json:"installedPackages"`
	SkippedPlatformOptional int    `json:"skippedPlatformOptional"`
	LifecycleScriptsRun     bool   `json:"lifecycleScriptsRun"`
	UpdaterContract         string `json:"updaterContract"`
	NativeAcceptance        bool   `json:"nativeAcceptance"`
}
type runtimeLock struct {
	Name            string                    `json:"name"`
	Version         string                    `json:"version"`
	LockfileVersion int                       `json:"lockfileVersion"`
	Packages        map[string]runtimePackage `json:"packages"`
}
type runtimePackage struct {
	Version   string   `json:"version"`
	Resolved  string   `json:"resolved"`
	Integrity string   `json:"integrity"`
	OS        []string `json:"os"`
	CPU       []string `json:"cpu"`
	Optional  bool     `json:"optional"`
}
type piRuntimePlan struct {
	receipt   PiRuntimeReceipt
	pkg, lock []byte
	selected  map[string]runtimePackage
	expected  map[string]InstalledFile
}

func runtimeInputDigest(in RuntimeInput) string {
	var pins []string
	for _, p := range in.Supplemental {
		pins = append(pins, p.SHA256)
	}
	sort.Strings(pins)
	b, _ := json.Marshal(pins)
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:])
}
func runtimePlatform(values []string, value string) bool {
	if len(values) == 0 {
		return true
	}
	allowed := true
	for _, v := range values {
		if !strings.HasPrefix(v, "!") {
			allowed = false
		}
	}
	for _, v := range values {
		if v == "!"+value {
			return false
		}
		if v == value || v == "any" {
			allowed = true
		}
	}
	return allowed
}
func pinHash(data []byte, expected string) bool {
	s := sha256.Sum256(data)
	return hex.EncodeToString(s[:]) == expected
}

func planPiRuntime(ctx context.Context, stage string, in RuntimeInput, budget *extractionBudget) (*piRuntimePlan, error) {
	bad := errors.New("fixed Pi runtime inputs or cache are invalid")
	if validateSandbox(in.CacheDirectory) != nil {
		return nil, bad
	}
	cache, err := os.OpenRoot(in.CacheDirectory)
	if err != nil {
		return nil, bad
	}
	defer cache.Close()
	info, err := cache.Stat(".")
	if err != nil || requireFixtureOwner(info) != nil {
		return nil, bad
	}
	pkg, err := os.ReadFile(filepath.Join(stage, "pi/package.json"))
	if err != nil {
		return nil, bad
	}
	lock, err := os.ReadFile(filepath.Join(stage, "pi/package-lock.json"))
	if err != nil {
		return nil, bad
	}
	if !pinHash(pkg, "491cb1ec4fba98d9547b037cd9dea48ae0bba651a0a80d67dd1660705b60f1c5") || !pinHash(lock, "b8e9e6a191bcf1e6e3ff8dafe5c0c9042b48e0087cd6d6816dcaa051222ba680") {
		return nil, bad
	}
	r, err := InspectPiMetadata(pkg, lock, in.Supplemental)
	if err != nil || !r.LockedCatalogComplete || r.Supplemented != 8 {
		return nil, bad
	}
	var l runtimeLock
	if json.Unmarshal(lock, &l) != nil {
		return nil, bad
	}
	supp := map[string]string{}
	for _, e := range in.Supplemental {
		var v struct {
			Dist struct{ Tarball, Integrity string } `json:"dist"`
		}
		if json.Unmarshal(e.Data, &v) != nil {
			return nil, bad
		}
		supp[v.Dist.Tarball] = v.Dist.Integrity
	}
	p := &piRuntimePlan{pkg: pkg, lock: lock, selected: map[string]runtimePackage{}, expected: map[string]InstalledFile{}, receipt: PiRuntimeReceipt{OwnerUID: os.Getuid(), Ownership: "private-same-uid-fixture; native programs must be administrator-owned and service-read-only", InputSHA256: runtimeInputDigest(in), LockedPackages: r.LockedPackages, UpdaterContract: "official managed releases-v1 route; actual network upgrade not accepted"}}
	for name, v := range l.Packages {
		if name == "" {
			continue
		}
		if !runtimePlatform(v.OS, "linux") || !runtimePlatform(v.CPU, "x64") {
			if !v.Optional {
				return nil, bad
			}
			p.receipt.SkippedPlatformOptional++
			continue
		}
		if v.Integrity == "" {
			v.Integrity = supp[v.Resolved]
		}
		if !sha512Integrity(v.Integrity) {
			return nil, bad
		}
		p.selected[name] = v
	}
	if r.LockedPackages != 147 || len(p.selected) != 122 || p.receipt.SkippedPlatformOptional != 25 {
		return nil, bad
	}
	if err := verifyRuntimeCacheIndex(cache, p.selected); err != nil {
		return nil, err
	}
	var compressed int64
	var names []string
	for name := range p.selected {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		v := p.selected[name]
		digest, _ := base64.StdEncoding.DecodeString(strings.TrimPrefix(v.Integrity, "sha512-"))
		h := hex.EncodeToString(digest)
		file := "_cacache/content-v2/sha512/" + h[:2] + "/" + h[2:4] + "/" + h[4:]
		info, err := cache.Lstat(file)
		if err != nil || !info.Mode().IsRegular() || info.Size() > maxNpmTarballBytes || requireFixtureOwner(info) != nil {
			return nil, bad
		}
		compressed += info.Size()
		if compressed > maxNpmCompressedBytes {
			return nil, bad
		}
		f, err := cache.Open(file)
		if err != nil {
			return nil, bad
		}
		hash := sha512.New()
		n, e := io.Copy(hash, contextReader{ctx, io.LimitReader(f, maxNpmTarballBytes+1)})
		f.Close()
		if e != nil || n != info.Size() || !bytes.Equal(hash.Sum(nil), digest) {
			return nil, bad
		}
		f, err = cache.Open(file)
		if err != nil {
			return nil, bad
		}
		e = scanNpmTar(ctx, f, name, v, p.expected, budget)
		f.Close()
		if e != nil {
			return nil, e
		}
	}
	p.receipt.InstalledPackages = len(p.selected)
	return p, nil
}

func verifyRuntimeCacheIndex(root *os.Root, packages map[string]runtimePackage) error {
	want := map[string]string{}
	for _, p := range packages {
		want[p.Resolved] = p.Integrity
	}
	seen := map[string]bool{}
	var total int64
	count := 0
	err := fs.WalkDir(root.FS(), "_cacache/index-v5", func(name string, entry fs.DirEntry, e error) error {
		if e != nil {
			return e
		}
		count++
		if count > 4096 {
			return errors.New("cache index entry limit")
		}
		info, e := root.Lstat(name)
		if e != nil || requireFixtureOwner(info) != nil {
			return errors.New("cache ownership")
		}
		if info.IsDir() {
			return nil
		}
		if !info.Mode().IsRegular() {
			return errors.New("cache index links or special files")
		}
		total += info.Size()
		if total > 4<<20 {
			return errors.New("cache index byte limit")
		}
		f, e := root.Open(name)
		if e != nil {
			return e
		}
		defer f.Close()
		scanner := bufio.NewScanner(f)
		for scanner.Scan() {
			line := scanner.Text()
			if line == "" {
				continue
			}
			pieces := strings.SplitN(line, "\t", 2)
			if len(pieces) != 2 {
				return errors.New("cache index format")
			}
			sum := sha1.Sum([]byte(pieces[1]))
			if hex.EncodeToString(sum[:]) != pieces[0] {
				return errors.New("cache index digest")
			}
			var v struct{ Key, Integrity string }
			if json.Unmarshal([]byte(pieces[1]), &v) != nil {
				return errors.New("cache index JSON")
			}
			url := strings.TrimPrefix(v.Key, "make-fetch-happen:request-cache:")
			if expected, ok := want[url]; ok {
				if v.Integrity != expected {
					return errors.New("cache URL integrity differs from reviewed pin")
				}
				seen[url] = true
			}
		}
		return scanner.Err()
	})
	if err != nil {
		return err
	}
	if len(seen) != len(want) {
		return errors.New("cache missing URL-bound reviewed tarballs")
	}
	return nil
}

func npmPAX(h *tar.Header) bool {
	total := 0
	if len(h.PAXRecords) > 64 {
		return false
	}
	for k, v := range h.PAXRecords {
		total += len(k) + len(v)
		if len(v) > 4096 || total > 32<<10 {
			return false
		}
		switch k {
		case "path":
			if v != h.Name {
				return false
			}
		case "size":
			n, e := strconv.ParseInt(v, 10, 64)
			if e != nil || n != h.Size {
				return false
			}
		case "uid", "gid", "SCHILY.dev", "SCHILY.nlink", "SCHILY.ino":
			if _, e := strconv.ParseUint(v, 10, 64); e != nil {
				return false
			}
		default:
			if !strings.HasPrefix(k, "NODETAR.") {
				return false
			}
		}
	}
	return true
}

var npmBinName = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`)

func scanNpmTar(ctx context.Context, raw io.Reader, location string, locked runtimePackage, expected map[string]InstalledFile, budget *extractionBudget) error {
	gz, e := gzip.NewReader(contextReader{ctx, raw})
	if e != nil {
		return e
	}
	defer gz.Close()
	if budget.expanded >= maxExpandedBytes {
		return errors.New("runtime expanded byte limit")
	}
	limited := &io.LimitedReader{R: contextReader{ctx, gz}, N: maxExpandedBytes - budget.expanded + 1}
	initial := limited.N
	tr := tar.NewReader(limited)
	seen := map[string]bool{}
	rawNames := map[string]string{}
	prefix := "package"
	// These two historical DefinitelyTyped tarballs use the audited legacy root,
	// while all other selected packages use the standard npm package/ root.
	if location == "node_modules/@types/node" && locked.Version == "22.19.19" {
		prefix = "node v22.19"
	}
	if location == "node_modules/p-retry/node_modules/@types/retry" && locked.Version == "0.12.0" {
		prefix = "retry"
	}
	var metadata []byte
	for {
		h, e := tr.Next()
		if e == io.EOF {
			break
		}
		if e != nil {
			return e
		}
		budget.entries++
		if budget.entries > maxRuntimeEntries {
			return errors.New("runtime archive entry limit")
		}
		canonical := *h
		// Two fixed official proxy packages retain /./ segments in their tar names.
		// Normalize only that inert segment for these versions; traversal and alias
		// collisions are still refused before constructing any file inventory.
		proxyAlias := location == "node_modules/agent-base" && locked.Version == "7.1.4" || location == "node_modules/https-proxy-agent" && locked.Version == "7.0.6"
		if proxyAlias && h.Name == "package/./dist/index.js" {
			canonical.Name = "package/dist/index.js"
		}
		name, e := canonicalArchiveName(&canonical)
		aliasDuplicate := proxyAlias && name == "package/dist/index.js" && h.Name == "package/dist/index.js" && rawNames[name] == "package/./dist/index.js" && h.Typeflag == tar.TypeReg
		if e != nil || seen[name] && !aliasDuplicate || !(name == prefix || strings.HasPrefix(name, prefix+"/")) || h.Size < 0 || h.Size > maxNpmTarballBytes || h.Mode&07000 != 0 || !npmPAX(h) {
			return errors.New("invalid npm archive entry")
		}
		seen[name] = true
		rawNames[name] = h.Name
		if h.Typeflag == tar.TypeDir {
			if h.Size != 0 {
				return errors.New("invalid npm directory")
			}
			continue
		}
		if h.Typeflag != tar.TypeReg && h.Typeflag != tar.TypeRegA || name == prefix {
			return errors.New("npm archive link or special file")
		}
		target := path.Join(piReleaseDir, location, strings.TrimPrefix(name, prefix+"/"))
		if _, exists := expected[target]; exists && !aliasDuplicate {
			return errors.New("overlapping npm package files")
		}
		hash := sha256.New()
		var capture bytes.Buffer
		var out io.Writer = hash
		if name == prefix+"/package.json" {
			if h.Size > 4<<20 {
				return errors.New("package metadata limit")
			}
			out = io.MultiWriter(hash, &capture)
		}
		n, e := io.Copy(out, tr)
		if e != nil || n != h.Size {
			return errors.New("npm archive file length")
		}
		mode := uint32(0644)
		if h.Mode&0111 != 0 {
			mode = 0755
		}
		candidate := InstalledFile{Path: target, SHA256: hex.EncodeToString(hash.Sum(nil)), Bytes: n, Mode: mode}
		// The two audited proxy archives repeat this file with an inert /./ alias.
		// Accept only the known pair and identical bytes/mode/size; never last-wins.
		if aliasDuplicate && expected[target] != candidate {
			return errors.New("npm alias bytes differ")
		}
		expected[target] = candidate
		if capture.Len() > 0 {
			metadata = append([]byte(nil), capture.Bytes()...)
		}
	}
	padding := make([]byte, 32<<10)
	for {
		n, e := limited.Read(padding)
		for _, b := range padding[:n] {
			if b != 0 {
				return errors.New("hidden npm tar payload")
			}
		}
		if e == io.EOF {
			break
		}
		if e != nil {
			return e
		}
		if limited.N == 0 {
			return errors.New("runtime expanded byte limit")
		}
	}
	if limited.N == 0 || initial-limited.N > maxExpandedBytes-budget.expanded {
		return errors.New("runtime expanded byte limit")
	}
	budget.expanded += initial - limited.N
	var p struct {
		Name, Version string
		Bin           json.RawMessage
	}
	if boundedPiJSON(metadata, &p) != nil || p.Version != locked.Version {
		return errors.New("npm package identity")
	}
	idx := strings.LastIndex(location, "node_modules/")
	if idx < 0 || p.Name != location[idx+len("node_modules/"):] {
		return errors.New("npm package name differs from lock")
	}
	if len(p.Bin) == 0 {
		return nil
	}
	bins := map[string]string{}
	if json.Unmarshal(p.Bin, &bins) != nil {
		var value string
		if json.Unmarshal(p.Bin, &value) != nil {
			return errors.New("invalid npm bins")
		}
		bins[path.Base(p.Name)] = value
	}
	for command, value := range bins {
		value = strings.TrimPrefix(value, "./")
		if !npmBinName.MatchString(command) || value == "" || strings.HasPrefix(value, "/") || path.Clean(value) != value || strings.HasPrefix(value, "../") || strings.ContainsAny(value, "\\\x00\r\n") {
			return errors.New("unsafe npm bin declaration")
		}
		target := path.Join(piReleaseDir, location, value)
		file, ok := expected[target]
		if !ok || file.LinkTarget != "" {
			return errors.New("npm bin target missing")
		}
		file.Mode = 0755
		expected[target] = file
		bin := path.Join(piReleaseDir, location[:idx], "node_modules/.bin", command)
		if _, exists := expected[bin]; exists {
			return errors.New("colliding npm bins")
		}
		relative, e := filepath.Rel(path.Dir(bin), target)
		if e != nil {
			return e
		}
		expected[bin] = InstalledFile{Path: bin, Mode: 0777, LinkTarget: filepath.ToSlash(relative)}
	}
	return nil
}

func preparePiRuntime(ctx context.Context, dest *os.Root, in RuntimeInput, plan *piRuntimePlan, o Observer) ([]InstalledFile, error) {
	for name, data := range map[string][]byte{"package.json": plan.pkg, "package-lock.json": plan.lock} {
		if _, err := writeSelected(ctx, dest, path.Join(piReleaseDir, name), bytes.NewReader(data), int64(len(data)), 0644); err != nil {
			return nil, err
		}
	}
	config, err := os.MkdirTemp(dest.Name(), ".npm-config-")
	if err != nil {
		return nil, err
	}
	defer os.RemoveAll(config)
	for _, name := range []string{"user.npmrc", "global.npmrc"} {
		if err := os.WriteFile(filepath.Join(config, name), nil, 0600); err != nil {
			return nil, err
		}
	}
	node := path.Join(dest.Name(), "opt/node/bin/node")
	data, err := os.ReadFile(node)
	if err != nil || !pinHash(data, "596b5144ff242737f1c1be6a5f0ccb3907dbba2482344143cb1a6898633402a9") {
		return nil, errors.New("audited Node executable required")
	}
	childCtx, cancel := context.WithTimeout(ctx, 2*time.Minute)
	defer cancel()
	cmd := exec.CommandContext(childCtx, node, path.Join(dest.Name(), "opt/node/lib/node_modules/npm/bin/npm-cli.js"), "ci", "--offline", "--ignore-scripts", "--min-release-age=0", "--omit=dev", "--include=optional", "--no-fund", "--no-audit", "--loglevel=error", "--progress=false")
	cmd.Dir = path.Join(dest.Name(), piReleaseDir)
	cmd.Env = []string{"PATH=" + path.Dir(node) + ":/usr/bin:/bin", "npm_config_cache=" + in.CacheDirectory, "npm_config_userconfig=" + filepath.Join(config, "user.npmrc"), "npm_config_globalconfig=" + filepath.Join(config, "global.npmrc"), "npm_config_prefix=" + cmd.Dir, "npm_config_logs_dir=" + config, "npm_config_registry=https://registry.npmjs.org", "npm_config_global=false", "PI_CODING_AGENT_DIR=" + filepath.Join(config, "agent")}
	configureRuntimeCommand(cmd)
	cmd.Stdout = io.Discard
	cmd.Stderr = io.Discard
	o.Event(ProgressEvent{Component: "pi", Stage: "npm-ci-offline", State: "started"})
	if err := cmd.Run(); err != nil {
		return nil, errors.New("official offline npm ci failed; no runtime selected")
	}
	o.Event(ProgressEvent{Component: "pi", Stage: "npm-ci-offline", State: "completed"})
	if err := verifyNpmInstalled(dest, plan); err != nil {
		return nil, err
	}
	var files []InstalledFile
	for _, f := range plan.expected {
		files = append(files, f)
	}
	for _, name := range []string{"package.json", "package-lock.json", "node_modules/.package-lock.json"} {
		target := path.Join(piReleaseDir, name)
		f, e := dest.Open(target)
		if e != nil {
			return nil, e
		}
		hash := sha256.New()
		n, e := io.Copy(hash, f)
		f.Close()
		if e != nil {
			return nil, e
		}
		files = append(files, InstalledFile{Path: target, SHA256: hex.EncodeToString(hash.Sum(nil)), Bytes: n, Mode: 0644})
	}
	for name, data := range map[string][]byte{"opt/pi-cli/managed-install.json": []byte(`{"kind":"pi-managed-install","schemaVersion":1,"layout":"releases-v1"}`), "opt/pi-cli/current-version": []byte("1.0.2\n"), "opt/pi-cli/bin/pi": []byte(sharedPiLauncher)} {
		mode := uint32(0644)
		if name == "opt/pi-cli/bin/pi" {
			mode = 0755
		}
		f, e := writeSelected(ctx, dest, name, bytes.NewReader(data), int64(len(data)), mode)
		if e != nil {
			return nil, e
		}
		files = append(files, f)
	}
	sort.Slice(files, func(i, j int) bool { return files[i].Path < files[j].Path })
	return files, nil
}

func verifyPiRootMetadata(root *os.Root, plan *piRuntimePlan) error {
	for name, want := range map[string][]byte{"package.json": plan.pkg, "package-lock.json": plan.lock} {
		target := path.Join(piReleaseDir, name)
		info, err := root.Lstat(target)
		if err != nil || !info.Mode().IsRegular() || info.Size() != int64(len(want)) || requireFixtureOwner(info) != nil {
			return errors.New("official Pi root metadata changed")
		}
		f, err := root.Open(target)
		if err != nil {
			return err
		}
		data, err := io.ReadAll(io.LimitReader(f, int64(len(want))+1))
		f.Close()
		if err != nil || !bytes.Equal(data, want) {
			return errors.New("official Pi root metadata changed")
		}
	}
	return nil
}
func verifyNpmInstalled(root *os.Root, plan *piRuntimePlan) error {
	if err := verifyPiRootMetadata(root, plan); err != nil {
		return err
	}
	meta := path.Join(piReleaseDir, "node_modules/.package-lock.json")
	f, e := root.Open(meta)
	if e != nil {
		return e
	}
	data, e := io.ReadAll(io.LimitReader(f, (4<<20)+1))
	f.Close()
	var hidden runtimeLock
	if e != nil || boundedPiJSON(data, &hidden) != nil || hidden.Name != "@earendil-works/pi-coding-agent-install" || hidden.Version != "1.0.2" || hidden.LockfileVersion != 3 || len(hidden.Packages) != len(plan.selected) {
		return errors.New("generated npm lock identity")
	}
	for name, v := range hidden.Packages {
		want, ok := plan.selected[name]
		if !ok || v.Version != want.Version || v.Resolved != want.Resolved || v.Integrity != "" && v.Integrity != want.Integrity {
			return errors.New("generated npm lock differs")
		}
	}
	seen := map[string]bool{}
	count := 0
	err := fs.WalkDir(root.FS(), path.Join(piReleaseDir, "node_modules"), func(name string, entry fs.DirEntry, e error) error {
		if e != nil {
			return e
		}
		count++
		if count > maxRuntimeEntries {
			return errors.New("installed runtime entry limit")
		}
		info, e := root.Lstat(name)
		if e != nil || requireFixtureOwner(info) != nil {
			return errors.New("installed runtime ownership")
		}
		if info.IsDir() {
			dir, e := root.Open(name)
			if e != nil {
				return e
			}
			defer dir.Close()
			return dir.Chmod(0700)
		}
		if name == meta {
			if !info.Mode().IsRegular() {
				return errors.New("linked hidden lock")
			}
			f, e := root.Open(name)
			if e != nil {
				return e
			}
			defer f.Close()
			return f.Chmod(0644)
		}
		want, ok := plan.expected[name]
		if !ok {
			return errors.New("unexpected installed npm file")
		}
		seen[name] = true
		if want.LinkTarget != "" {
			if info.Mode()&os.ModeSymlink == 0 {
				return errors.New("npm bin must be exact declared link")
			}
			target, e := os.Readlink(path.Join(root.Name(), name))
			if e != nil || target != want.LinkTarget {
				return errors.New("npm bin link mismatch")
			}
			return nil
		}
		if !info.Mode().IsRegular() || info.Mode()&os.ModeSetuid != 0 || info.Mode()&os.ModeSetgid != 0 || info.Size() != want.Bytes {
			return errors.New("npm file type or length mismatch")
		}
		f, e := root.Open(name)
		if e != nil {
			return e
		}
		defer f.Close()
		hash := sha256.New()
		n, e := io.Copy(hash, io.LimitReader(f, want.Bytes+1))
		if e != nil || n != want.Bytes || hex.EncodeToString(hash.Sum(nil)) != want.SHA256 {
			return errors.New("installed npm bytes differ from pinned tarball")
		}
		return f.Chmod(os.FileMode(want.Mode))
	})
	if err != nil {
		return err
	}
	if len(seen) != len(plan.expected) {
		return errors.New("missing installed npm files")
	}
	return nil
}

// Equivalent shared launcher, not a copy of the inaccessible initial installer.
// execve preserves PID/stdin/stdout and avoids an orphaned launcher child.
const sharedPiLauncher = `#!/opt/node/bin/node
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const marker=JSON.parse(fs.readFileSync(path.join(root,"managed-install.json"),"utf8"));
if(marker.kind!=="pi-managed-install"||marker.schemaVersion!==1||marker.layout!=="releases-v1")throw new Error("Invalid managed Pi installation");
const version=fs.readFileSync(path.join(root,"current-version"),"utf8").trim();
if(!/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/.test(version))throw new Error("Invalid managed Pi selector");
const node=path.join(path.dirname(root),"node/bin/node");
const cli=path.join(root,"releases",version,"node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js");
const env={...process.env,PI_MANAGED_INSTALL_ROOT:root,PATH:path.dirname(node)+":"+(process.env.PATH||"/usr/bin:/bin")};
delete env.PI_INSTALLER_API_BASE;
if(typeof process.execve!=="function")throw new Error("Pinned Node execve support required");
process.execve(node,[node,cli,...process.argv.slice(2)],env);
`

// Executable preparation is narrower than the metadata/staging matrix: these
// are the exact official bytes whose npm behavior was locally accepted.
func auditedRuntimeManifest(m Manifest) bool {
	if m.Arch != "amd64" {
		return false
	}
	for _, c := range m.Components {
		switch c.ID {
		case "node":
			if c.Version != "v22.19.0" || len(c.Artifacts) != 1 || c.Artifacts[0].Bytes != 54907188 || c.Artifacts[0].SHA256 != "d36e56998220085782c0ca965f9d51b7726335aed2f5fc7321c6c0ad233aa96d" {
				return false
			}
		case "pi":
			for _, a := range c.Artifacts {
				if a.Name == "package.json" {
					if a.Bytes != 317 || a.SHA256 != "491cb1ec4fba98d9547b037cd9dea48ae0bba651a0a80d67dd1660705b60f1c5" {
						return false
					}
				} else if a.Name == "package-lock.json" {
					if a.Bytes != 63566 || a.SHA256 != "b8e9e6a191bcf1e6e3ff8dafe5c0c9042b48e0087cd6d6816dcaa051222ba680" {
						return false
					}
				} else {
					return false
				}
			}
		}
	}
	return true
}
