package lifecycle

import (
	"archive/zip"
	"bytes"
	"context"
	"crypto/sha256"
	encodingbinary "encoding/binary"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func privateReleaseRoot(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	if err := privateRoot(root); err != nil {
		t.Fatalf("protect release fixture root: %v", err)
	}
	return root
}

type archiveFixtureEntry struct {
	name string
	data []byte
	mode os.FileMode
}

func archiveFixture(t *testing.T, entries []archiveFixtureEntry) []byte {
	t.Helper()
	var b bytes.Buffer
	w := zip.NewWriter(&b)
	for _, entry := range entries {
		h := &zip.FileHeader{Name: entry.name, Method: zip.Store}
		h.SetMode(entry.mode)
		f, err := w.CreateHeader(h)
		if err != nil {
			t.Fatal(err)
		}
		if _, err = f.Write(entry.data); err != nil {
			t.Fatal(err)
		}
	}
	if err := w.Close(); err != nil {
		t.Fatal(err)
	}
	return b.Bytes()
}

func peFixture(arch string) []byte {
	b := make([]byte, 128)
	copy(b, "MZ")
	encodingbinary.LittleEndian.PutUint32(b[0x3c:0x40], 64)
	copy(b[64:], "PE\x00\x00")
	machine := uint16(0x8664)
	if arch == "arm64" {
		machine = 0xaa64
	}
	encodingbinary.LittleEndian.PutUint16(b[68:70], machine)
	encodingbinary.LittleEndian.PutUint16(b[88:90], 0x20b)
	return b
}

func releaseEntries(v, arch string) []archiveFixtureEntry {
	return []archiveFixtureEntry{
		{"awf.exe", peFixture(arch), 0700},
		{"awf-node.exe", peFixture(arch), 0700},
		{"manifest.json", []byte(fmt.Sprintf(`{"version":%q,"os":"windows","arch":%q}`, v, arch)), 0600},
	}
}

func noStagingDirectories(t *testing.T, root string) {
	t.Helper()
	entries, err := os.ReadDir(filepath.Join(root, "versions"))
	if os.IsNotExist(err) {
		return
	}
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		if strings.HasPrefix(entry.Name(), ".stage-") {
			t.Errorf("staging directory leaked: %s", entry.Name())
		}
	}
}

func TestStageArchiveRejectsUnsafeEntries(t *testing.T) {
	cases := []struct {
		name   string
		mutate func([]archiveFixtureEntry) []archiveFixtureEntry
	}{
		{"parent traversal", func(e []archiveFixtureEntry) []archiveFixtureEntry { e[0].name = "../awf.exe"; return e }},
		{"absolute path", func(e []archiveFixtureEntry) []archiveFixtureEntry { e[0].name = "/awf.exe"; return e }},
		{"windows traversal", func(e []archiveFixtureEntry) []archiveFixtureEntry { e[0].name = `..\awf.exe`; return e }},
		{"windows drive", func(e []archiveFixtureEntry) []archiveFixtureEntry { e[0].name = `C:\awf.exe`; return e }},
		{"alternate stream", func(e []archiveFixtureEntry) []archiveFixtureEntry { e[0].name = "awf.exe:extra"; return e }},
		{"nested path", func(e []archiveFixtureEntry) []archiveFixtureEntry { e[0].name = "bin/awf.exe"; return e }},
		{"case collision", func(e []archiveFixtureEntry) []archiveFixtureEntry { e[1].name = "AWF.EXE"; return e }},
		{"duplicate", func(e []archiveFixtureEntry) []archiveFixtureEntry { e[1].name = e[0].name; return e }},
		{"symbolic link", func(e []archiveFixtureEntry) []archiveFixtureEntry {
			e[0].mode = os.ModeSymlink | 0777
			e[0].data = []byte("../outside")
			return e
		}},
		{"directory", func(e []archiveFixtureEntry) []archiveFixtureEntry { e[0].mode = os.ModeDir | 0700; return e }},
		{"missing binary", func(e []archiveFixtureEntry) []archiveFixtureEntry { return e[:2] }},
		{"extra entry", func(e []archiveFixtureEntry) []archiveFixtureEntry {
			return append(e, archiveFixtureEntry{"README.txt", []byte("extra"), 0600})
		}},
		{"non PE executable", func(e []archiveFixtureEntry) []archiveFixtureEntry { e[0].data = []byte("#!/bin/sh"); return e }},
		{"empty executable", func(e []archiveFixtureEntry) []archiveFixtureEntry { e[1].data = nil; return e }},
		{"malformed manifest", func(e []archiveFixtureEntry) []archiveFixtureEntry { e[2].data = []byte("{"); return e }},
		{"wrong version", func(e []archiveFixtureEntry) []archiveFixtureEntry {
			e[2] = releaseEntries("v9.0.0", "amd64")[2]
			return e
		}},
		{"wrong architecture", func(e []archiveFixtureEntry) []archiveFixtureEntry {
			e[2] = releaseEntries("v1.2.3", "arm64")[2]
			return e
		}},
		{"wrong OS", func(e []archiveFixtureEntry) []archiveFixtureEntry {
			e[2].data = []byte(`{"version":"v1.2.3","os":"linux","arch":"amd64"}`)
			return e
		}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			root := privateReleaseRoot(t)
			outside := filepath.Join(root, "awf.exe")
			if err := os.WriteFile(outside, []byte("preserve me"), 0600); err != nil {
				t.Fatal(err)
			}
			if err := stageArchive(root, "v1.2.3", "amd64", archiveFixture(t, tc.mutate(releaseEntries("v1.2.3", "amd64")))); err == nil {
				t.Fatal("unsafe archive accepted")
			}
			if _, err := os.Stat(filepath.Join(root, "versions", "v1.2.3")); !os.IsNotExist(err) {
				t.Fatalf("failed archive published a version: %v", err)
			}
			if got, err := os.ReadFile(outside); err != nil || string(got) != "preserve me" {
				t.Fatalf("outside sentinel changed: %q, %v", got, err)
			}
			noStagingDirectories(t, root)
		})
	}
}

