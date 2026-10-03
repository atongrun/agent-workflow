package lifecycle

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"unicode/utf8"
)

const channelName = "go-v1"
const channelManifestURL = "https://raw.githubusercontent.com/" + Repository + "/awf/go-v1/distribution/go-v1.json"

var sourceCommitRE = regexp.MustCompile(`^[0-9a-f]{40}$`)
var channelDigestRE = regexp.MustCompile(`^[0-9a-f]{64}$`)

// ChannelSelection is deliberately separate from the immutable launcher's
// current.json format. Existing launchers can keep forwarding to newer versions.
type ChannelSelection struct {
	Schema          string `json:"schema"`
	Channel         string `json:"channel"`
	PreviewApproved bool   `json:"previewApproved"`
}

type channelManifest struct {
	Schema             string `json:"schema"`
	Channel            string `json:"channel"`
	Version            string `json:"version"`
	SourceCommit       string `json:"sourceCommit"`
	CLIProtocol        string `json:"cliProtocol"`
	WindowsAMD64SHA256 string `json:"windowsAMD64SHA256"`
	WindowsARM64SHA256 string `json:"windowsARM64SHA256"`
}

// parseFlatFields accepts only the exact, unescaped publisher vocabulary. The
// normal JSON decoder alone silently accepts duplicate keys, escaped keys and
// null string values, which are unsuitable for this trust boundary.
func parseFlatFields(data []byte, names ...string) (map[string]json.RawMessage, error) {
	if len(data) > 4096 || !utf8.Valid(data) || bytes.ContainsRune(data, '\\') {
		return nil, errors.New("channel metadata must be bounded, unescaped UTF-8 JSON")
	}
	allowed := make(map[string]bool, len(names))
	for _, name := range names {
		allowed[name] = true
	}
	d := json.NewDecoder(bytes.NewReader(data))
	token, err := d.Token()
	if err != nil || token != json.Delim('{') {
		return nil, errors.New("channel metadata must be an object")
	}
	fields := make(map[string]json.RawMessage, len(names))
	for d.More() {
		token, err = d.Token()
		name, ok := token.(string)
		if err != nil || !ok || !allowed[name] {
			return nil, errors.New("unknown channel metadata field")
		}
		if _, exists := fields[name]; exists {
			return nil, errors.New("duplicate channel metadata field")
		}
		var raw json.RawMessage
		if err = d.Decode(&raw); err != nil {
			return nil, errors.New("invalid channel metadata value")
		}
		fields[name] = raw
	}
	if token, err = d.Token(); err != nil || token != json.Delim('}') || d.Decode(new(any)) != io.EOF || len(fields) != len(names) {
		return nil, errors.New("channel metadata requires exactly the supported fields")
	}
	return fields, nil
}

func parseChannelManifest(data []byte) (channelManifest, error) {
	var m channelManifest
	fields, err := parseFlatFields(data, "schema", "channel", "version", "sourceCommit", "cliProtocol", "windowsAMD64SHA256", "windowsARM64SHA256")
	if err != nil {
		return m, err
	}
	for _, raw := range fields {
		if len(raw) < 2 || raw[0] != '"' || raw[len(raw)-1] != '"' {
			return m, errors.New("channel manifest fields must be strings")
		}
	}
	if err = json.Unmarshal(data, &m); err != nil {
		return m, errors.New("invalid channel manifest")
	}
	if m.Schema != "1" || m.Channel != channelName || (m.CLIProtocol != "1" && m.CLIProtocol != "2") {
		return m, errors.New("unsupported channel schema, name, or CLI protocol")
	}
	if err = validGoReleaseVersion(m.Version); err != nil {
		return m, err
	}
	if versionRE.FindStringSubmatch(m.Version)[1] != "1" {
		return m, errors.New("go-v1 channel requires a major-version-1 Go CLI release")
	}
	if !sourceCommitRE.MatchString(m.SourceCommit) || !channelDigestRE.MatchString(m.WindowsAMD64SHA256) || !channelDigestRE.MatchString(m.WindowsARM64SHA256) {
		return m, errors.New("channel manifest requires canonical commit and archive SHA-256 values")
	}
	return m, nil
}

func loadChannel(root string) (ChannelSelection, error) {
	selection := ChannelSelection{Schema: "1", Channel: channelName}
	data, err := readBounded(filepath.Join(root, "channel.json"), 4096)
	if os.IsNotExist(err) {
		return selection, nil
	} // Legacy installs do not imply preview consent.
	if err != nil {
		return selection, err
	}
	fields, err := parseFlatFields(data, "schema", "channel", "previewApproved")
	if err != nil {
		return selection, err
	}
	if !bytes.Equal(fields["schema"], []byte(`"1"`)) || !bytes.Equal(fields["channel"], []byte(`"go-v1"`)) || (!bytes.Equal(fields["previewApproved"], []byte("true")) && !bytes.Equal(fields["previewApproved"], []byte("false"))) {
		return selection, errors.New("invalid saved update channel; explicit recovery is required")
	}
	if err = json.Unmarshal(data, &selection); err != nil {
		return selection, err
	}
	return selection, nil
}

