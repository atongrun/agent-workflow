package lifecycle

import (
	"archive/zip"
	"bytes"
	"context"
	"crypto/sha256"
	encodingbinary "encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const maxReleaseBytes = 100 << 20

type releaseAsset struct {
	Name string `json:"name"`
	URL  string `json:"browser_download_url"`
}
type releaseInfo struct {
	Tag             string         `json:"tag_name"`
	TargetCommitish string         `json:"target_commitish"`
	Draft           bool           `json:"draft"`
	Prerelease      bool           `json:"prerelease"`
	Assets          []releaseAsset `json:"assets"`
}

func assetName(v, arch string) string { return "awf_" + v + "_windows_" + arch + ".zip" }
func officialAsset(v, name string) string {
	return "https://github.com/" + Repository + "/releases/download/" + v + "/" + name
}
func releaseClient() *http.Client {
	return &http.Client{Timeout: 2 * time.Minute, CheckRedirect: func(r *http.Request, via []*http.Request) error {
		if len(via) > 5 || r.URL.Scheme != "https" || r.URL.User != nil {
			return errors.New("unsafe release redirect")
		}
		switch r.URL.Host {
		case "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com":
			return nil
		}
		return errors.New("release redirect is not an official GitHub asset host")
	}}
}
func fetch(ctx context.Context, c *http.Client, address string, limit int64) ([]byte, error) {
	u, e := url.Parse(address)
	if e != nil || u.Scheme != "https" || u.User != nil {
		return nil, errors.New("release download must use HTTPS")
	}
	req, e := http.NewRequestWithContext(ctx, "GET", address, nil)
	if e != nil {
		return nil, e
	}
	req.Header.Set("User-Agent", "awf-cli")
	req.Header.Set("Accept", "application/vnd.github+json")
	res, e := c.Do(req)
	if e != nil {
		return nil, errors.New("official GitHub release request failed")
	}
	defer res.Body.Close()
	if res.StatusCode != 200 {
		return nil, fmt.Errorf("official GitHub release returned HTTP %d; no installed version was changed", res.StatusCode)
	}
	b, e := io.ReadAll(io.LimitReader(res.Body, limit+1))
	if e != nil {
		return nil, e
	}
	if int64(len(b)) > limit {
		return nil, errors.New("release download exceeds allowed size")
	}
	return b, nil
}
func checksum(data []byte, name string) (string, error) {
	found := ""
	for _, line := range strings.Split(string(data), "\n") {
		f := strings.Fields(line)
		if len(f) == 0 {
			continue
		}
		if len(f) != 2 {
			return "", errors.New("malformed SHA256SUMS")
		}
		decoded, e := hex.DecodeString(f[0])
		if e != nil || len(decoded) != 32 {
			return "", errors.New("malformed SHA256SUMS digest")
		}
		if strings.TrimPrefix(f[1], "*") == name {
			if found != "" {
				return "", errors.New("duplicate asset checksum")
			}
			found = strings.ToLower(f[0])
		}
	}
	if found == "" {
		return "", errors.New("release has no checksum for this architecture")
	}
	return found, nil
}

type releaseTarget struct {
	Version      string
	SourceCommit string
	Digest       string
}

func resolveReleaseTarget(ctx context.Context, c *http.Client, requested, arch string) (releaseTarget, error) {
	if arch != "amd64" && arch != "arm64" {
		return releaseTarget{}, errors.New("supported native Windows architectures are amd64 and arm64")
	}
	if requested != "" {
		if err := validGoReleaseVersion(requested); err != nil {
			return releaseTarget{}, err
		}
		return releaseTarget{Version: requested}, nil
	}
	data, err := fetchMetadata(ctx, c, channelManifestURL, 4096)
	if err != nil {
		return releaseTarget{}, err
	}
	manifest, err := parseChannelManifest(data)
	if err != nil {
		return releaseTarget{}, err
	}
	if manifest.CLIProtocol != "2" {
		return releaseTarget{}, errors.New("the go-v1 channel selects legacy CLI protocol 1; wait for a channel-aware release (protocol 2)")
	}
	digest := manifest.WindowsAMD64SHA256
	if arch == "arm64" {
		digest = manifest.WindowsARM64SHA256
	}
	return releaseTarget{Version: manifest.Version, SourceCommit: manifest.SourceCommit, Digest: digest}, nil
}

// stageRelease never executes downloaded code. Default selection is exclusively
// the publisher's Go channel, never GitHub's repository-wide latest endpoint.
func stageRelease(ctx context.Context, c *http.Client, root, requested, arch, pin string, allowPrerelease bool, currentVersion string) (string, error) {
	if e := validateReleaseRequest(requested, allowPrerelease); e != nil {
		return "", e
	}
	target, e := resolveReleaseTarget(ctx, c, requested, arch)
	if e != nil {
		return "", e
	}
	return stageSelectedRelease(ctx, c, root, target, arch, pin, allowPrerelease, currentVersion)
}

func stageSelectedRelease(ctx context.Context, c *http.Client, root string, target releaseTarget, arch, pin string, allowPrerelease bool, currentVersion string) (string, error) {
	if err := validateReleaseRequest(target.Version, allowPrerelease); err != nil {
		return "", err
	}
	if target.Version == "" {
		return "", errors.New("release selection requires an exact Go CLI version")
	}
	if arch != "amd64" && arch != "arm64" {
		return "", errors.New("unsupported release architecture")
	}
	if currentVersion != "" {
		order, err := compareReleaseVersions(target.Version, currentVersion)
		if err != nil {
			return "", err
		}
		if order < 0 {
			return "", errors.New("selected release is older than the installed version; downgrade is blocked")
		}
	}
	metadata, e := fetchMetadata(ctx, c, releaseMetadataURL(target.Version), 2<<20)
	if e != nil {
		return "", e
	}
	if e = validateUniqueJSON(metadata); e != nil {
		return "", errors.New("invalid or duplicate official release metadata")
	}
	if e = requireMetadataFields(metadata, "tag_name", "target_commitish", "draft", "prerelease", "assets"); e != nil {
		return "", e
	}
	var release releaseInfo
	if e = json.Unmarshal(metadata, &release); e != nil {
		return "", errors.New("invalid official release metadata")
	}
	var flags struct {
		Draft      *bool `json:"draft"`
		Prerelease *bool `json:"prerelease"`
	}
	if e = json.Unmarshal(metadata, &flags); e != nil || flags.Draft == nil || flags.Prerelease == nil {
		return "", errors.New("release metadata requires explicit boolean draft and prerelease fields")
	}
	if validGoReleaseVersion(release.Tag) != nil || release.Draft || release.Tag != target.Version {
		return "", errors.New("release is not the requested pinned tag")
	}
	if release.Prerelease != prereleaseVersion(release.Tag) {
		return "", errors.New("release tag and GitHub prerelease status disagree")
	}
	if !sourceCommitRE.MatchString(release.TargetCommitish) || (target.SourceCommit != "" && release.TargetCommitish != target.SourceCommit) {
		return "", errors.New("release source commit does not match the publisher channel or is unknown")
	}
	if e = verifyReleaseRef(ctx, c, release.Tag, release.TargetCommitish); e != nil {
		return "", e
	}
	name := assetName(release.Tag, arch)
	wanted := map[string]string{name: "", "SHA256SUMS": ""}
	for _, a := range release.Assets {
		if _, ok := wanted[a.Name]; ok {
			if wanted[a.Name] != "" || a.URL != officialAsset(release.Tag, a.Name) {
				return "", errors.New("ambiguous or unofficial release asset")
			}
			wanted[a.Name] = a.URL
		}
	}
	if wanted[name] == "" || wanted["SHA256SUMS"] == "" {
		return "", errors.New("official release does not contain the CLI package and SHA256SUMS for this architecture; no installer asset is assumed to exist")
	}
	sums, e := fetch(ctx, c, wanted["SHA256SUMS"], 1<<20)
	if e != nil {
		return "", e
	}
	digest, e := checksum(sums, name)
	if e != nil {
		return "", e
	}
	if target.Digest != "" && target.Digest != digest {
		return "", errors.New("release checksum differs from the publisher channel SHA-256")
	}
	if pin != "" && (!strings.EqualFold(pin, digest) || len(pin) != 64) {
		return "", errors.New("release checksum differs from the explicitly pinned SHA-256")
	}
	payload, e := fetch(ctx, c, wanted[name], maxReleaseBytes)
	if e != nil {
		return "", e
	}
	sum := sha256.Sum256(payload)
	if hex.EncodeToString(sum[:]) != digest {
		return "", errors.New("release SHA-256 verification failed")
	}
	if e = stageArchive(root, release.Tag, arch, payload); e != nil {
		return "", e
	}
	return release.Tag, nil
}
func stageArchive(root, v, arch string, payload []byte) error {
	if e := validVersion(v); e != nil {
		return e
	}
	archive, e := zip.NewReader(bytes.NewReader(payload), int64(len(payload)))
	if e != nil {
		return errors.New("invalid release ZIP")
	}
	expected := map[string]bool{"awf.exe": false, "awf-node.exe": false, "manifest.json": false}
	if len(archive.File) != len(expected) {
		return errors.New("release ZIP must contain exactly awf.exe, awf-node.exe, and manifest.json")
	}
	var expanded uint64
	for _, f := range archive.File {
		seen, ok := expected[f.Name]
		if !ok || seen || !f.Mode().IsRegular() || f.UncompressedSize64 == 0 || f.UncompressedSize64 > maxReleaseBytes || f.CompressedSize64 > maxReleaseBytes || f.ExternalAttrs&0x410 != 0 {
			return errors.New("release ZIP contains an unexpected, duplicate, linked, or oversized entry")
		}
		expected[f.Name] = true
		expanded += f.UncompressedSize64
		if expanded > maxReleaseBytes {
			return errors.New("release ZIP expanded payload exceeds 100 MiB")
		}

		if f.Name == "manifest.json" && f.UncompressedSize64 > 4096 {
			return errors.New("release manifest is oversized")
		}
	}
	versions, e := managedDirectory(root, "versions")
	if e != nil {
		return e
	}
	staging, e := os.MkdirTemp(versions, ".stage-")
	if e != nil {
		return e
	}
	defer os.RemoveAll(staging)
	for _, f := range archive.File {
		r, e := f.Open()
		if e != nil {
			return e
		}
		data, e := io.ReadAll(io.LimitReader(r, maxReleaseBytes+1))
		r.Close()
		if e != nil || len(data) > maxReleaseBytes {
			return errors.New("cannot read bounded release ZIP entry")
		}
		if f.Name == "manifest.json" {
			if e = validateManifest(data, v, arch); e != nil {
				return e
			}
		} else if e = validatePE(data, arch); e != nil {
			return e
		}
		if e = os.WriteFile(filepath.Join(staging, f.Name), data, 0700); e != nil {
			return e
		}
	}
	dest := filepath.Join(versions, v)
	if _, e = os.Stat(dest); e == nil {
		// Repeated install is safe only for byte-identical payloads. Never overwrite
		// a loaded DLL/executable or accept a mutable tag with different content.
		for name := range expected {
			a, e := os.ReadFile(filepath.Join(staging, name))
			if e != nil {
				return e
			}
			b, e := readBounded(filepath.Join(dest, name), maxReleaseBytes)
			if e != nil || !bytes.Equal(a, b) {
				return errors.New("installed tag already exists with different bytes; refusing to overwrite")
			}
		}
		return nil
	} else if !os.IsNotExist(e) {
		return e
	}
	return os.Rename(staging, dest)
}
func verifyDigest(b []byte, digest string) error {
	expected, e := hex.DecodeString(digest)
	if e != nil || len(expected) != 32 {
		return errors.New("expected SHA-256 must have exactly 64 hexadecimal digits")
	}
	actual := sha256.Sum256(b)
	if !bytes.Equal(actual[:], expected) {
		return errors.New("release SHA-256 verification failed")
	}
	return nil
}

// Check the architecture before executing the self-check, including on Windows
// ARM64 hosts capable of emulating a differently compiled Windows executable.
func validatePE(data []byte, arch string) error {
	if len(data) < 90 || string(data[:2]) != "MZ" {
		return errors.New("release executable is not a native Windows PE file")
	}
	offset := uint64(encodingbinary.LittleEndian.Uint32(data[0x3c:0x40]))
	if offset < 64 || offset+26 > uint64(len(data)) || string(data[offset:offset+4]) != "PE\x00\x00" {
		return errors.New("release executable has an invalid PE header")
	}
	machine := encodingbinary.LittleEndian.Uint16(data[offset+4 : offset+6])
	expected := uint16(0)
	switch arch {
	case "amd64":
		expected = 0x8664
	case "arm64":
		expected = 0xaa64
	default:
		return errors.New("unsupported native executable architecture")
	}
	if encodingbinary.LittleEndian.Uint16(data[offset+24:offset+26]) != 0x20b {
		return errors.New("release executable must be native 64-bit PE")
	}
	if machine != expected {
		return errors.New("release executable machine does not match the requested architecture")
	}
	return nil
}

func validateManifest(data []byte, v, arch string) error {
	if len(data) > 4<<10 {
		return errors.New("release manifest is oversized")
	}
	d := json.NewDecoder(bytes.NewReader(data))
	token, e := d.Token()
	if e != nil || token != json.Delim('{') {
		return errors.New("invalid release manifest")
	}
	fields := map[string]string{}
	for d.More() {
		key, e := d.Token()
		if e != nil {
			return errors.New("invalid release manifest")
		}
		name, ok := key.(string)
		if !ok {
			return errors.New("invalid release manifest")
		}
		if _, ok = fields[name]; ok {
			return errors.New("duplicate release manifest field")
		}
		var value string
		if d.Decode(&value) != nil {
			return errors.New("invalid release manifest value")
		}
		fields[name] = value
	}
	if _, e = d.Token(); e != nil || d.Decode(new(any)) != io.EOF {
		return errors.New("invalid release manifest")
	}
	if len(fields) != 3 || fields["version"] != v || fields["os"] != "windows" || fields["arch"] != arch {
		return errors.New("release manifest does not match pinned version and architecture")
	}
	return nil
}