func TestStageArchiveRejectsOversizedDeclaredEntry(t *testing.T) {
	b := archiveFixture(t, releaseEntries("v1.2.3", "amd64"))
	// Change the central directory size without allocating a decompression bomb.
	i := bytes.Index(b, []byte{'P', 'K', 1, 2})
	if i < 0 {
		t.Fatal("fixture lacks central directory")
	}
	encodingbinary.LittleEndian.PutUint32(b[i+24:i+28], uint32(maxReleaseBytes+1))
	root := privateReleaseRoot(t)
	if err := stageArchive(root, "v1.2.3", "amd64", b); err == nil || !strings.Contains(err.Error(), "oversized") {
		t.Fatalf("oversized entry guard: %v", err)
	}
	noStagingDirectories(t, root)
}

func TestStageArchiveRejectsInvalidZIPAndVersion(t *testing.T) {
	for _, payload := range [][]byte{nil, []byte("not a ZIP"), {'P', 'K', 3, 4}} {
		if err := stageArchive(privateReleaseRoot(t), "v1.2.3", "amd64", payload); err == nil {
			t.Fatal("invalid ZIP accepted")
		}
	}
	for _, v := range []string{"", "latest", "1.2.3", "v1.2", "v1.2.3-beta.1", "v1.2.3+meta", "../v1.2.3", "v1.2.3\n"} {
		if err := stageArchive(privateReleaseRoot(t), v, "amd64", archiveFixture(t, releaseEntries(v, "amd64"))); err == nil {
			t.Fatalf("invalid version accepted: %q", v)
		}
	}
}

func TestStageArchivePreservesInstalledTag(t *testing.T) {
	root := privateReleaseRoot(t)
	payload := archiveFixture(t, releaseEntries("v1.2.3", "amd64"))
	if err := stageArchive(root, "v1.2.3", "amd64", payload); err != nil {
		t.Fatal(err)
	}
	if err := stageArchive(root, "v1.2.3", "amd64", payload); err != nil {
		t.Fatalf("byte-identical reinstall rejected: %v", err)
	}
	changed := releaseEntries("v1.2.3", "amd64")
	changed[0].data[100] = 1
	if err := stageArchive(root, "v1.2.3", "amd64", archiveFixture(t, changed)); err == nil {
		t.Fatal("mutable release tag overwritten")
	}
	got, err := os.ReadFile(binary(root, "v1.2.3"))
	if err != nil || !bytes.Equal(got, releaseEntries("v1.2.3", "amd64")[0].data) {
		t.Fatalf("existing binary changed: %q, %v", got, err)
	}
	noStagingDirectories(t, root)
}