func validGoReleaseVersion(v string) error {
	if err := validVersion(v); err != nil {
		return err
	}
	order, err := compareReleaseVersions(v, "v1.0.0-rc.0")
	if err != nil || order < 0 {
		return errors.New("release must be a Go CLI tag at or above v1.0.0-rc.0")
	}
	return nil
}

func releaseMetadataURL(version string) string {
	return "https://api.github.com/repos/" + Repository + "/releases/tags/" + version
}
func releaseRefURL(version string) string {
	return "https://api.github.com/repos/" + Repository + "/git/ref/tags/" + version
}

// Metadata is never redirected, including to another official GitHub host. Only
// release archive downloads use GitHub's CDN redirect policy.
func fetchMetadata(ctx context.Context, c *http.Client, address string, limit int64) ([]byte, error) {
	u, err := url.Parse(address)
	allowed := address == channelManifestURL
	if err == nil && u.Scheme == "https" && u.Host == "api.github.com" && u.User == nil && u.RawQuery == "" && !u.ForceQuery && u.Fragment == "" && u.RawPath == "" {
		for _, prefix := range []string{"/repos/" + Repository + "/releases/tags/", "/repos/" + Repository + "/git/ref/tags/"} {
			if bytes.HasPrefix([]byte(u.Path), []byte(prefix)) && validGoReleaseVersion(u.Path[len(prefix):]) == nil {
				allowed = true
			}
		}
	}
	if !allowed {
		return nil, errors.New("metadata URL is not an exact official channel or release endpoint")
	}
	client := *c
	client.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	return fetch(ctx, &client, address, limit)
}

// validateUniqueJSON rejects duplicate keys at every depth in GitHub metadata,
// while allowing unrelated fields added by GitHub's public API.
func validateUniqueJSON(data []byte) error {
	d := json.NewDecoder(bytes.NewReader(data))
	var value func(int) error
	value = func(depth int) error {
		if depth > 64 {
			return errors.New("metadata nesting exceeds limit")
		}
		token, err := d.Token()
		if err != nil {
			return err
		}
		delim, ok := token.(json.Delim)
		if !ok {
			return nil
		}
		switch delim {
		case '{':
			seen := map[string]bool{}
			for d.More() {
				key, e := d.Token()
				name, ok := key.(string)
				// GitHub's schema uses ASCII keys. encoding/json also folds
				// Unicode aliases such as long-s onto ASCII struct fields.
				if e != nil || !ok || strings.IndexFunc(name, func(r rune) bool { return r > 127 }) >= 0 || seen[strings.ToLower(name)] {
					return errors.New("duplicate or invalid release metadata field")
				}
				seen[strings.ToLower(name)] = true
				if err = value(depth + 1); err != nil {
					return err
				}
			}
		case '[':
			for d.More() {
				if err = value(depth + 1); err != nil {
					return err
				}
			}
		default:
			return errors.New("invalid metadata delimiter")
		}
		_, err = d.Token()
		return err
	}
	if !utf8.Valid(data) {
		return errors.New("invalid metadata encoding")
	}
	if err := value(0); err != nil {
		return err
	}
	if d.Decode(new(any)) != io.EOF {
		return errors.New("expected exactly one metadata object")
	}
	return nil
}

func requireMetadataFields(data []byte, names ...string) error {
	var fields map[string]json.RawMessage
	if json.Unmarshal(data, &fields) != nil || fields == nil {
		return errors.New("release metadata must be an object")
	}
	for _, name := range names {
		if _, exists := fields[name]; !exists {
			return fmt.Errorf("release metadata is missing exact field %s", name)
		}
	}
	return nil
}

func verifyReleaseRef(ctx context.Context, c *http.Client, version, commit string) error {
	data, err := fetchMetadata(ctx, c, releaseRefURL(version), 2<<20)
	if err != nil {
		return err
	}
	if err = validateUniqueJSON(data); err != nil {
		return err
	}
	if err = requireMetadataFields(data, "ref", "object"); err != nil {
		return err
	}
	var fields map[string]json.RawMessage
	if json.Unmarshal(data, &fields) != nil {
		return errors.New("invalid release ref metadata")
	}
	if err = requireMetadataFields(fields["object"], "type", "sha"); err != nil {
		return err
	}
	var ref struct {
		Ref    string `json:"ref"`
		Object struct {
			Type string `json:"type"`
			SHA  string `json:"sha"`
		} `json:"object"`
	}
	if json.Unmarshal(data, &ref) != nil || ref.Ref != "refs/tags/"+version || ref.Object.Type != "commit" || ref.Object.SHA != commit || !sourceCommitRE.MatchString(commit) {
		return fmt.Errorf("release tag %s is not a lightweight tag at the expected source commit", version)
	}
	return nil
}

// A pinned bootstrap's one-release approval must not become standing consent.
// The channel bootstrap passes --channel only after disclosing future previews.
func installChannelSelection(channel string, allowPrerelease bool) (ChannelSelection, error) {
	selection := ChannelSelection{Schema: "1", Channel: channelName}
	if channel != "" && channel != channelName {
		return selection, errors.New("unsupported update channel; only go-v1 is supported")
	}
	selection.PreviewApproved = channel == channelName && allowPrerelease
	return selection, nil
}
