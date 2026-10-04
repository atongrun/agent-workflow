package hostinstall

import (
	"archive/tar"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path"
	"sort"
	"strings"
)

const maxExpandedBytes int64 = 512 << 20
const maxExtractedFileBytes int64 = 256 << 20
const maxArchiveEntries = 8192

type InstalledFile struct {
	Path       string `json:"path"`
	SHA256     string `json:"sha256"`
	Bytes      int64  `json:"bytes"`
	Mode       uint32 `json:"mode"`
	LinkTarget string `json:"linkTarget,omitempty"`
}

type buildIdentity struct {
	Schema       int    `json:"schema"`
	Version      string `json:"version"`
	SourceCommit string `json:"sourceCommit"`
	OS           string `json:"os"`
	Arch         string `json:"arch"`
	HostProtocol string `json:"hostProtocol"`
}
type extensionIdentity struct {
	Schema            int    `json:"schema"`
	Version           string `json:"version"`
	SourceCommit      string `json:"sourceCommit"`
	ExtensionProtocol int    `json:"extensionProtocol"`
	PiRPCVersion      string `json:"piRPCVersion"`
}

// The default fixture selects fixed files and discards official Node command
// links. The opt-in runtime fixture prepares the full pinned Node archive.
func selectedPath(c Component, name string, m Manifest) (string, uint32) {
	switch c.ID {
	case "node":
		prefix := "node-" + c.Version + "-linux-x64/"
		switch strings.TrimPrefix(name, prefix) {
		case "bin/node":
			return "opt/node/bin/node", 0755
		case "LICENSE", "README.md", "CHANGELOG.md":
			return "opt/node/" + strings.TrimPrefix(name, prefix), 0644
		}
	case "awf-host":
		switch name {
		case "awf":
			return "opt/awf/awf", 0755
		case "build.json":
			return "opt/awf/build.json", 0644
		}
	case "awf-extension":
		switch name {
		case "awf.ts", "extension.json":
			return "opt/awf/extensions/" + name, 0644
		}
	}
	return "", 0
}
func archiveNameAllowed(c Component, name string) bool {
	switch c.ID {
	case "node":
		prefix := "node-" + c.Version + "-linux-x64"
		if name == prefix {
			return true
		}
		if !strings.HasPrefix(name, prefix+"/") {
			return false
		}
		name = strings.TrimPrefix(name, prefix+"/")
		for _, dir := range []string{"bin", "include", "lib", "share"} {
			if name == dir || strings.HasPrefix(name, dir+"/") {
				return true
			}
		}
		return name == "LICENSE" || name == "README.md" || name == "CHANGELOG.md"
	case "awf-host":
		return name == "awf" || name == "build.json"
	case "awf-extension":
		return name == "awf.ts" || name == "extension.json"
	}
	return false
}
func ignoredNodeLink(c Component, h *tar.Header) bool {
	if c.ID != "node" || h.Typeflag != tar.TypeSymlink {
		return false
	}
	prefix := "node-" + c.Version + "-linux-x64/"
	links := map[string]string{"bin/npm": "../lib/node_modules/npm/bin/npm-cli.js", "bin/npx": "../lib/node_modules/npm/bin/npx-cli.js", "bin/corepack": "../lib/node_modules/corepack/dist/corepack.js"}
	target, ok := links[strings.TrimPrefix(h.Name, prefix)]
	return ok && strings.HasPrefix(h.Name, prefix) && h.Linkname == target
}
func canonicalArchiveName(h *tar.Header) (string, error) {
	name := h.Name
	if h.Typeflag == tar.TypeDir {
		name = strings.TrimSuffix(name, "/")
	}
	if name == "" || len(name) > 512 || strings.ContainsAny(name, "\\\x00\r\n") || strings.HasPrefix(name, "/") || path.Clean(name) != name || name == "." || name == ".." || strings.HasPrefix(name, "../") {
		return "", errors.New("invalid archive path")
	}
	return name, nil
}

type contextReader struct {
	ctx context.Context
	r   io.Reader
}

func (r contextReader) Read(p []byte) (int, error) {
	if err := r.ctx.Err(); err != nil {
		return 0, err
	}
	return r.r.Read(p)
}

type extractionBudget struct {
	expanded   int64
	entries    int
	maxEntries int
}