func TestChecksumRejectsMalformedOrAmbiguousInput(t *testing.T) {
	digest := strings.Repeat("a", 64)
	name := "awf_v1.2.3_windows_amd64.zip"
	for _, data := range []string{"", digest + " other.zip", "bad " + name, strings.Repeat("a", 62) + " " + name, digest + " " + name + " extra", digest + " " + name + "\n" + digest + " *" + name, digest + " " + name + "\ninvalid unrelated.zip"} {
		if _, err := checksum([]byte(data), name); err == nil {
			t.Fatalf("invalid checksums accepted: %q", data)
		}
	}
	got, err := checksum([]byte(strings.ToUpper(digest)+" *"+name+"\r\n"), name)
	if err != nil || got != digest {
		t.Fatalf("valid checksum = %q, %v", got, err)
	}
	payload := []byte("fixture")
	sum := sha256.Sum256(payload)
	good := hex.EncodeToString(sum[:])
	if err := verifyDigest(payload, good); err != nil {
		t.Fatal(err)
	}
	for _, bad := range []string{"", strings.Repeat("g", 64), good[:63], good + "0", strings.Repeat("0", 64)} {
		if err := verifyDigest(payload, bad); err == nil {
			t.Fatalf("invalid digest accepted: %q", bad)
		}
	}
}

type fixtureTransport func(*http.Request) (*http.Response, error)

