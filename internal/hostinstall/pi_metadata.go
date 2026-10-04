package hostinstall

import (
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/url"
	"path"
	"sort"
	"strings"
)

// RegistryMetadata is explicitly reviewed public npm metadata, not an npm
// install or permission to run a lifecycle script. Digest authenticates Data
// against the caller's independently reviewed pin.
type RegistryMetadata struct {
	Data   []byte
	SHA256 string
}
type PiMetadataReport struct {
	LockedPackages          int      `json:"lockedPackages"`
	Supplemented            int      `json:"supplemented"`
	MissingIntegrity        []string `json:"missingIntegrity"`
	LifecycleScriptPackages []string `json:"lifecycleScriptPackages"`
	LockedCatalogComplete   bool     `json:"lockedCatalogComplete"`
	RuntimeReady            bool     `json:"runtimeReady"`
}
type piPackageMetadata struct {
	Name         string            `json:"name"`
	Version      string            `json:"version"`
	Private      bool              `json:"private"`
	Dependencies map[string]string `json:"dependencies"`
	Overrides    map[string]string `json:"overrides"`
	Engines      map[string]string `json:"engines"`
}
type piLockedPackage struct {
	Name             string            `json:"name"`
	Version          string            `json:"version"`
	Resolved         string            `json:"resolved"`
	Integrity        string            `json:"integrity"`
	Link             bool              `json:"link"`
	HasInstallScript bool              `json:"hasInstallScript"`
	Dependencies     map[string]string `json:"dependencies"`
}

func boundedPiJSON(data []byte, out any) error {
	if len(data) > 4<<20 || uniqueJSON(data) != nil || json.Unmarshal(data, out) != nil {
		return errors.New("invalid bounded Pi metadata")
	}
	return nil
}
func npmTarball(raw string) bool {
	u, err := url.Parse(raw)
	return err == nil && u.Scheme == "https" && u.Host == "registry.npmjs.org" && u.User == nil && u.RawQuery == "" && u.Fragment == "" && strings.HasSuffix(u.Path, ".tgz") && !strings.Contains(u.Path, "\\") && path.Clean(u.Path) == u.Path
}
func sha512Integrity(s string) bool {
	if !strings.HasPrefix(s, "sha512-") {
		return false
	}
	b, err := base64.StdEncoding.DecodeString(strings.TrimPrefix(s, "sha512-"))
	return err == nil && len(b) == 64
}

// InspectPiMetadata checks the locked official registry catalog. It deliberately
// does not resolve semver, install, modify the official lock, fetch tarballs or
// claim optional/platform/native dependencies work. npm ci owns that next step.
func InspectPiMetadata(pkg, lock []byte, supplemental []RegistryMetadata) (PiMetadataReport, error) {
	r := PiMetadataReport{MissingIntegrity: []string{}, LifecycleScriptPackages: []string{}}
	var p piPackageMetadata
	var l struct {
		Name            string                     `json:"name"`
		Version         string                     `json:"version"`
		LockfileVersion int                        `json:"lockfileVersion"`
		Packages        map[string]piLockedPackage `json:"packages"`
	}
	if boundedPiJSON(pkg, &p) != nil || boundedPiJSON(lock, &l) != nil || p.Name != "@earendil-works/pi-coding-agent-install" || p.Version != "1.0.2" || !p.Private || len(p.Dependencies) != 1 || p.Dependencies["@earendil-works/pi-coding-agent"] != "1.0.2" || len(p.Overrides) != 1 || p.Overrides["protobufjs"] != "7.6.6" || p.Engines["node"] != ">=22.19.0" || l.Name != p.Name || l.Version != p.Version || l.LockfileVersion != 3 || len(l.Packages) < 2 || len(l.Packages) > 4096 {
		return r, errors.New("unsupported official Pi installer metadata")
	}
	root, ok := l.Packages[""]
	if !ok || root.Name != p.Name || root.Version != p.Version || len(root.Dependencies) != 1 || root.Dependencies["@earendil-works/pi-coding-agent"] != "1.0.2" {
		return r, errors.New("Pi lock root mismatch")
	}
	type pin struct{ version, tarball, integrity string }
	pins := map[string]pin{}
	for _, evidence := range supplemental {
		sum := sha256.Sum256(evidence.Data)
		if !digestPattern.MatchString(evidence.SHA256) || hex.EncodeToString(sum[:]) != evidence.SHA256 {
			return r, errors.New("npm metadata digest mismatch")
		}
		var meta struct {
			Name    string `json:"name"`
			Version string `json:"version"`
			Dist    struct {
				Tarball   string `json:"tarball"`
				Integrity string `json:"integrity"`
			} `json:"dist"`
		}
		if boundedPiJSON(evidence.Data, &meta) != nil || !strings.HasPrefix(meta.Name, "@earendil-works/") || meta.Version != "1.0.2" || !npmTarball(meta.Dist.Tarball) || !sha512Integrity(meta.Dist.Integrity) {
			return r, errors.New("invalid supplementary official npm metadata")
		}
		if _, exists := pins[meta.Name]; exists {
			return r, errors.New("duplicate supplementary npm metadata")
		}
		pins[meta.Name] = pin{meta.Version, meta.Dist.Tarball, meta.Dist.Integrity}
	}
	used := map[string]bool{}
	for name, entry := range l.Packages {
		if name == "" {
			continue
		}
		if !strings.HasPrefix(name, "node_modules/") || path.Clean(name) != name || strings.Contains(name, "\\") || entry.Link || !versionPattern.MatchString(entry.Version) || !npmTarball(entry.Resolved) {
			return r, errors.New("unsupported Pi locked package source")
		}
		r.LockedPackages++
		if entry.HasInstallScript {
			r.LifecycleScriptPackages = append(r.LifecycleScriptPackages, name)
		}
		if entry.Integrity != "" {
			if !sha512Integrity(entry.Integrity) {
				return r, errors.New("unsupported Pi lock integrity")
			}
			continue
		}
		packageName := strings.TrimPrefix(name, "node_modules/")
		supplement, exists := pins[packageName]
		if !exists {
			r.MissingIntegrity = append(r.MissingIntegrity, name)
			continue
		}
		if supplement.version != entry.Version || supplement.tarball != entry.Resolved {
			return r, errors.New("supplementary Pi package identity mismatch")
		}
		used[packageName] = true
		r.Supplemented++
	}
	if len(used) != len(pins) {
		return r, errors.New("unused supplementary npm metadata")
	}
	pi, ok := l.Packages["node_modules/@earendil-works/pi-coding-agent"]
	if !ok || pi.Version != p.Version {
		return r, errors.New("Pi entry missing from lock")
	}
	sort.Strings(r.MissingIntegrity)
	sort.Strings(r.LifecycleScriptPackages)
	r.LockedCatalogComplete = len(r.MissingIntegrity) == 0
	return r, nil
}
