package lifecycle

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestCanonicalRCVersionAndExplicitPolicy(t *testing.T) {
	for _, v := range []string{"v0.0.0", "v1.2.3", "v1.2.3-rc.0", "v1.2.3-rc.1", "v12.345.678-rc.999"} {
		if e := validVersion(v); e != nil {
			t.Fatalf("canonical version %q: %v", v, e)
		}
		if e := validateReleaseRequest(v, true); e != nil {
			t.Fatalf("explicit version %q: %v", v, e)
		}
		if e := validateReleaseRequest(v, false); (e != nil) != prereleaseVersion(v) {
			t.Fatalf("default policy %q: %v", v, e)
		}
	}
	for _, v := range []string{"latest", "v1.2.3-rc", "v1.2.3-rc.", "v1.2.3-rc.01", "v1.2.3-rc.-1", "v1.2.3-RC.1", "v1.2.3-alpha.1", "v1.2.3-beta.1", "v1.2.3-rc.1.more", "v1.2.3-rc.1+build", "v01.2.3-rc.1", "v1.02.3-rc.1", "v1.2.03-rc.1", "../v1.2.3-rc.1", "v1.2.3-rc.1\n"} {
		if e := validVersion(v); e == nil {
			t.Fatalf("noncanonical version %q was accepted", v)
		}
	}
	if e := validateReleaseRequest("", false); e != nil {
		t.Fatal("default latest stable was rejected")
	}
	if e := validateReleaseRequest("", true); e == nil {
		t.Fatal("prerelease opt-in accepted without exact version")
	}
}

func TestReleaseVersionOrderingPreventsImplicitDowngrades(t *testing.T) {
	cases := []struct {
		a, b  string
		order int
	}{
		{"v1.0.0", "v1.0.0", 0},
		{"v1.0.0-rc.1", "v1.0.0", -1},
		{"v1.0.0", "v1.0.0-rc.99", 1},
		{"v1.0.0-rc.10", "v1.0.0-rc.9", 1},
		{"v1.0.0-rc.0", "v1.0.0-rc.1", -1},
		{"v0.9.9", "v1.0.0-rc.1", -1},
		{"v1.10.0", "v1.9.99", 1},
		{"v10.0.0", "v9.999.999", 1},
		{"v1.0.100", "v1.0.99", 1},
		{"v99999999999999999999999999.0.0", "v9999999999999999999999999.9.9", 1},
	}
	for _, tc := range cases {
		got, e := compareReleaseVersions(tc.a, tc.b)
		if e != nil || got != tc.order {
			t.Fatalf("%s vs %s = %d,%v", tc.a, tc.b, got, e)
		}
	}
	if _, e := compareReleaseVersions("unknown", "v1.0.0"); e == nil {
		t.Fatal("unknown current version compared as older")
	}
}

func TestRCInstallIdentityPersistsWithoutBroadeningUpdateDefault(t *testing.T) {
	root := privateReleaseRoot(t)
	const v = "v1.0.0-rc.1"
	if e := stageArchive(root, v, "amd64", archiveFixture(t, releaseEntries(v, "amd64"))); e != nil {
		t.Fatal(e)
	}
	if e := writeJSON(filepath.Join(root, "current.json"), Pointer{Version: v}); e != nil {
		t.Fatal(e)
	}
	if p, e := current(root); e != nil || p.Version != v {
		t.Fatalf("RC pointer: %+v %v", p, e)
	}
	id := strings.Repeat("a", 64)
	if e := createStartup(root, Startup{LaunchID: id, Version: v}); e != nil {
		t.Fatal(e)
	}
	if p, e := readStartup(root); e != nil || p.Version != v {
		t.Fatalf("RC startup: %+v %v", p, e)
	}
	if e := clearStartup(root, id); e != nil {
		t.Fatal(e)
	}
	if e := validateReleaseRequest(v, false); e == nil {
		t.Fatal("installed RC implicitly opted into future prereleases")
	}
}