func (f fixtureTransport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func TestStageReleaseRequiresPinnedOfficialMetadata(t *testing.T) {
	const v = "v1.2.3"
	name := assetName(v, "amd64")
	payload := archiveFixture(t, releaseEntries(v, "amd64"))
	sum := sha256.Sum256(payload)
	digest := hex.EncodeToString(sum[:])
	cases := []struct {
		name, requested, arch, pin string
		mutate                     func(*releaseInfo)
		sums                       string
		payload                    []byte
		wantOK                     bool
	}{
		{name: "exact release", requested: v, arch: "amd64", wantOK: true},
		{name: "channel resolves exact tag", arch: "amd64", wantOK: true},
		{name: "matching independent pin", requested: v, arch: "amd64", pin: strings.ToUpper(digest), wantOK: true},
		{name: "invalid requested tag", requested: "../latest", arch: "amd64"},
		{name: "unsupported architecture", requested: v, arch: "386"},
		{name: "draft", requested: v, arch: "amd64", mutate: func(r *releaseInfo) { r.Draft = true }},
		{name: "prerelease", requested: v, arch: "amd64", mutate: func(r *releaseInfo) { r.Prerelease = true }},
		{name: "unstable tag", arch: "amd64", mutate: func(r *releaseInfo) { r.Tag = "v1.2.3-rc.1" }},
		{name: "tag mismatch", requested: v, arch: "amd64", mutate: func(r *releaseInfo) { r.Tag = "v1.2.4" }},
		{name: "missing ZIP", requested: v, arch: "amd64", mutate: func(r *releaseInfo) { r.Assets = r.Assets[1:] }},
		{name: "missing checksums", requested: v, arch: "amd64", mutate: func(r *releaseInfo) { r.Assets = r.Assets[:1] }},
		{name: "duplicate ZIP", requested: v, arch: "amd64", mutate: func(r *releaseInfo) { r.Assets = append(r.Assets, r.Assets[0]) }},
		{name: "duplicate sums", requested: v, arch: "amd64", mutate: func(r *releaseInfo) { r.Assets = append(r.Assets, r.Assets[1]) }},
		{name: "foreign host", requested: v, arch: "amd64", mutate: func(r *releaseInfo) { r.Assets[0].URL = "https://example.invalid/" + name }},
		{name: "HTTP downgrade", requested: v, arch: "amd64", mutate: func(r *releaseInfo) { r.Assets[0].URL = strings.Replace(r.Assets[0].URL, "https:", "http:", 1) }},
		{name: "asset URL query", requested: v, arch: "amd64", mutate: func(r *releaseInfo) { r.Assets[0].URL += "?source=other" }},
		{name: "foreign repository", requested: v, arch: "amd64", mutate: func(r *releaseInfo) {
			r.Assets[0].URL = strings.Replace(r.Assets[0].URL, Repository, "someone/else", 1)
		}},
		{name: "checksum absent", requested: v, arch: "amd64", sums: digest + " other.zip"},
		{name: "checksum malformed", requested: v, arch: "amd64", sums: "invalid " + name},
		{name: "checksum duplicate", requested: v, arch: "amd64", sums: digest + " " + name + "\n" + digest + " " + name},
		{name: "wrong pin", requested: v, arch: "amd64", pin: strings.Repeat("0", 64)},
		{name: "truncated pin", requested: v, arch: "amd64", pin: digest[:63]},
		{name: "payload digest mismatch", requested: v, arch: "amd64", payload: []byte("tampered")},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			root := privateReleaseRoot(t)
			r := releaseInfo{Tag: v, TargetCommitish: fixtureSourceCommit, Assets: []releaseAsset{{name, officialAsset(v, name)}, {"SHA256SUMS", officialAsset(v, "SHA256SUMS")}}}
			if tc.mutate != nil {
				tc.mutate(&r)
			}
			metadata, err := json.Marshal(r)
			if err != nil {
				t.Fatal(err)
			}
			sums := tc.sums
			if sums == "" {
				sums = digest + " " + name + "\n"
			}
			body := tc.payload
			if body == nil {
				body = payload
			}
			requests := 0
			client := &http.Client{Transport: fixtureTransport(func(req *http.Request) (*http.Response, error) {
				requests++
				if req.Method != "GET" || req.URL.Scheme != "https" {
					t.Fatalf("unexpected request: %s %s", req.Method, req.URL)
				}
				var b []byte
				switch req.URL.String() {
				case channelManifestURL:
					b = fixtureChannelManifest(v, digest)
				case releaseRefURL(v):
					b = fixtureReleaseRef(v, fixtureSourceCommit)
				case releaseMetadataURL(v):
					b = metadata
				case officialAsset(v, "SHA256SUMS"):
					b = []byte(sums)
				case officialAsset(v, name):
					b = body
				default:
					t.Fatalf("unexpected release request: %s", req.URL)
				}
				return &http.Response{StatusCode: 200, Body: io.NopCloser(bytes.NewReader(b)), Header: make(http.Header)}, nil
			})}
			got, err := stageRelease(context.Background(), client, root, tc.requested, tc.arch, tc.pin, false, "")
			if tc.wantOK {
				if err != nil || got != v {
					t.Fatalf("stage = %q, %v", got, err)
				}
				wantRequests := 4
				if tc.requested == "" {
					wantRequests++
				}
				if requests != wantRequests {
					t.Fatalf("wanted exactly channel (when unpinned), metadata, tag ref, checksum, payload requests; got %d", requests)
				}
			} else {
				if err == nil {
					t.Fatal("unsafe release accepted")
				}
				if _, err := os.Stat(filepath.Join(root, "versions", v)); !os.IsNotExist(err) {
					t.Fatalf("rejected release published: %v", err)
				}
				if (tc.name == "invalid requested tag" || tc.name == "unsupported architecture") && requests != 0 {
					t.Fatal("invalid request accessed network")
				}
			}
			noStagingDirectories(t, root)
		})
	}
}

func TestFetchIsBoundedAndRequiresHTTPS(t *testing.T) {
	requests := 0
	client := &http.Client{Transport: fixtureTransport(func(r *http.Request) (*http.Response, error) {
		requests++
		return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader("123456789")), Header: make(http.Header)}, nil
	})}
	for _, address := range []string{"http://github.com/file", "https://user:pass@github.com/file", "file:///tmp/release", "://bad"} {
		if _, err := fetch(context.Background(), client, address, 8); err == nil {
			t.Fatalf("unsafe URL accepted: %s", address)
		}
	}
	if requests != 0 {
		t.Fatal("unsafe URL reached transport")
	}
	if _, err := fetch(context.Background(), client, "https://github.com/file", 8); err == nil {
		t.Fatal("oversized response accepted")
	}
	got, err := fetch(context.Background(), client, "https://github.com/file", 9)
	if err != nil || string(got) != "123456789" {
		t.Fatalf("exact limit response = %q, %v", got, err)
	}
	client.Transport = fixtureTransport(func(r *http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: 404, Body: io.NopCloser(strings.NewReader("missing")), Header: make(http.Header)}, nil
	})
	if _, err := fetch(context.Background(), client, "https://github.com/file", 9); err == nil {
		t.Fatal("non-200 response accepted")
	}
}

