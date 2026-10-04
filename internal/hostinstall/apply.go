package hostinstall

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
)

type AppliedComponent struct {
	ID           string          `json:"id"`
	Version      string          `json:"version"`
	State        string          `json:"state"`
	RuntimeReady bool            `json:"runtimeReady"`
	Reason       string          `json:"reason"`
	Files        []InstalledFile `json:"files"`
}
type InstallReceipt struct {
	Schema               int                `json:"schema"`
	Mode                 string             `json:"mode"`
	ManifestSHA256       string             `json:"manifestSHA256"`
	SourceCommit         string             `json:"sourceCommit"`
	OS                   string             `json:"os"`
	Arch                 string             `json:"arch"`
	FilesPrepared        bool               `json:"filesPrepared"`
	InstallationComplete bool               `json:"installationComplete"`
	Components           []AppliedComponent `json:"components"`
	PiProgramRoot        string             `json:"piProgramRoot"`
	ServicePiAgent       string             `json:"servicePiAgent"`
}
type fixtureSelection struct {
	Schema        int    `json:"schema"`
	Mode          string `json:"mode"`
	Generation    string `json:"generation"`
	ReceiptSHA256 string `json:"receiptSHA256"`
}

// ApplyFixture is deliberately internal and Linux-only, accepts only private
// sandboxes beneath real /tmp, and never executes installed files. It cannot
// install to the real program/config/service roots. No public CLI calls it.
func ApplyFixture(ctx context.Context, m Manifest, stage, sandbox string, o Observer) (receipt InstallReceipt, err error) {
	if runtime.GOOS != "linux" || m.Arch != "amd64" {
		return receipt, errors.New("fixture apply requires Linux amd64")
	}
	if err = m.Validate(); err != nil {
		return receipt, err
	}
	if nilObserver(o) {
		return receipt, errors.New("fixture apply requires progress")
	}
	if p, ok := o.(*Progress); ok && p.Out == nil {
		return receipt, errors.New("fixture progress has no output")
	}
	defer func() {
		if e, ok := err.(*StageError); ok {
			o.Event(ProgressEvent{Component: e.Component, Stage: e.Stage, State: "failed"})
		}
	}()
	if err = validateSandbox(sandbox); err != nil {
		return receipt, err
	}
	root, err := os.OpenRoot(sandbox)
	if err != nil {
		return receipt, errors.New("sandbox unavailable")
	}
	defer root.Close()
	lock, err := fixtureLock(root)
	if err != nil {
		return receipt, &StageError{"bundle", "activate", "another fixture apply is running or lock is invalid"}
	}
	defer lock.Close()
	if ctx.Err() != nil {
		return receipt, &StageError{"bundle", "verify", "fixture apply cancelled"}
	}
	encoded, _ := json.Marshal(m)
	sum := sha256.Sum256(encoded)
	digest := hex.EncodeToString(sum[:])
	generation := "layout-1-" + digest
	if err = checkSandboxTopology(root, generation); err != nil {
		return receipt, &StageError{"bundle", "verify", "sandbox state requires explicit inspection"}
	}
	o.Event(ProgressEvent{Component: "bundle", Stage: "verify", State: "started"})
	if err = verifyStage(stage, m, digest); err != nil {
		return receipt, &StageError{"bundle", "verify", "stage verification failed"}
	}
	o.Event(ProgressEvent{Component: "bundle", Stage: "verify", State: "completed"})
	work, err := os.MkdirTemp(sandbox, ".fixture-apply-")
	if err != nil {
		return receipt, &StageError{"bundle", "extract", "private extraction directory unavailable"}
	}
	defer os.RemoveAll(work)
	dest, err := os.OpenRoot(work)
	if err != nil {
		return receipt, &StageError{"bundle", "extract", "private extraction directory unavailable"}
	}
	defer dest.Close()
	receipt = InstallReceipt{Schema: 1, Mode: "sandbox-fixture", ManifestSHA256: digest, SourceCommit: m.SourceCommit, OS: m.OS, Arch: m.Arch, FilesPrepared: true, InstallationComplete: false, PiProgramRoot: "/opt/pi-cli", ServicePiAgent: "/var/lib/awf/pi-agent"}
	budget := &extractionBudget{}
	// Fixed order makes receipts independent of manifest component order.
	for _, id := range componentOrder {
		var c Component
		for _, item := range m.Components {
			if item.ID == id {
				c = item
				break
			}
		}
		item := AppliedComponent{ID: id, Version: c.Version, State: "files_prepared", Reason: "fixture files only; native runtime acceptance not performed", Files: []InstalledFile{}}
		if id == "pi" {
			item.State = "unavailable"
			item.Reason = "official installer metadata only; verified Pi dependency closure is unavailable"
			receipt.Components = append(receipt.Components, item)
			o.Event(ProgressEvent{Component: id, Stage: "extract", State: "unavailable"})
			continue
		}
		o.Event(ProgressEvent{Component: id, Stage: "extract", State: "started"})
		if id == "magpie" {
			a := c.Artifacts[0]
			f, e := os.Open(filepath.Join(stage, id, a.Name))
			if e != nil {
				return receipt, &StageError{id, "extract", "staged payload unavailable"}
			}
			file, e := writeSelected(ctx, dest, "opt/magpie/magpie", f, a.Bytes, 0755)
			f.Close()
			if e != nil || file.SHA256 != a.SHA256 || verifyFormat(filepath.Join(work, file.Path), Artifact{Format: "elf"}, m.Arch) != nil {
				return receipt, &StageError{id, "extract", "payload copy, digest or architecture verification failed"}
			}
			item.Files = []InstalledFile{file}
		} else {
			item.Files, err = extractArchive(ctx, m, c, filepath.Join(stage, id, c.Artifacts[0].Name), dest, budget, o)
			if err != nil {
				return receipt, &StageError{id, "extract", "archive, identity, digest or architecture verification failed"}
			}
		}
		if id == "awf-extension" {
			item.State = "files_prepared_runtime_unavailable"
			item.Reason = "extension files only; bundled dependency resolution and Pi runtime are unavailable"
		}
		receipt.Components = append(receipt.Components, item)
		o.Event(ProgressEvent{Component: id, Stage: "extract", State: "completed"})
	}
	if ctx.Err() != nil {
		return receipt, &StageError{"bundle", "activate", "fixture apply cancelled"}
	}
	receiptBytes, _ := json.Marshal(receipt)
	if err = writeSynced(dest, "install.json", receiptBytes); err != nil {
		return receipt, &StageError{"bundle", "activate", "fixture receipt could not be prepared"}
	}
	if err = syncTreeDirectories(work); err != nil {
		return receipt, &StageError{"bundle", "activate", "fixture generation could not be synchronized"}
	}
	if err = verifyGeneration(work, receipt, receiptBytes); err != nil {
		return receipt, &StageError{"bundle", "verify", "prepared generation is invalid"}
	}
	if err = root.Mkdir("releases", 0700); err != nil && !os.IsExist(err) {
		return receipt, &StageError{"bundle", "activate", "release directory unavailable"}
	}
	final := filepath.Join(sandbox, "releases", generation)
	if _, err = os.Lstat(final); err == nil {
		if err = verifyGeneration(final, receipt, receiptBytes); err != nil {
			return receipt, &StageError{"bundle", "verify", "existing generation differs; explicit inspection required"}
		}
	} else if os.IsNotExist(err) {
		if ctx.Err() != nil {
			return receipt, &StageError{"bundle", "activate", "fixture apply cancelled"}
		}
		if err = os.Rename(work, final); err != nil {
			return receipt, &StageError{"bundle", "activate", "fixture generation could not be prepared"}
		}
		if err = syncDirectory(filepath.Join(sandbox, "releases")); err != nil {
			return receipt, &StageError{"bundle", "activate", "prepared generation requires inspection"}
		}
	} else {
		return receipt, &StageError{"bundle", "activate", "generation is unreadable"}
	}
	receiptSum := sha256.Sum256(receiptBytes)
	selection := fixtureSelection{1, "sandbox-fixture", generation, hex.EncodeToString(receiptSum[:])}
	if _, err = root.Lstat("current.json"); err == nil {
		var current fixtureSelection
		if readIdentity(root, "current.json", &current) != nil || current != selection {
			return receipt, &StageError{"bundle", "activate", "existing selection differs; updates are unsupported"}
		}
	} else if !os.IsNotExist(err) {
		return receipt, &StageError{"bundle", "activate", "selection is unreadable"}
	}
	o.Event(ProgressEvent{Component: "bundle", Stage: "activate", State: "started"})
	if ctx.Err() != nil {
		return receipt, &StageError{"bundle", "activate", "fixture apply cancelled"}
	}
	data, _ := json.Marshal(selection)
	if err = replaceSelection(ctx, sandbox, data); err != nil {
		return receipt, &StageError{"bundle", "activate", "selection outcome requires inspection"}
	}
	o.Event(ProgressEvent{Component: "bundle", Stage: "activate", State: "completed"})
	return receipt, nil
}

