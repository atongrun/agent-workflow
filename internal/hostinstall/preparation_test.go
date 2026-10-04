package hostinstall

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestInitializationPlanIsFixedAndNeverReady(t *testing.T) {
	m, _ := manifestFixture()
	p, err := BuildInitializationPlan(m)
	if err != nil || p.ReadyToInstall || p.HostConfig["piAgentDir"] != "/var/lib/awf/pi-agent" || p.HostConfig["enableMaintenance"] != true {
		t.Fatal(p, err)
	}
	for _, unit := range p.Units {
		if !strings.Contains(unit, "User=awf\n") || !strings.Contains(unit, "KillMode=control-group\n") || !strings.Contains(unit, "ConditionPathExists=/etc/awf/native-") || strings.Contains(unit, "ExecStart=/bin/sh") {
			t.Fatal(unit)
		}
	}
	data, _ := json.Marshal(p)
	if bytes.Contains(data, []byte("AWF_HOST_TOKEN=")) || bytes.Contains(data, []byte(m.SourceCommit)) {
		t.Fatal("invented credentials or interpolated executable identity")
	}
	if len(p.Pending) == 0 || len(p.Activation) == 0 {
		t.Fatal("missing unresolved native prerequisites")
	}
	for i := range m.Components {
		if m.Components[i].ID == "pi" {
			for j := range m.Components[i].Artifacts {
				a := &m.Components[i].Artifacts[j]
				a.URL = "https://github.com/earendil-works/pi/releases/download/v1.0.2/pi-coding-agent-install-" + a.Name
			}
		}
	}
	if err := m.Validate(); err != nil {
		t.Fatal("official release metadata rejected", err)
	}
	m.Components[1].Artifacts[0].URL = "https://pi.dev/api/installer/releases/1.0.2/package.json"
	if m.Validate() == nil {
		t.Fatal("mixed installer sources admitted")
	}
}

func TestPiMetadataIntegrityAndUnsupportedSources(t *testing.T) {
	pkg := []byte(`{"name":"@earendil-works/pi-coding-agent-install","version":"1.0.2","private":true,"dependencies":{"@earendil-works/pi-coding-agent":"1.0.2"},"overrides":{"protobufjs":"7.6.6"},"engines":{"node":">=22.19.0"}}`)
	url := "https://registry.npmjs.org/@earendil-works/pi-coding-agent/-/pi-coding-agent-1.0.2.tgz"
	lock, _ := json.Marshal(map[string]any{"name": "@earendil-works/pi-coding-agent-install", "version": "1.0.2", "lockfileVersion": 3, "packages": map[string]any{"": map[string]any{"name": "@earendil-works/pi-coding-agent-install", "version": "1.0.2", "dependencies": map[string]string{"@earendil-works/pi-coding-agent": "1.0.2"}}, "node_modules/@earendil-works/pi-coding-agent": map[string]any{"version": "1.0.2", "resolved": url, "hasInstallScript": true}}})
	r, err := InspectPiMetadata(pkg, lock, nil)
	if err != nil || r.LockedCatalogComplete || r.RuntimeReady || len(r.MissingIntegrity) != 1 || len(r.LifecycleScriptPackages) != 1 {
		t.Fatal(r, err)
	}
	meta := []byte(`{"name":"@earendil-works/pi-coding-agent","version":"1.0.2","dist":{"tarball":"` + url + `","integrity":"sha512-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="}}`)
	sum := sha256.Sum256(meta)
	evidence := RegistryMetadata{meta, hex.EncodeToString(sum[:])}
	r, err = InspectPiMetadata(pkg, lock, []RegistryMetadata{evidence})
	if err != nil || !r.LockedCatalogComplete || r.RuntimeReady || r.Supplemented != 1 {
		t.Fatal(r, err)
	}
	evidence.SHA256 = strings.Repeat("f", 64)
	if _, err := InspectPiMetadata(pkg, lock, []RegistryMetadata{evidence}); err == nil {
		t.Fatal("unverified metadata admitted")
	}
	for _, bad := range []string{"file:///tmp/pi.tgz", "https://evil.example/pi.tgz", "https://registry.npmjs.org/pi.tgz?credential=x"} {
		if _, err := InspectPiMetadata(pkg, bytes.ReplaceAll(lock, []byte(url), []byte(bad)), nil); err == nil {
			t.Fatal("unsupported source admitted", bad)
		}
	}
	if _, err := InspectPiMetadata(pkg, []byte(`{"lockfileVersion":3,"lockfileVersion":3}`), nil); err == nil {
		t.Fatal("duplicate metadata keys admitted")
	}
}

