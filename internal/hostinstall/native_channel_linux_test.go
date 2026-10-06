//go:build linux

package hostinstall

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func channelFixture(t *testing.T, mutate func(string, []byte) (int, []byte)) (Manifest, *http.Client, *[]string) {
	t.Helper()
	m, _ := manifestFixture()
	setFixtureRelease(&m, "v1.0.1-rc.3")
	b, _ := json.Marshal(m)
	requests := []string{}
	c := &http.Client{Transport: fixtureTransport(func(r *http.Request) (*http.Response, error) {
		address := r.URL.String()
		requests = append(requests, address)
		payload := b
		if strings.Contains(address, "/git/ref/tags/") {
			payload = []byte(fmt.Sprintf(`{"object":{"type":"commit","sha":"%s"}}`, m.SourceCommit))
		} else if address != LinuxChannelURL && address != releaseManifestURL(m.Version) {
			t.Fatalf("unexpected metadata address %s", address)
		}
		code := 200
		if mutate != nil {
			code, payload = mutate(address, payload)
		}
		return &http.Response{StatusCode: code, Body: io.NopCloser(strings.NewReader(string(payload))), Header: make(http.Header), ContentLength: int64(len(payload)), Request: r}, nil
	})}
	return m, c, &requests
}

func setFixtureRelease(m *Manifest, version string) {
	m.Version = version
	for i := range m.Components {
		c := &m.Components[i]
		if c.ID != "awf-host" && c.ID != "awf-extension" {
			continue
		}
		c.Version = m.Version
		prefix := "awf_"
		suffix := "_linux_amd64.tar.gz"
		if c.ID == "awf-extension" {
			prefix, suffix = "awf-extension_", ".tar.gz"
		}
		c.Artifacts[0].Name = prefix + m.Version + suffix
		c.Artifacts[0].URL = "https://github.com/atongrun/agent-workflow/releases/download/" + m.Version + "/" + c.Artifacts[0].Name
	}
}

func TestLinuxDefaultUpdateChecksChannelReleaseAndTag(t *testing.T) {
	want, client, requests := channelFixture(t, nil)
	got, err := readUpdateManifest(context.Background(), "", "", client, &recorder{})
	if err != nil || !reflect.DeepEqual(got, want) {
		t.Fatal(got, err)
	}
	if len(*requests) != 3 || (*requests)[0] != LinuxChannelURL || (*requests)[1] != releaseManifestURL(want.Version) || !strings.HasSuffix((*requests)[2], "/git/ref/tags/"+want.Version) {
		t.Fatal(*requests)
	}
}

func TestLinuxExactUpdateAndAdvancedManifestUseImmutableSource(t *testing.T) {
	for _, local := range []bool{false, true} {
		m, client, requests := channelFixture(t, nil)
		file, version := "", m.Version
		if local {
			file, version = filepath.Join(t.TempDir(), "manifest.json"), ""
			b, _ := json.Marshal(m)
			if err := os.WriteFile(file, b, 0600); err != nil {
				t.Fatal(err)
			}
		}
		if _, err := readUpdateManifest(context.Background(), file, version, client, &recorder{}); err != nil {
			t.Fatal(err)
		}
		if len(*requests) != 2 || (*requests)[0] != releaseManifestURL(m.Version) {
			t.Fatal(*requests)
		}
	}
}

func TestLinuxUpdateRejectsPublisherDriftAndUnavailableMetadata(t *testing.T) {
	for _, kind := range []string{"channel-drift", "tag-drift", "missing-channel", "oversized", "duplicate", "foreign-channel"} {
		t.Run(kind, func(t *testing.T) {
			_, c, _ := channelFixture(t, func(address string, b []byte) (int, []byte) {
				switch kind {
				case "channel-drift":
					if address == LinuxChannelURL {
						return 200, []byte(strings.Replace(string(b), strings.Repeat("a", 40), strings.Repeat("b", 40), 1))
					}
				case "tag-drift":
					if strings.Contains(address, "/git/ref/tags/") {
						return 200, []byte(`{"object":{"type":"commit","sha":"` + strings.Repeat("b", 40) + `"}}`)
					}
				case "missing-channel":
					if address == LinuxChannelURL {
						return 404, []byte("unavailable")
					}
				case "oversized":
					if address == LinuxChannelURL {
						return 200, []byte(strings.Repeat("x", MaxManifestBytes+1))
					}
				case "duplicate":
					if address == LinuxChannelURL {
						return 200, []byte(`{"schema":1,"schema":1}`)
					}
				case "foreign-channel":
					if address == LinuxChannelURL {
						return 200, []byte(strings.Replace(string(b), "linux-host-v1", "go-v1", 1))
					}
				}
				return 200, b
			})
			if _, err := readUpdateManifest(context.Background(), "", "", c, &recorder{}); err == nil {
				t.Fatal("invalid publisher metadata admitted")
			}
		})
	}
}

func TestLinuxVersionsNeverDowngradeOrRewritePublishedVersion(t *testing.T) {
	for _, row := range [][3]string{{"v1.0.1-rc.3", "v1.0.1-rc.2", "1"}, {"v1.0.1", "v1.0.1-rc.99", "1"}, {"v1.0.1-rc.1", "v1.0.1", "-1"}, {"v1.1.0", "v1.0.999", "1"}, {"v1.0.1-rc.2", "v1.0.1-rc.2", "0"}, {"v1.999999999999999999999999.0", "v1.99.0", "1"}} {
		if fmt.Sprint(compareLinuxVersions(row[0], row[1])) != row[2] {
			t.Fatal(row)
		}
	}
	m, _ := manifestFixture()
	next := m
	next.SourceCommit = strings.Repeat("b", 40)
	if validateUpdateTarget(next, m) == nil {
		t.Fatal("same-version source drift admitted")
	}
	next = m
	next.Version = "v1.0.0-rc.1"
	if compareLinuxVersions(next.Version, m.Version) < 0 && validateUpdateTarget(next, m) == nil {
		t.Fatal("downgrade admitted")
	}
	if err := validateUpdateTarget(m, m); err != nil {
		t.Fatal(err)
	}
	next = m
	next.Arch = "arm64"
	if validateUpdateTarget(next, m) == nil {
		t.Fatal("different platform admitted")
	}
}