func TestReleaseRedirectAllowlist(t *testing.T) {
	client := releaseClient()
	for _, address := range []string{"https://github.com/a", "https://release-assets.githubusercontent.com/a", "https://objects.githubusercontent.com/a"} {
		u, _ := url.Parse(address)
		if err := client.CheckRedirect(&http.Request{URL: u}, nil); err != nil {
			t.Fatalf("official redirect rejected: %s: %v", address, err)
		}
	}
	for _, address := range []string{"http://github.com/a", "https://evil.invalid/a", "https://github.com.evil.invalid/a", "https://user@github.com/a", "https://github.com:444/a"} {
		u, _ := url.Parse(address)
		if err := client.CheckRedirect(&http.Request{URL: u}, nil); err == nil {
			t.Fatalf("unsafe redirect accepted: %s", address)
		}
	}
	u, _ := url.Parse("https://github.com/a")
	if err := client.CheckRedirect(&http.Request{URL: u}, make([]*http.Request, 6)); err == nil {
		t.Fatal("redirect limit not enforced")
	}
}

func TestValidatePERejectsMalformedOrMismatchedMachine(t *testing.T) {
	for _, arch := range []string{"amd64", "arm64"} {
		if err := validatePE(peFixture(arch), arch); err != nil {
			t.Fatalf("valid %s header: %v", arch, err)
		}
	}
	cases := []struct {
		name, arch string
		mutate     func([]byte) []byte
	}{
		{"unsupported architecture", "386", func(b []byte) []byte { return b }},
		{"wrong machine", "arm64", func(b []byte) []byte { return b }},
		{"truncated DOS header", "amd64", func(b []byte) []byte { return b[:63] }},
		{"not MZ", "amd64", func(b []byte) []byte { b[0] = 'X'; return b }},
		{"not PE", "amd64", func(b []byte) []byte { b[64] = 'X'; return b }},
		{"overlapping offset", "amd64", func(b []byte) []byte { encodingbinary.LittleEndian.PutUint32(b[0x3c:0x40], 0); return b }},
		{"out of range offset", "amd64", func(b []byte) []byte { encodingbinary.LittleEndian.PutUint32(b[0x3c:0x40], 0xffffffff); return b }},
		{"truncated machine", "amd64", func(b []byte) []byte { return b[:69] }},
		{"truncated optional header", "amd64", func(b []byte) []byte { return b[:89] }},
		{"PE32 optional header", "amd64", func(b []byte) []byte { encodingbinary.LittleEndian.PutUint16(b[88:90], 0x10b); return b }},
		{"missing optional header magic", "amd64", func(b []byte) []byte { b[88], b[89] = 0, 0; return b }},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if err := validatePE(tc.mutate(peFixture("amd64")), tc.arch); err == nil {
				t.Fatal("unsafe PE accepted")
			}
		})
	}
	entries := releaseEntries("v1.2.3", "amd64")
	entries[1].data = peFixture("arm64")
	if err := stageArchive(privateReleaseRoot(t), "v1.2.3", "amd64", archiveFixture(t, entries)); err == nil {
		t.Fatal("manifest architecture hid wrong node binary machine")
	}
}