func TestUnapprovedRCCommandsFailBeforeInstallationOrNetwork(t *testing.T) {
	for _, args := range [][]string{{"--version", "v1.0.0-rc.1"}, {"--version", "v1.0.0-rc.1", "--allow-prerelease=false"}, {"--allow-prerelease"}, {"--version", "latest", "--allow-prerelease"}, {"--version", "v1.0.0-beta.1", "--allow-prerelease"}} {
		root := privateReleaseRoot(t)
		if e := update(root, args, io.Discard); e == nil {
			t.Fatalf("update accepted unsafe options %v", args)
		}
		if e := install(root, args, io.Discard); e == nil {
			t.Fatalf("bootstrap accepted unsafe options %v", args)
		}
		entries, e := os.ReadDir(root)
		if e != nil || len(entries) != 0 {
			t.Fatalf("invalid options changed fixture: %v %v", entries, e)
		}
	}
}

func TestReleaseRCMetadataAndStableLatestSafety(t *testing.T) {
	cases := []struct {
		name, requested, tag, current string
		allow, pre, draft, wantOK     bool
		calls                         int
	}{
		{name: "explicit RC with opt-in", requested: "v1.0.0-rc.1", tag: "v1.0.0-rc.1", allow: true, pre: true, wantOK: true, calls: 3},
		{name: "RC missing opt-in", requested: "v1.0.0-rc.1", tag: "v1.0.0-rc.1", pre: true, calls: 0},
		{name: "opt-in without pin", tag: "v1.0.0-rc.1", allow: true, pre: true, calls: 0},
		{name: "RC tag mislabeled stable", requested: "v1.0.0-rc.1", tag: "v1.0.0-rc.1", allow: true, calls: 1},
		{name: "stable tag mislabeled preview", requested: "v1.0.0", tag: "v1.0.0", allow: true, pre: true, calls: 1},
		{name: "RC draft", requested: "v1.0.0-rc.1", tag: "v1.0.0-rc.1", allow: true, pre: true, draft: true, calls: 1},
		{name: "wrong pinned RC", requested: "v1.0.0-rc.1", tag: "v1.0.0-rc.2", allow: true, pre: true, calls: 1},
		{name: "latest unexpectedly returns RC", tag: "v1.0.0-rc.1", pre: true, calls: 1},
		{name: "latest RC hidden as stable", tag: "v1.0.0-rc.1", calls: 1},
		{name: "latest stable below installed RC", tag: "v0.9.9", current: "v1.0.0-rc.1", calls: 1},
		{name: "latest stable below installed stable", tag: "v1.0.0", current: "v1.0.1", calls: 1},
		{name: "unknown installed identity", tag: "v1.0.0", current: "unknown", calls: 1},
		{name: "RC promotes to final stable", tag: "v1.0.0", current: "v1.0.0-rc.99", wantOK: true, calls: 3},
		{name: "stable latest advances", tag: "v1.1.0", current: "v1.0.0", wantOK: true, calls: 3},
		{name: "stable latest same version", tag: "v1.0.0", current: "v1.0.0", wantOK: true, calls: 3},
		{name: "manual older stable pin", requested: "v0.9.9", tag: "v0.9.9", current: "v1.0.0-rc.1", wantOK: true, calls: 3},
		{name: "manual older RC pin", requested: "v1.0.0-rc.1", tag: "v1.0.0-rc.1", current: "v1.0.0-rc.2", allow: true, pre: true, wantOK: true, calls: 3},
		{name: "stable pin with explicit opt-in remains stable", requested: "v1.0.0", tag: "v1.0.0", allow: true, wantOK: true, calls: 3},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			root := privateReleaseRoot(t)
			name := assetName(tc.tag, "amd64")
			payload := archiveFixture(t, releaseEntries(tc.tag, "amd64"))
			sum := sha256.Sum256(payload)
			digest := hex.EncodeToString(sum[:])
			release := releaseInfo{Tag: tc.tag, Prerelease: tc.pre, Draft: tc.draft, Assets: []releaseAsset{{name, officialAsset(tc.tag, name)}, {"SHA256SUMS", officialAsset(tc.tag, "SHA256SUMS")}}}
			metadata, e := json.Marshal(release)
			if e != nil {
				t.Fatal(e)
			}
			calls := 0
			client := &http.Client{Transport: fixtureTransport(func(req *http.Request) (*http.Response, error) {
				calls++
				var b []byte
				expectedAPI := "https://api.github.com/repos/" + Repository + "/releases/latest"
				if tc.requested != "" {
					expectedAPI = "https://api.github.com/repos/" + Repository + "/releases/tags/" + tc.requested
				}
				switch req.URL.String() {
				case expectedAPI:
					b = metadata
				case officialAsset(tc.tag, "SHA256SUMS"):
					b = []byte(digest + "  " + name + "\n")
				case officialAsset(tc.tag, name):
					b = payload
				default:
					t.Fatalf("unexpected request %s", req.URL)
				}
				return &http.Response{StatusCode: 200, Body: io.NopCloser(bytes.NewReader(b)), Header: make(http.Header)}, nil
			})}
			got, e := stageRelease(context.Background(), client, root, tc.requested, "amd64", "", tc.allow, tc.current)
			if (e == nil) != tc.wantOK {
				t.Fatalf("result %q,%v; wantOK=%t", got, e, tc.wantOK)
			}
			if calls != tc.calls {
				t.Fatalf("requests=%d, want%d", calls, tc.calls)
			}
			if !tc.wantOK {
				entries, e := os.ReadDir(root)
				if e != nil || len(entries) != 0 {
					t.Fatal("rejected release changed installation")
				}
			}
		})
	}
}