func extractArchive(ctx context.Context, m Manifest, c Component, src string, dest *os.Root, budget *extractionBudget, o Observer) ([]InstalledFile, error) {
	return extractNodeArchive(ctx, m, c, src, dest, budget, o, false)
}
func extractNodeArchive(ctx context.Context, m Manifest, c Component, src string, dest *os.Root, budget *extractionBudget, o Observer, full bool) ([]InstalledFile, error) {
	a := c.Artifacts[0]
	f, err := os.Open(src)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	hash := sha256.New()
	raw := io.TeeReader(contextReader{ctx, io.LimitReader(f, a.Bytes+1)}, hash)
	var decoded io.Reader
	switch a.Format {
	case "tar.gz":
		gz, e := gzip.NewReader(raw)
		if e != nil {
			return nil, e
		}
		defer gz.Close()
		decoded = gz
	default:
		return nil, errors.New("unsupported archive format")
	}
	// Includes tar headers, skipped payloads and padding, not only output files.
	limited := &io.LimitedReader{R: contextReader{ctx, decoded}, N: maxExpandedBytes - budget.expanded + 1}
	initialLimit := limited.N
	tr := tar.NewReader(limited)
	seen := map[string]bool{}
	var files []InstalledFile
	var links []InstalledFile
	for {
		h, e := tr.Next()
		if e == io.EOF {
			break
		}
		if e != nil {
			return nil, e
		}
		budget.entries++
		limit := budget.maxEntries
		if limit == 0 {
			limit = maxArchiveEntries
		}
		if budget.entries > limit {
			return nil, errors.New("archive entry limit")
		}
		name, e := canonicalArchiveName(h)
		if e != nil {
			return nil, e
		}
		if seen[name] || !archiveNameAllowed(c, name) || h.Size < 0 || h.Size > maxExtractedFileBytes || h.Mode&07000 != 0 || len(h.PAXRecords) != 0 {
			return nil, errors.New("unsupported archive entry")
		}
		seen[name] = true
		switch h.Typeflag {
		case tar.TypeDir:
			if h.Size != 0 {
				return nil, errors.New("invalid directory size")
			}
			continue
		case tar.TypeSymlink:
			if !ignoredNodeLink(c, h) || h.Size != 0 {
				return nil, errors.New("archive links are refused")
			}
			if full {
				links = append(links, InstalledFile{Path: "opt/node/" + strings.TrimPrefix(name, "node-"+c.Version+"-linux-x64/"), Mode: 0777, LinkTarget: h.Linkname})
			}
			continue
		case tar.TypeReg, tar.TypeRegA:
		default:
			return nil, errors.New("special archive entries are refused")
		}
		target, mode := selectedPath(c, name, m)
		if full && c.ID == "node" {
			target = "opt/node/" + strings.TrimPrefix(name, "node-"+c.Version+"-linux-x64/")
			mode = 0644
			if h.Mode&0111 != 0 {
				mode = 0755
			}
		}
		if target == "" {
			continue
		} // bounded discarded official Node package files
		file, e := writeSelected(ctx, dest, target, tr, h.Size, mode)
		if e != nil {
			return nil, e
		}
		files = append(files, file)
		o.Event(ProgressEvent{Component: c.ID, Stage: "extract", State: "progress", Bytes: initialLimit - limited.N})
	}
	// Force compressor footer/checksum and EOF; reject hidden second tar payload.
	padding := make([]byte, 32<<10)
	for {
		n, e := limited.Read(padding)
		for _, b := range padding[:n] {
			if b != 0 {
				return nil, errors.New("trailing archive payload")
			}
		}
		if e == io.EOF {
			break
		}
		if e != nil {
			return nil, e
		}
		if limited.N == 0 {
			return nil, errors.New("expanded archive limit")
		}
	}
	consumed := initialLimit - limited.N
	if limited.N == 0 || consumed > maxExpandedBytes-budget.expanded {
		return nil, errors.New("expanded archive limit")
	}
	budget.expanded += consumed
	if hex.EncodeToString(hash.Sum(nil)) != a.SHA256 {
		return nil, errors.New("archive digest changed")
	}
	for _, link := range links {
		if err := createPinnedLink(dest, link); err != nil {
			return nil, err
		}
		files = append(files, link)
	}
	if full && c.ID == "node" {
		if len(links) != 3 {
			return nil, errors.New("complete Node command links required")
		}
		var npm struct {
			Version string `json:"version"`
		}
		f, e := dest.Open("opt/node/lib/node_modules/npm/package.json")
		if e != nil {
			return nil, e
		}
		data, e := io.ReadAll(io.LimitReader(f, 1<<20))
		f.Close()
		if e != nil || json.Unmarshal(data, &npm) != nil || npm.Version != "10.9.3" {
			return nil, errors.New("tested bundled npm version required")
		}
	}
	sort.Slice(files, func(i, j int) bool { return files[i].Path < files[j].Path })
	if err = verifySelected(dest, m, c, files); err != nil {
		return nil, err
	}
	return files, nil
}