func TestStageArchiveRejectsAmbiguousOrOversizedManifest(t *testing.T) {
	for _, tc := range []struct{ name, manifest string }{
		{"duplicate version", `{"version":"v9.9.9","version":"v1.2.3","os":"windows","arch":"amd64"}`},
		{"duplicate architecture", `{"version":"v1.2.3","os":"windows","arch":"arm64","arch":"amd64"}`},
		{"unknown field", `{"version":"v1.2.3","os":"windows","arch":"amd64","entrypoint":"other.exe"}`},
		{"trailing object", `{"version":"v1.2.3","os":"windows","arch":"amd64"}{}`},
		{"null", `null`},
		{"array", `[]`},
		{"wrong type", `{"version":"v1.2.3","os":"windows","arch":123}`},
		{"missing architecture", `{"version":"v1.2.3","os":"windows"}`},
		{"oversized", `{"version":"v1.2.3","os":"windows","arch":"amd64"}` + strings.Repeat(" ", 4<<10)},
	} {
		t.Run(tc.name, func(t *testing.T) {
			root := privateReleaseRoot(t)
			entries := releaseEntries("v1.2.3", "amd64")
			entries[2].data = []byte(tc.manifest)
			if err := stageArchive(root, "v1.2.3", "amd64", archiveFixture(t, entries)); err == nil {
				t.Fatal("unsafe manifest accepted")
			}
			if _, err := os.Stat(filepath.Join(root, "versions", "v1.2.3")); !os.IsNotExist(err) {
				t.Fatalf("unsafe manifest published: %v", err)
			}
			noStagingDirectories(t, root)
		})
	}
}

func TestStageArchiveRejectsCorruptEntryCRC(t *testing.T) {
	payload := archiveFixture(t, releaseEntries("v1.2.3", "amd64"))
	// The fixture uses Store compression. Corrupt its payload while retaining the
	// ZIP checksums, proving extraction errors cannot publish partially read data.
	i := bytes.Index(payload, peFixture("amd64"))
	if i < 0 {
		t.Fatal("fixture payload not found")
	}
	payload[i+100] ^= 0xff
	root := privateReleaseRoot(t)
	if err := stageArchive(root, "v1.2.3", "amd64", payload); err == nil {
		t.Fatal("corrupt ZIP entry accepted")
	}
	if _, err := os.Stat(filepath.Join(root, "versions", "v1.2.3")); !os.IsNotExist(err) {
		t.Fatalf("corrupt ZIP published: %v", err)
	}
	noStagingDirectories(t, root)
}

func TestStageArchiveRejectsTotalExpandedSizeBeforeExtraction(t *testing.T) {
	payload := archiveFixture(t, releaseEntries("v1.2.3", "amd64"))
	central := []byte{'P', 'K', 1, 2}
	first := bytes.Index(payload, central)
	if first < 0 {
		t.Fatal("first central directory entry missing")
	}
	secondRelative := bytes.Index(payload[first+4:], central)
	if secondRelative < 0 {
		t.Fatal("second central directory entry missing")
	}
	second := first + 4 + secondRelative
	// Each executable is individually within its limit; together with the
	// manifest, the declared expansion exceeds 100 MiB. No large buffer is needed.
	encodingbinary.LittleEndian.PutUint32(payload[first+24:first+28], uint32(maxReleaseBytes/2))
	encodingbinary.LittleEndian.PutUint32(payload[second+24:second+28], uint32(maxReleaseBytes/2))
	root := privateReleaseRoot(t)
	err := stageArchive(root, "v1.2.3", "amd64", payload)
	if err == nil || !strings.Contains(err.Error(), "expanded") {
		t.Fatalf("aggregate size preflight not enforced: %v", err)
	}
	if _, err := os.Stat(filepath.Join(root, "versions", "v1.2.3")); !os.IsNotExist(err) {
		t.Fatalf("oversized ZIP published: %v", err)
	}
	noStagingDirectories(t, root)
}

func TestStageArchiveRejectsDOSReparseAndDirectoryAttributes(t *testing.T) {
	for _, attr := range []uint32{0x400, 0x10} {
		t.Run(fmt.Sprintf("attribute_%x", attr), func(t *testing.T) {
			payload := archiveFixture(t, releaseEntries("v1.2.3", "amd64"))
			i := bytes.Index(payload, []byte{'P', 'K', 1, 2})
			if i < 0 {
				t.Fatal("central directory missing")
			}
			existing := encodingbinary.LittleEndian.Uint32(payload[i+38 : i+42])
			encodingbinary.LittleEndian.PutUint32(payload[i+38:i+42], existing|attr)
			root := privateReleaseRoot(t)
			if err := stageArchive(root, "v1.2.3", "amd64", payload); err == nil {
				t.Fatal("DOS reparse/directory entry accepted")
			}
			if _, err := os.Stat(filepath.Join(root, "versions", "v1.2.3")); !os.IsNotExist(err) {
				t.Fatalf("unsafe attribute published: %v", err)
			}
			noStagingDirectories(t, root)
		})
	}
}