func TestLinuxPreviewApprovalIsExplicitAndDurable(t *testing.T) {
	for _, row := range []struct {
		version, input     string
		allowed, yes, want bool
		failed             bool
	}{
		{"v1.0.1-rc.3", "", false, true, false, true},
		{"v1.0.1-rc.3", "", false, false, false, true},
		{"v1.0.1-rc.3", "n\n", false, false, false, true},
		{"v1.0.1-rc.3", "y\n", false, false, true, false},
		{"v1.0.1-rc.3", "", true, true, true, false},
		{"v1.0.1", "", false, true, false, false},
	} {
		var out strings.Builder
		got, err := approveLinuxPreview(row.version, row.allowed, row.yes, strings.NewReader(row.input), &out)
		if got != row.want || (err != nil) != row.failed {
			t.Fatal(row, got, err)
		}
		if row.input == "y\n" && !strings.Contains(out.String(), "future linux-host-v1 previews") {
			t.Fatal(out.String())
		}
	}
	var old nativeReceipt
	if err := json.Unmarshal([]byte(`{"schema":1}`), &old); err != nil || old.AllowPrerelease {
		t.Fatal("old receipt inferred preview approval", err)
	}
	for _, allowed := range []bool{false, true} {
		f := newNativeFixture(t)
		f.a.allowPrerelease = allowed
		f.install(t)
		r, err := f.a.installed(context.Background())
		if err != nil || r.AllowPrerelease != allowed {
			t.Fatal("install preview consent lost", r, err)
		}
		setFixtureRelease(&f.m, "v1.0.1-rc.11")
		f.a.allowPrerelease = false
		dir, receipt := nativePreparedFixture(t, f.m)
		if err := f.a.replacePrepared(context.Background(), f.m, dir, receipt, r); err != nil {
			t.Fatal(err)
		}
		var replaced nativeReceipt
		if err := f.a.read("etc/awf/install.json", &replaced); err != nil || replaced.AllowPrerelease != allowed {
			t.Fatal("update preview consent lost", err)
		}
	}
}

func TestLinuxCurrentVersionPersistsOnlyNewPreviewApproval(t *testing.T) {
	f := newNativeFixture(t)
	f.install(t)
	ctx := context.Background()
	before, err := f.a.installed(ctx)
	if err != nil || before.AllowPrerelease {
		t.Fatal("fixture inferred preview approval", err)
	}
	if err := f.a.writeNew("etc/awf/update-pending.json", []byte(`{"schema":1}`), 0600); err != nil {
		t.Fatal(err)
	}
	f.a.allowPrerelease = true
	if err := f.a.update(ctx, f.m); err == nil {
		t.Fatal("new consent bypassed pending update")
	}
	var pending nativeReceipt
	if err := f.a.read("etc/awf/install.json", &pending); err != nil || pending.AllowPrerelease {
		t.Fatal("pending refusal wrote receipt", err)
	}
	if err := f.a.root.Remove("etc/awf/update-pending.json"); err != nil {
		t.Fatal(err)
	}
	f.commands = nil
	if err := f.a.update(ctx, f.m); err != nil {
		t.Fatal(err)
	}
	after, err := f.a.installed(ctx)
	before.AllowPrerelease = true
	if err != nil || !reflect.DeepEqual(before, after) {
		t.Fatal("current consent did not preserve receipt fields", err)
	}
	receiptPath := filepath.Join(f.dir, "etc/awf/install.json")
	identity, err := os.Stat(receiptPath)
	if err != nil {
		t.Fatal(err)
	}
	f.a.allowPrerelease = false
	if err := f.a.update(ctx, f.m); err != nil {
		t.Fatal(err)
	}
	current, err := os.Stat(receiptPath)
	if err != nil || !os.SameFile(identity, current) {
		t.Fatal("approved current-version check rewrote receipt", err)
	}
	for _, command := range f.commands {
		if strings.Contains(command, "systemctl") || strings.Contains(command, "npm") {
			t.Fatal("current-version consent invoked machine mutation", command)
		}
	}
}

func TestLinuxBackupConflictRefusedBeforeAnyProgramReplacement(t *testing.T) {
	f := newNativeFixture(t)
	f.install(t)
	old, err := f.a.installed(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	setFixtureRelease(&f.m, "v1.0.1-rc.11")
	dir, receipt := nativePreparedFixture(t, f.m)
	backup := filepath.Join(f.dir, "opt/awf.before-"+manifestDigest(f.m))
	if err := os.Mkdir(backup, 0755); err != nil {
		t.Fatal(err)
	}
	before, err := os.Stat(filepath.Join(f.dir, "opt/node"))
	if err != nil {
		t.Fatal(err)
	}
	if err := f.a.replacePrepared(context.Background(), f.m, dir, receipt, old); err == nil {
		t.Fatal("backup conflict admitted")
	}
	after, err := os.Stat(filepath.Join(f.dir, "opt/node"))
	if err != nil || !os.SameFile(before, after) {
		t.Fatal("first program moved before later conflict", err)
	}
}