func validateSandbox(name string) error {
	bad := errors.New("fixture sandbox must be an existing private real directory beneath /tmp")
	if !filepath.IsAbs(name) || filepath.Clean(name) != name || !strings.HasPrefix(name, "/tmp/") {
		return bad
	}
	for current := name; ; current = filepath.Dir(current) {
		info, err := os.Lstat(current)
		if err != nil || !info.IsDir() {
			return bad
		}
		if current == name && info.Mode().Perm()&0077 != 0 {
			return bad
		}
		if current == "/" {
			break
		}
	}
	return nil
}
func checkSandboxTopology(root *os.Root, generation string) error {
	entries, err := fs.ReadDir(root.FS(), ".")
	if err != nil {
		return err
	}
	for _, entry := range entries {
		name := entry.Name()
		info, err := root.Lstat(name)
		if err != nil {
			return err
		}
		if info.Mode()&os.ModeSymlink != 0 {
			return errors.New("linked sandbox entry")
		}
		switch name {
		case ".apply.lock", "current.json":
			if !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 {
				return errors.New("invalid control file")
			}
		case "releases":
			if !info.IsDir() || info.Mode().Perm()&0077 != 0 {
				return errors.New("invalid release directory")
			}
		default:
			if strings.HasPrefix(name, ".fixture-apply-selection-") && info.Mode().IsRegular() && info.Mode().Perm() == 0600 && info.Size() <= 4096 {
				continue // a crashed partial selector is never adopted
			}
			// Interrupted temporary trees are never adopted or followed. They can be
			// inspected/removed separately; successful retries create a fresh tree.
			if !strings.HasPrefix(name, ".fixture-apply-") || !info.IsDir() || info.Mode().Perm()&0077 != 0 {
				return errors.New("unexpected sandbox entry")
			}
		}
	}
	if info, err := root.Lstat("current.json"); err == nil {
		if info.Size() > 4096 {
			return errors.New("oversized selection")
		}
		var current fixtureSelection
		if readIdentity(root, "current.json", &current) != nil || current.Schema != 1 || current.Mode != "sandbox-fixture" || current.Generation != generation || !digestPattern.MatchString(current.ReceiptSHA256) {
			return errors.New("invalid or different selection")
		}
	}
	return nil
}
func verifyGeneration(dir string, receipt InstallReceipt, data []byte) error {
	info, err := os.Lstat(dir)
	if err != nil || !info.IsDir() || info.Mode().Perm()&0077 != 0 {
		return errors.New("invalid generation directory")
	}
	root, err := os.OpenRoot(dir)
	if err != nil {
		return err
	}
	defer root.Close()
	// Expected receipt comes from freshly extracted manifest-pinned artifacts,
	// never from the existing generation's self-reported hashes.
	existing, err := root.Open("install.json")
	if err != nil {
		return err
	}
	actual, err := io.ReadAll(io.LimitReader(existing, int64(len(data))+1))
	existing.Close()
	if err != nil || string(actual) != string(data) {
		return errors.New("generation receipt mismatch")
	}
	expected := map[string]*InstalledFile{"install.json": nil}
	dirs := map[string]bool{".": true}
	for _, component := range receipt.Components {
		for _, file := range component.Files {
			file := file
			expected[file.Path] = &file
			for parent := filepath.Dir(file.Path); parent != "."; parent = filepath.Dir(parent) {
				dirs[parent] = true
			}
		}
	}
	seen := map[string]bool{}
	err = fs.WalkDir(root.FS(), ".", func(name string, entry fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		info, err := root.Lstat(name)
		if err != nil {
			return err
		}
		if info.IsDir() {
			if !dirs[name] || info.Mode().Perm()&0077 != 0 {
				return errors.New("unexpected generation directory")
			}
			return nil
		}
		if !info.Mode().IsRegular() {
			return errors.New("linked or special generation entry")
		}
		file, ok := expected[name]
		seen[name] = true
		if !ok {
			return errors.New("unexpected generation file")
		}
		if file == nil {
			if info.Mode().Perm() != 0600 {
				return errors.New("invalid receipt permissions")
			}
			return nil
		}
		if info.Size() != file.Bytes || uint32(info.Mode().Perm()) != file.Mode {
			return errors.New("generation size or mode mismatch")
		}
		f, err := root.Open(name)
		if err != nil {
			return err
		}
		hash := sha256.New()
		_, err = io.Copy(hash, io.LimitReader(f, file.Bytes+1))
		f.Close()
		if err != nil || hex.EncodeToString(hash.Sum(nil)) != file.SHA256 {
			return errors.New("generation digest mismatch")
		}
		return nil
	})
	if err != nil {
		return err
	}
	if len(seen) != len(expected) {
		return errors.New("missing generation file")
	}
	return nil
}
func writeSynced(root *os.Root, name string, data []byte) error {
	f, err := root.OpenFile(name, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	defer f.Close()
	if _, err = f.Write(data); err != nil {
		return err
	}
	return f.Sync()
}
func syncDirectory(name string) error {
	f, err := os.Open(name)
	if err != nil {
		return err
	}
	defer f.Close()
	return f.Sync()
}
func syncTreeDirectories(dir string) error {
	var dirs []string
	if err := filepath.WalkDir(dir, func(name string, e fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if e.IsDir() {
			dirs = append(dirs, name)
		}
		return nil
	}); err != nil {
		return err
	}
	sort.Slice(dirs, func(i, j int) bool { return len(dirs[i]) > len(dirs[j]) })
	for _, name := range dirs {
		if err := syncDirectory(name); err != nil {
			return err
		}
	}
	return nil
}
func replaceSelection(ctx context.Context, sandbox string, data []byte) error {
	f, err := os.CreateTemp(sandbox, ".fixture-apply-selection-")
	if err != nil {
		return err
	}
	name := f.Name()
	defer os.Remove(name)
	if _, err = f.Write(data); err != nil {
		f.Close()
		return err
	}
	if err = f.Sync(); err != nil {
		f.Close()
		return err
	}
	if err = f.Close(); err != nil {
		return err
	}
	if ctx.Err() != nil {
		return ctx.Err()
	}
	if err = os.Rename(name, filepath.Join(sandbox, "current.json")); err != nil {
		return err
	}
	return syncDirectory(sandbox)
}