func makeParents(root *os.Root, name string) error {
	parent := path.Dir(name)
	if parent == "." {
		return nil
	}
	parts := strings.Split(parent, "/")
	for i := range parts {
		p := strings.Join(parts[:i+1], "/")
		if err := root.Mkdir(p, 0700); err != nil && !os.IsExist(err) {
			return err
		}
		info, err := root.Lstat(p)
		if err != nil || !info.IsDir() {
			return errors.New("invalid destination directory")
		}
	}
	return nil
}
func writeSelected(ctx context.Context, root *os.Root, name string, src io.Reader, size int64, mode uint32) (InstalledFile, error) {
	if err := makeParents(root, name); err != nil {
		return InstalledFile{}, err
	}
	f, err := root.OpenFile(name, os.O_WRONLY|os.O_CREATE|os.O_EXCL, os.FileMode(mode))
	if err != nil {
		return InstalledFile{}, err
	}
	defer f.Close()
	hash := sha256.New()
	n, err := io.Copy(io.MultiWriter(f, hash), contextReader{ctx, io.LimitReader(src, size+1)})
	if err != nil || n != size {
		return InstalledFile{}, errors.New("selected file size mismatch")
	}
	if err = f.Chmod(os.FileMode(mode)); err != nil {
		return InstalledFile{}, err
	}
	if err = f.Sync(); err != nil {
		return InstalledFile{}, err
	}
	return InstalledFile{Path: name, SHA256: hex.EncodeToString(hash.Sum(nil)), Bytes: n, Mode: mode}, nil
}
func strictJSON(data []byte, out any) error {
	if len(data) > 64<<10 || uniqueJSON(data) != nil {
		return errors.New("invalid identity JSON")
	}
	d := json.NewDecoder(strings.NewReader(string(data)))
	d.DisallowUnknownFields()
	return d.Decode(out)
}
func readIdentity(root *os.Root, name string, out any) error {
	f, err := root.Open(name)
	if err != nil {
		return err
	}
	defer f.Close()
	data, err := io.ReadAll(io.LimitReader(f, (64<<10)+1))
	if err != nil {
		return err
	}
	return strictJSON(data, out)
}
func verifySelected(root *os.Root, m Manifest, c Component, files []InstalledFile) error {
	has := func(name string) bool {
		for _, f := range files {
			if f.Path == name {
				return true
			}
		}
		return false
	}
	switch c.ID {
	case "node":
		if !has("opt/node/bin/node") || !has("opt/node/LICENSE") {
			return errors.New("missing Node runtime or notice")
		}
		return verifyFormat(path.Join(root.Name(), "opt/node/bin/node"), Artifact{Format: "elf"}, m.Arch)
	case "awf-host":
		if !has("opt/awf/awf") || !has("opt/awf/build.json") {
			return errors.New("missing Host payload")
		}
		var identity buildIdentity
		if readIdentity(root, "opt/awf/build.json", &identity) != nil || identity != (buildIdentity{1, m.Version, m.SourceCommit, m.OS, m.Arch, m.HostProtocol}) {
			return errors.New("Host build identity mismatch")
		}
		return verifyFormat(path.Join(root.Name(), "opt/awf/awf"), Artifact{Format: "elf"}, m.Arch)
	case "awf-extension":
		if !has("opt/awf/extensions/awf.ts") || !has("opt/awf/extensions/extension.json") {
			return errors.New("missing extension payload")
		}
		var identity extensionIdentity
		if readIdentity(root, "opt/awf/extensions/extension.json", &identity) != nil || identity != (extensionIdentity{1, m.Version, m.SourceCommit, m.ExtensionProtocol, m.PiRPCVersion}) {
			return errors.New("extension identity mismatch")
		}
	}
	return nil
}

// Links are generated only after all regular files were prepared, from known
// Node/npm bin declarations. The parent is a fresh private same-user tree.
func pinnedLinkTarget(link InstalledFile) (string, error) {
	target := path.Clean(path.Join(path.Dir(link.Path), link.LinkTarget))
	prefix := "opt/node/"
	if strings.HasPrefix(link.Path, piReleaseDir+"/") {
		prefix = piReleaseDir + "/"
	}
	if !strings.HasPrefix(link.Path, prefix) || !strings.HasPrefix(target, prefix) || strings.HasPrefix(link.LinkTarget, "/") || strings.ContainsAny(link.LinkTarget, "\\\x00\r\n") {
		return "", errors.New("link escapes program tree")
	}
	return target, nil
}
func createPinnedLink(root *os.Root, link InstalledFile) error {
	target, err := pinnedLinkTarget(link)
	if err != nil {
		return err
	}
	info, err := root.Lstat(target)
	if err != nil || !info.Mode().IsRegular() {
		return errors.New("bin link target must be prepared regular file")
	}
	if err := makeParents(root, link.Path); err != nil {
		return err
	}
	return os.Symlink(link.LinkTarget, path.Join(root.Name(), link.Path))
}

func verifyPinnedLink(root *os.Root, link InstalledFile) error {
	target, err := pinnedLinkTarget(link)
	if err != nil {
		return err
	}
	info, err := root.Lstat(link.Path)
	if err != nil || info.Mode()&os.ModeSymlink == 0 || link.Bytes != 0 || link.SHA256 != "" || link.Mode != 0777 {
		return errors.New("invalid program link")
	}
	actual, err := os.Readlink(path.Join(root.Name(), link.Path))
	if err != nil || actual != link.LinkTarget {
		return errors.New("program link differs")
	}
	info, err = root.Lstat(target)
	if err != nil || !info.Mode().IsRegular() {
		return errors.New("program link target invalid")
	}
	return nil
}