func TestWindowsUnapprovedRCBootstrapLeavesNoRoot(t *testing.T) {
	if runtime.GOOS != "windows" {
		t.Skip("native CLI dispatch requires Windows")
	}
	base := t.TempDir()
	t.Setenv("LOCALAPPDATA", base)
	if e := Run([]string{"_install", "--version", "v1.0.0-rc.1"}, strings.NewReader(""), io.Discard); e == nil {
		t.Fatal("native bootstrap accepted RC without opt-in")
	}
	if _, e := os.Stat(filepath.Join(base, "AWF")); !os.IsNotExist(e) {
		t.Fatal("rejected RC bootstrap changed installation root")
	}
}

func TestReleaseMetadataRequiresKnownBooleanFlags(t *testing.T) {
	for _, tag := range []string{"v1.0.0", "v1.0.0-rc.1"} {
		for _, field := range []string{"draft", "prerelease"} {
			for _, kind := range []string{"missing", "null", "string"} {
				t.Run(tag+"/"+field+"/"+kind, func(t *testing.T) {
					metadata := map[string]any{"tag_name": tag, "draft": false, "prerelease": prereleaseVersion(tag), "assets": []any{}}
					switch kind {
					case "missing":
						delete(metadata, field)
					case "null":
						metadata[field] = nil
					case "string":
						metadata[field] = "false"
					}
					b, e := json.Marshal(metadata)
					if e != nil {
						t.Fatal(e)
					}
					calls := 0
					client := &http.Client{Transport: fixtureTransport(func(req *http.Request) (*http.Response, error) {
						calls++
						if calls != 1 || !strings.HasPrefix(req.URL.String(), "https://api.github.com/repos/"+Repository+"/releases/tags/") {
							t.Fatal("unknown metadata reached asset download")
						}
						return &http.Response{StatusCode: 200, Body: io.NopCloser(bytes.NewReader(b)), Header: make(http.Header)}, nil
					})}
					root := privateReleaseRoot(t)
					if _, e = stageRelease(context.Background(), client, root, tag, "amd64", "", true, ""); e == nil {
						t.Fatal("unknown release flags were accepted")
					}
					if calls != 1 {
						t.Fatalf("metadata requests=%d", calls)
					}
					entries, e := os.ReadDir(root)
					if e != nil || len(entries) != 0 {
						t.Fatal("unknown metadata changed installation")
					}
				})
			}
		}
	}
}
