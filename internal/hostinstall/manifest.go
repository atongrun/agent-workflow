// Package hostinstall plans Linux Host installation and stages verified artifacts.
// It never installs programs, executes packages, configures accounts or services.
package hostinstall

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/url"
	"regexp"
	"strings"
	"unicode/utf8"
)

const MaxManifestBytes = 64 << 10
const MaxArtifactBytes int64 = 256 << 20
const MaxBundleBytes int64 = 512 << 20

var componentOrder = []string{"node", "pi", "awf-host", "awf-extension", "magpie"}
var digestPattern = regexp.MustCompile(`^[0-9a-f]{64}$`)
var commitPattern = regexp.MustCompile(`^[0-9a-f]{40}$`)
var releasePattern = regexp.MustCompile(`^v1\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-rc\.(0|[1-9][0-9]*))?$`)
var versionPattern = regexp.MustCompile(`^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$`)

type Manifest struct {
	Schema            int         `json:"schema"`
	Channel           string      `json:"channel"`
	Version           string      `json:"version"`
	SourceCommit      string      `json:"sourceCommit"`
	InstallerProtocol int         `json:"installerProtocol"`
	HostProtocol      string      `json:"hostProtocol"`
	ExtensionProtocol int         `json:"extensionProtocol"`
	PiRPCVersion      string      `json:"piRPCVersion"`
	OS                string      `json:"os"`
	Arch              string      `json:"arch"`
	LibC              string      `json:"libc"`
	Components        []Component `json:"components"`
}
type Component struct {
	ID        string     `json:"id"`
	Version   string     `json:"version"`
	Artifacts []Artifact `json:"artifacts"`
}
type Artifact struct {
	Name   string `json:"name"`
	URL    string `json:"url"`
	SHA256 string `json:"sha256"`
	Bytes  int64  `json:"bytes"`
	Format string `json:"format"`
}

func ParseManifest(data []byte) (Manifest, error) {
	var m Manifest
	if len(data) > MaxManifestBytes || !utf8.Valid(data) {
		return m, errors.New("manifest exceeds bounded UTF-8 contract")
	}
	if err := uniqueJSON(data); err != nil {
		return m, err
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&m); err != nil {
		return m, errors.New("invalid Linux Host manifest fields")
	}
	if err := m.Validate(); err != nil {
		return m, err
	}
	return m, nil
}
func (m Manifest) Validate() error {
	if m.Schema != 1 || m.Channel != "linux-host-v1" || m.InstallerProtocol != 1 || m.HostProtocol != "v1" || m.ExtensionProtocol != 1 || m.PiRPCVersion != "1.0.2" {
		return errors.New("unsupported Linux Host manifest or compatibility protocol")
	}
	if !releasePattern.MatchString(m.Version) || !commitPattern.MatchString(m.SourceCommit) {
		return errors.New("manifest requires exact Go v1 release and source commit")
	}
	if m.OS != "linux" || (m.Arch != "amd64" && m.Arch != "arm64") || m.LibC != "glibc" {
		return errors.New("unsupported manifest platform")
	}
	if len(m.Components) != len(componentOrder) {
		return errors.New("manifest requires the five default components")
	}
	seen := map[string]bool{}
	var total int64
	for _, c := range m.Components {
		if seen[c.ID] {
			return errors.New("duplicate manifest component")
		}
		seen[c.ID] = true
		var expected map[string]string
		arch := m.Arch
		nodeArch := "x64"
		if arch == "arm64" {
			nodeArch = "arm64"
		}
		switch c.ID {
		case "node":
			var major, minor, patch int
			v := strings.TrimPrefix(c.Version, "v")
			if !strings.HasPrefix(c.Version, "v") || !versionPattern.MatchString(v) {
				return errors.New("Node requires exact version")
			}
			_, _ = fmt.Sscanf(v, "%d.%d.%d", &major, &minor, &patch)
			if major < 22 || (major == 22 && minor < 19) {
				return errors.New("Pi requires Node at least 22.19.0")
			}
			name := "node-" + c.Version + "-linux-" + nodeArch + ".tar.xz"
			expected = map[string]string{name: "https://nodejs.org/dist/" + c.Version + "/" + name}
		case "pi":
			if c.Version != m.PiRPCVersion {
				return errors.New("Pi version is outside verified RPC compatibility")
			}
			base := "https://pi.dev/api/installer/releases/" + c.Version + "/"
			expected = map[string]string{"package.json": base + "package.json", "package-lock.json": base + "package-lock.json"}
		case "awf-host", "awf-extension":
			if c.Version != m.Version {
				return errors.New("Host and extension must share the manifest release")
			}
			name := "awf_" + m.Version + "_linux_" + arch + ".tar.gz"
			if c.ID == "awf-extension" {
				name = "awf-extension_" + m.Version + ".tar.gz"
			}
			expected = map[string]string{name: "https://github.com/atongrun/agent-workflow/releases/download/" + m.Version + "/" + name}
		case "magpie":
			if !versionPattern.MatchString(c.Version) {
				return errors.New("Magpie requires exact version")
			}
			name := "magpie-cli-linux-" + arch
			expected = map[string]string{name: "https://github.com/yetone/magpie-releases/releases/download/v" + c.Version + "/" + name}
		default:
			return errors.New("unknown manifest component")
		}
		if len(c.Artifacts) != len(expected) {
			return errors.New("component has missing or extra artifacts")
		}
		names := map[string]bool{}
		for _, a := range c.Artifacts {
			if names[a.Name] || expected[a.Name] == "" || a.URL != expected[a.Name] {
				return errors.New("artifact must use its exact official versioned source")
			}
			names[a.Name] = true
			u, err := url.Parse(a.URL)
			if err != nil || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
				return errors.New("invalid artifact source")
			}
			format := "tar.gz"
			switch c.ID {
			case "node":
				format = "tar.xz"
			case "pi":
				format = "json"
			case "magpie":
				format = "elf"
			}
			if a.Format != format || !digestPattern.MatchString(a.SHA256) || a.Bytes < 1 || a.Bytes > MaxArtifactBytes {
				return errors.New("artifact requires exact format, size and SHA-256")
			}
			total += a.Bytes
		}
	}
	if total > MaxBundleBytes {
		return errors.New("bundle exceeds staging size limit")
	}
	return nil
}

// Reject duplicate keys at every depth before decoding a trust-boundary manifest.
func uniqueJSON(data []byte) error {
	d := json.NewDecoder(bytes.NewReader(data))
	var value func(int) error
	value = func(depth int) error {
		if depth > 16 {
			return errors.New("manifest nesting exceeds limit")
		}
		token, err := d.Token()
		if err != nil {
			return errors.New("invalid manifest JSON")
		}
		delimiter, ok := token.(json.Delim)
		if !ok {
			return nil
		}
		switch delimiter {
		case '{':
			seen := map[string]bool{}
			for d.More() {
				key, e := d.Token()
				name, ok := key.(string)
				if e != nil || !ok || seen[name] {
					return errors.New("duplicate or invalid manifest key")
				}
				seen[name] = true
				if e = value(depth + 1); e != nil {
					return e
				}
			}
		case '[':
			for d.More() {
				if e := value(depth + 1); e != nil {
					return e
				}
			}
		default:
			return errors.New("invalid manifest JSON")
		}
		_, err = d.Token()
		return err
	}
	if err := value(0); err != nil {
		return err
	}
	if _, err := d.Token(); err != io.EOF {
		return errors.New("manifest must contain exactly one JSON value")
	}
	return nil
}