// Optional local evidence check. It reads official pinned bytes from /tmp and
// never runs them. AWF Host/extension remain explicitly synthetic test payloads.
func TestOfficialPreparationEvidence(t *testing.T) {
	dir := os.Getenv("AWF_PUBLIC_AUDIT_FIXTURE_DIR")
	if dir == "" {
		t.Skip("explicit public audit fixture directory not supplied")
	}
	if !strings.HasPrefix(filepath.Clean(dir), "/tmp/") {
		t.Fatal("audit fixture must be beneath /tmp")
	}
	read := func(name string) []byte {
		t.Helper()
		b, err := os.ReadFile(filepath.Join(dir, name))
		if err != nil {
			t.Fatal(err)
		}
		return b
	}
	check := func(b []byte, size int, want string) {
		t.Helper()
		sum := sha256.Sum256(b)
		if len(b) != size || hex.EncodeToString(sum[:]) != want {
			t.Fatal("official byte identity mismatch")
		}
	}
	node := read("node-v22.19.0-linux-x64.tar.gz")
	magpie := read("magpie-cli-linux-amd64")
	check(node, 54907188, "d36e56998220085782c0ca965f9d51b7726335aed2f5fc7321c6c0ad233aa96d")
	check(magpie, 31375522, "f79df4bd90aa81371eff4386740b1fdcb557cf272d395494948c15b9f4f8ff10")
	pkg, lock := read("pi-official-package.json"), read("pi-official-package-lock.json")
	check(pkg, 317, "491cb1ec4fba98d9547b037cd9dea48ae0bba651a0a80d67dd1660705b60f1c5")
	check(lock, 63566, "b8e9e6a191bcf1e6e3ff8dafe5c0c9042b48e0087cd6d6816dcaa051222ba680")
	r, err := InspectPiMetadata(pkg, lock, nil)
	if err != nil || r.LockedPackages != 147 || len(r.MissingIntegrity) != 8 || r.LockedCatalogComplete || r.RuntimeReady {
		t.Fatal(r, err)
	}
	var pins []struct {
		Name           string `json:"name"`
		MetadataSHA256 string `json:"metadataSHA256"`
	}
	if json.Unmarshal(read("pi-supplemental-pins.json"), &pins) != nil {
		t.Fatal("invalid supplemental audit")
	}
	var evidence []RegistryMetadata
	for _, p := range pins {
		evidence = append(evidence, RegistryMetadata{read("registry-" + strings.TrimPrefix(p.Name, "@earendil-works/") + ".json"), p.MetadataSHA256})
	}
	r, err = InspectPiMetadata(pkg, lock, evidence)
	if err != nil || !r.LockedCatalogComplete || r.RuntimeReady || r.Supplemented != 8 {
		t.Fatal(r, err)
	}
	m, payloads := applyFixture(t)
	replacePayload(&m, payloads, "node", node)
	replacePayload(&m, payloads, "magpie", magpie)
	staged := stageApplyFixture(t, m, payloads)
	receipt, err := ApplyFixture(context.Background(), m, staged, privateParent(t), &recorder{})
	if err != nil || receipt.InstallationComplete {
		t.Fatal(receipt, err)
	}
	for _, c := range receipt.Components {
		if c.RuntimeReady {
			t.Fatal("official bytes claimed native acceptance")
		}
	}
}
