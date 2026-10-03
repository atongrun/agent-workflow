package lifecycle

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

const fixtureSourceCommit = "0123456789abcdef0123456789abcdef01234567"

func fixtureChannelManifest(version, digest string) []byte {
	data, _ := json.Marshal(channelManifest{Schema: "1", Channel: channelName, Version: version, SourceCommit: fixtureSourceCommit, CLIProtocol: "2", WindowsAMD64SHA256: digest, WindowsARM64SHA256: digest})
	return data
}
func fixtureReleaseRef(version, commit string) []byte {
	return []byte(fmt.Sprintf(`{"ref":%q,"object":{"type":"commit","sha":%q}}`, "refs/tags/"+version, commit))
}

func TestChannelManifestStrictPublisherContract(t *testing.T) {
	base := string(fixtureChannelManifest("v1.0.0-rc.2", strings.Repeat("a", 64)))
	for _, protocol := range []string{"1", "2"} {
		if _, err := parseChannelManifest([]byte(strings.Replace(base, `"cliProtocol":"2"`, `"cliProtocol":"`+protocol+`"`, 1))); err != nil {
			t.Fatalf("supported CLI protocol %s: %v", protocol, err)
		}
	}
	for _, version := range []string{"v1.0.0-rc.0", "v1.0.0", "v1.99999999999999999999999.0-rc.999"} {
		if _, err := parseChannelManifest(fixtureChannelManifest(version, strings.Repeat("a", 64))); err != nil {
			t.Fatalf("valid channel version %s: %v", version, err)
		}
	}
	cases := map[string]string{
		"missing schema":       strings.Replace(base, `"schema":"1",`, "", 1),
		"missing protocol":     strings.Replace(base, `"cliProtocol":"2",`, "", 1),
		"missing commit":       strings.Replace(base, `"sourceCommit":"`+fixtureSourceCommit+`",`, "", 1),
		"missing architecture": strings.Replace(base, `,"windowsARM64SHA256":"`+strings.Repeat("a", 64)+`"`, "", 1),
		"unknown field":        strings.Replace(base, "}", `,"url":"https://elsewhere.invalid"}`, 1),
		"duplicate schema":     strings.Replace(base, "}", `,"schema":"1"}`, 1),
		"duplicate commit":     strings.Replace(base, "}", `,"sourceCommit":"`+fixtureSourceCommit+`"}`, 1),
		"case alias":           strings.Replace(base, `"schema"`, `"Schema"`, 1),
		"escaped key":          strings.Replace(base, `"schema"`, `"schem\u0061"`, 1),
		"escaped value":        strings.Replace(base, `"go-v1"`, `"go-v\u0031"`, 1),
		"numeric schema":       strings.Replace(base, `"schema":"1"`, `"schema":1`, 1),
		"numeric protocol":     strings.Replace(base, `"cliProtocol":"2"`, `"cliProtocol":2`, 1),
		"null schema":          strings.Replace(base, `"schema":"1"`, `"schema":null`, 1),
		"boolean channel":      strings.Replace(base, `"channel":"go-v1"`, `"channel":true`, 1),
		"nested value":         strings.Replace(base, `"schema":"1"`, `"schema":{"schema":"1"}`, 1),
		"unknown schema":       strings.Replace(base, `"schema":"1"`, `"schema":"2"`, 1),
		"unknown protocol":     strings.Replace(base, `"cliProtocol":"2"`, `"cliProtocol":"3"`, 1),
		"zero protocol":        strings.Replace(base, `"cliProtocol":"2"`, `"cliProtocol":"0"`, 1),
		"unknown channel":      strings.Replace(base, "go-v1", "stable", 1),
		"uppercase commit":     strings.Replace(base, fixtureSourceCommit, strings.ToUpper(fixtureSourceCommit), 1),
		"short commit":         strings.Replace(base, fixtureSourceCommit, fixtureSourceCommit[:39], 1),
		"commit branch":        strings.Replace(base, fixtureSourceCommit, "awf/go-v1", 1),
		"uppercase digest":     strings.Replace(base, strings.Repeat("a", 64), strings.Repeat("A", 64), 1),
		"invalid digest":       strings.Replace(base, strings.Repeat("a", 64), strings.Repeat("g", 64), 1),
		"short digest":         strings.Replace(base, strings.Repeat("a", 64), strings.Repeat("a", 63), 1),
		"pre-Go version":       strings.Replace(base, "v1.0.0-rc.2", "v0.3.18", 1),
		"future major":         strings.Replace(base, "v1.0.0-rc.2", "v2.0.0", 1),
		"noncanonical version": strings.Replace(base, "v1.0.0-rc.2", "v1.0.0-rc.02", 1),
		"build suffix":         strings.Replace(base, "v1.0.0-rc.2", "v1.0.0+build", 1),
		"empty":                "", "null": "null", "array": "[]", "trailing object": base + "{}", "oversized": base + strings.Repeat(" ", 4096),
		"BOM": "\xef\xbb\xbf" + base,
	}
	for name, data := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := parseChannelManifest([]byte(data)); err == nil {
				t.Fatal("unsafe channel manifest accepted")
			}
		})
	}
}

func TestSavedChannelIsStrictAndLegacyDoesNotAuthorizePreview(t *testing.T) {
	root := privateReleaseRoot(t)
	selection, err := loadChannel(root)
	if err != nil || selection != (ChannelSelection{Schema: "1", Channel: channelName}) {
		t.Fatalf("legacy selection: %+v %v", selection, err)
	}
	for _, approved := range []bool{true, false} {
		want := ChannelSelection{Schema: "1", Channel: channelName, PreviewApproved: approved}
		if err := writeJSON(filepath.Join(root, "channel.json"), want); err != nil {
			t.Fatal(err)
		}
		if got, err := loadChannel(root); err != nil || got != want {
			t.Fatalf("saved selection: %+v %v", got, err)
		}
	}
	for _, data := range []string{
		`{}`, `null`, `[]`, `{"schema":"1","channel":"go-v1"}`,
		`{"schema":1,"channel":"go-v1","previewApproved":false}`,
		`{"schema":"1","channel":"go-v1","previewApproved":"false"}`,
		`{"schema":"1","channel":"go-v1","previewApproved":null}`,
		`{"schema":"1","channel":"go-v1","previewApproved":false,"previewApproved":true}`,
		`{"schema":"1","channel":"go-v1","previewApproved":false,"extra":false}`,
		`{"schema":"1","channel":"go-v1","previewApproved":false}{}`,
		`{"schema":"1","channel":"go-v\u0031","previewApproved":false}`,
		`{"schema":"2","channel":"go-v1","previewApproved":false}`,
		`{"schema":"1","channel":"go-v2","previewApproved":false}`,
		`{"schema":"1","channel":"go-v1","PreviewApproved":false}`,
	} {
		if err := os.WriteFile(filepath.Join(root, "channel.json"), []byte(data), 0600); err != nil {
			t.Fatal(err)
		}
		if _, err := loadChannel(root); err == nil {
			t.Fatalf("invalid saved selection accepted: %s", data)
		}
	}
}

func TestMetadataExactOriginsAndNoRedirects(t *testing.T) {
	calls := 0
	client := &http.Client{Transport: fixtureTransport(func(req *http.Request) (*http.Response, error) {
		calls++
		return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader("{}")), Header: make(http.Header)}, nil
	})}
	for _, address := range []string{
		strings.Replace(channelManifestURL, "https:", "http:", 1),
		strings.Replace(channelManifestURL, "raw.githubusercontent.com", "raw.githubusercontent.com.evil.invalid", 1),
		strings.Replace(channelManifestURL, "raw.githubusercontent.com", "raw.githubusercontent.com:443", 1),
		strings.Replace(channelManifestURL, "/awf/go-v1/", "/main/", 1),
		channelManifestURL + "?x=1", channelManifestURL + "?", channelManifestURL + "#fragment", channelManifestURL + "/",
		strings.Replace(channelManifestURL, "/distribution/", "/%64istribution/", 1),
		"https://user@raw.githubusercontent.com/" + Repository + "/awf/go-v1/distribution/go-v1.json",
		"https://api.github.com/repos/" + Repository + "/releases/latest",
		releaseMetadataURL("v0.3.18"), releaseMetadataURL("v1.0.0") + "?", releaseRefURL("v1.0.0") + "#x",
		strings.Replace(releaseMetadataURL("v1.0.0"), "api.github.com", "api.github.com:443", 1),
		strings.Replace(releaseMetadataURL("v1.0.0"), "v1.0.0", "%761.0.0", 1),
	} {
		if _, err := fetchMetadata(context.Background(), client, address, 4096); err == nil {
			t.Fatalf("unsafe metadata origin accepted: %s", address)
		}
	}
	if calls != 0 {
		t.Fatalf("unsafe URL accessed network %d times", calls)
	}
	for _, address := range []string{channelManifestURL, releaseMetadataURL("v1.0.0-rc.2"), releaseRefURL("v1.0.0")} {
		if _, err := fetchMetadata(context.Background(), client, address, 4096); err != nil {
			t.Fatal(err)
		}
	}
	for _, address := range []string{channelManifestURL, releaseMetadataURL("v1.0.0"), releaseRefURL("v1.0.0")} {
		for _, status := range []int{301, 302, 303, 307, 308} {
			calls = 0
			client.CheckRedirect = func(*http.Request, []*http.Request) error {
				t.Fatal("caller's permissive redirect policy used for metadata")
				return nil
			}
			client.Transport = fixtureTransport(func(req *http.Request) (*http.Response, error) {
				calls++
				return &http.Response{StatusCode: status, Body: io.NopCloser(strings.NewReader("")), Header: http.Header{"Location": []string{officialAsset("v1.0.0", "redirect")}}}, nil
			})
			if _, err := fetchMetadata(context.Background(), client, address, 4096); err == nil || calls != 1 {
				t.Fatalf("metadata redirect %d: calls=%d err=%v", status, calls, err)
			}
		}
	}
}

func TestChannelReleaseCommitAndDigestBinding(t *testing.T) {
	const version = "v1.0.0-rc.2"
	for _, arch := range []string{"amd64", "arm64"} {
		payload := archiveFixture(t, releaseEntries(version, arch))
		sum := sha256.Sum256(payload)
		digest := hex.EncodeToString(sum[:])
		baseManifest := string(fixtureChannelManifest(version, digest))
		name := assetName(version, arch)
		metaBytes, _ := json.Marshal(releaseInfo{Tag: version, TargetCommitish: fixtureSourceCommit, Prerelease: true, Assets: []releaseAsset{{name, officialAsset(version, name)}, {"SHA256SUMS", officialAsset(version, "SHA256SUMS")}}})
		baseMeta := string(metaBytes)
		baseRef := string(fixtureReleaseRef(version, fixtureSourceCommit))
		cases := []struct {
			name, manifest, metadata, ref string
			wantOK                        bool
		}{
			{name: "exact channel source and digest", wantOK: true},
			{name: "release commit mismatch", metadata: strings.Replace(baseMeta, fixtureSourceCommit, strings.Repeat("b", 40), 1)},
			{name: "release missing exact tag key", metadata: strings.Replace(baseMeta, `"tag_name"`, `"TAG_NAME"`, 1)},
			{name: "release duplicate case alias", metadata: strings.Replace(baseMeta, `"tag_name":`, `"TAG_NAME":"`+version+`","tag_name":`, 1)},
			{name: "release Unicode prerelease alias", metadata: strings.Replace(baseMeta, `"prerelease":`, `"prereleaſe":false,"prerelease":`, 1)},
			{name: "release Unicode assets alias", metadata: strings.Replace(baseMeta, `"assets":`, `"aſſets":[],"assets":`, 1)},
			{name: "release Unicode commit alias", metadata: strings.Replace(baseMeta, `"target_commitish":`, `"target_commitiſh":"`+fixtureSourceCommit+`","target_commitish":`, 1)},
			{name: "release missing exact flag key", metadata: strings.Replace(baseMeta, `"draft"`, `"Draft"`, 1)},
			{name: "release commit branch", metadata: strings.Replace(baseMeta, fixtureSourceCommit, "awf/go-v1", 1)},
			{name: "release commit missing", metadata: strings.Replace(baseMeta, `"target_commitish":"`+fixtureSourceCommit+`",`, "", 1)},
			{name: "release commit null", metadata: strings.Replace(baseMeta, `"`+fixtureSourceCommit+`"`, "null", 1)},
			{name: "release duplicate tag", metadata: strings.TrimSuffix(baseMeta, "}") + `,"tag_name":"` + version + `"}`},
			{name: "release duplicate commit", metadata: strings.TrimSuffix(baseMeta, "}") + `,"target_commitish":"` + fixtureSourceCommit + `"}`},
			{name: "tag commit mismatch", ref: strings.Replace(baseRef, fixtureSourceCommit, strings.Repeat("b", 40), 1)},
			{name: "tag missing exact ref key", ref: strings.Replace(baseRef, `"ref"`, `"Ref"`, 1)},
			{name: "tag missing exact object key", ref: strings.Replace(baseRef, `"object"`, `"Object"`, 1)},
			{name: "tag Unicode SHA alias", ref: strings.Replace(baseRef, `"sha":`, `"ſha":"`+fixtureSourceCommit+`","sha":`, 1)},
			{name: "tag missing exact SHA key", ref: strings.Replace(baseRef, `"sha"`, `"SHA"`, 1)},
			{name: "tag duplicate SHA alias", ref: strings.Replace(baseRef, `"sha":`, `"SHA":"`+fixtureSourceCommit+`","sha":`, 1)},
			{name: "annotated tag", ref: strings.Replace(baseRef, `"type":"commit"`, `"type":"tag"`, 1)},
			{name: "wrong ref", ref: strings.Replace(baseRef, "refs/tags/"+version, "refs/tags/v1.0.0-rc.3", 1)},
			{name: "ref missing", ref: strings.Replace(baseRef, `"ref":"refs/tags/`+version+`",`, "", 1)},
			{name: "missing tag object", ref: `{"ref":"refs/tags/` + version + `"}`},
			{name: "null tag object", ref: `{"ref":"refs/tags/` + version + `","object":null}`},
			{name: "duplicate tag object sha", ref: strings.Replace(baseRef, `"sha":`, `"sha":"`+fixtureSourceCommit+`","sha":`, 1)},
			{name: "upper case tag commit", ref: strings.Replace(baseRef, fixtureSourceCommit, strings.ToUpper(fixtureSourceCommit), 1)},
			{name: "manifest digest mismatch", manifest: strings.ReplaceAll(baseManifest, digest, strings.Repeat("b", 64))},
			{name: "manifest commit mismatch", manifest: strings.Replace(baseManifest, fixtureSourceCommit, strings.Repeat("b", 40), 1)},
		}
		for _, tc := range cases {
			t.Run(arch+"/"+tc.name, func(t *testing.T) {
				manifest, metadata, ref := tc.manifest, tc.metadata, tc.ref
				if manifest == "" {
					manifest = baseManifest
				}
				if metadata == "" {
					metadata = baseMeta
				}
				if ref == "" {
					ref = baseRef
				}
				archiveRequested := false
				client := &http.Client{Transport: fixtureTransport(func(req *http.Request) (*http.Response, error) {
					var body []byte
					switch req.URL.String() {
					case channelManifestURL:
						body = []byte(manifest)
					case releaseMetadataURL(version):
						body = []byte(metadata)
					case releaseRefURL(version):
						body = []byte(ref)
					case officialAsset(version, "SHA256SUMS"):
						body = []byte(digest + "  " + name + "\n")
					case officialAsset(version, name):
						archiveRequested = true
						body = payload
					default:
						t.Fatalf("unexpected URL including forbidden latest: %s", req.URL)
					}
					return &http.Response{StatusCode: 200, Body: io.NopCloser(bytes.NewReader(body)), Header: make(http.Header)}, nil
				})}
				root := privateReleaseRoot(t)
				got, err := stageRelease(context.Background(), client, root, "", arch, "", true, "v1.0.0-rc.1")
				if (err == nil) != tc.wantOK {
					t.Fatalf("stage=%s err=%v wantOK=%v", got, err, tc.wantOK)
				}
				if !tc.wantOK && archiveRequested {
					t.Fatal("unsafe metadata reached archive download")
				}
			})
		}
	}
}

func TestChannelPreviewConfirmation(t *testing.T) {
	for _, tc := range []struct {
		name, version, answer                                             string
		approved, explicit, interactive, wantOK, wantApproved, wantPrompt bool
	}{
		{name: "noninteractive rejected", version: "v1.0.0-rc.2"},
		{name: "piped yes rejected", version: "v1.0.0-rc.2", answer: "yes\n"},
		{name: "explicit durable approval", version: "v1.0.0-rc.2", explicit: true, wantOK: true, wantApproved: true},
		{name: "saved durable approval", version: "v1.0.0-rc.2", approved: true, wantOK: true, wantApproved: true},
		{name: "console yes", version: "v1.0.0-rc.2", answer: "yes\n", interactive: true, wantOK: true, wantApproved: true, wantPrompt: true},
		{name: "console uppercase", version: "v1.0.0-rc.2", answer: "Y\n", interactive: true, wantOK: true, wantApproved: true, wantPrompt: true},
		{name: "console no", version: "v1.0.0-rc.2", answer: "n\n", interactive: true, wantPrompt: true},
		{name: "console empty", version: "v1.0.0-rc.2", answer: "\n", interactive: true, wantPrompt: true},
		{name: "console EOF", version: "v1.0.0-rc.2", answer: "yes", interactive: true, wantPrompt: true},
		{name: "console unrecognized", version: "v1.0.0-rc.2", answer: "sure\n", interactive: true, wantPrompt: true},
		{name: "console oversized", version: "v1.0.0-rc.2", answer: strings.Repeat(" ", 128) + "yes\n", interactive: true, wantPrompt: true},
		{name: "stable no consent", version: "v1.0.0", wantOK: true},
		{name: "stable explicit consent persists", version: "v1.0.0", explicit: true, wantOK: true, wantApproved: true},
		{name: "stable saved consent persists", version: "v1.0.0", approved: true, wantOK: true, wantApproved: true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			selection := ChannelSelection{Schema: "1", Channel: channelName, PreviewApproved: tc.approved}
			var out bytes.Buffer
			got, err := approveChannelPreview(selection, tc.version, tc.explicit, strings.NewReader(tc.answer), &out, tc.interactive)
			if (err == nil) != tc.wantOK || got.PreviewApproved != tc.wantApproved {
				t.Fatalf("consent=%+v err=%v", got, err)
			}
			prompts := strings.Count(out.String(), "[y/N]")
			if tc.wantPrompt && prompts != 1 || !tc.wantPrompt && prompts != 0 {
				t.Fatalf("wrong prompt count: %q", out.String())
			}
		})
	}
	if interactiveUpdateInput(strings.NewReader("yes\n")) {
		t.Fatal("piped reader identified as console")
	}
}

// A same-version release exercises channel migration and saved consent without
// executing the inert Windows PE fixture on a test host.
func TestUpdateChannelMigrationAndConsent(t *testing.T) {
	for _, tc := range []struct {
		name, version, saved string
		args                 []string
		wantOK, wantApproved bool
		wantCalls            int
	}{
		{name: "legacy stable migrates", version: "v1.0.0", wantOK: true, wantCalls: 5},
		{name: "legacy RC does not imply approval", version: "v1.0.0-rc.2", wantCalls: 1},
		{name: "legacy explicit channel opt-in", version: "v1.0.0-rc.2", args: []string{"--allow-prerelease"}, wantOK: true, wantApproved: true, wantCalls: 5},
		{name: "saved channel preview approval", version: "v1.0.0-rc.2", saved: `{"schema":"1","channel":"go-v1","previewApproved":true}`, wantOK: true, wantApproved: true, wantCalls: 5},
		{name: "saved stable does not approve RC", version: "v1.0.0-rc.2", saved: `{"schema":"1","channel":"go-v1","previewApproved":false}`, wantCalls: 1},
		{name: "stable retains preview approval", version: "v1.0.0", saved: `{"schema":"1","channel":"go-v1","previewApproved":true}`, wantOK: true, wantApproved: true, wantCalls: 5},
		{name: "stable explicit future opt-in", version: "v1.0.0", args: []string{"--allow-prerelease"}, wantOK: true, wantApproved: true, wantCalls: 5},
		{name: "unknown saved channel rejected", version: "v1.0.0", saved: `{"schema":"1","channel":"go-v2","previewApproved":true}`},
		{name: "malformed saved channel rejected", version: "v1.0.0", saved: `{"schema":"1","channel":"go-v1","previewApproved":"true"}`},
		{name: "explicit pin preserves channel consent", version: "v1.0.0", saved: `{"schema":"1","channel":"go-v1","previewApproved":true}`, args: []string{"--version", "v1.0.0"}, wantOK: true, wantApproved: true, wantCalls: 4},
		{name: "explicit RC pin does not authorize future previews", version: "v1.0.0-rc.2", args: []string{"--version", "v1.0.0-rc.2", "--allow-prerelease"}, wantOK: true, wantCalls: 4},
	} {
		t.Run(tc.name, func(t *testing.T) {
			root := privateReleaseRoot(t)
			if err := writeJSON(filepath.Join(root, "current.json"), Pointer{Version: tc.version}); err != nil {
				t.Fatal(err)
			}
			before, _ := os.ReadFile(filepath.Join(root, "current.json"))
			if tc.saved != "" {
				if err := os.WriteFile(filepath.Join(root, "channel.json"), []byte(tc.saved), 0600); err != nil {
					t.Fatal(err)
				}
			}
			payload := archiveFixture(t, releaseEntries(tc.version, runtime.GOARCH))
			sum := sha256.Sum256(payload)
			digest := hex.EncodeToString(sum[:])
			name := assetName(tc.version, runtime.GOARCH)
			metadata, _ := json.Marshal(releaseInfo{Tag: tc.version, TargetCommitish: fixtureSourceCommit, Prerelease: prereleaseVersion(tc.version), Assets: []releaseAsset{{name, officialAsset(tc.version, name)}, {"SHA256SUMS", officialAsset(tc.version, "SHA256SUMS")}}})
			calls := 0
			oldTransport := http.DefaultTransport
			http.DefaultTransport = fixtureTransport(func(req *http.Request) (*http.Response, error) {
				calls++
				var body []byte
				switch req.URL.String() {
				case channelManifestURL:
					body = fixtureChannelManifest(tc.version, digest)
				case releaseMetadataURL(tc.version):
					body = metadata
				case releaseRefURL(tc.version):
					body = fixtureReleaseRef(tc.version, fixtureSourceCommit)
				case officialAsset(tc.version, "SHA256SUMS"):
					body = []byte(digest + " " + name)
				case officialAsset(tc.version, name):
					body = payload
				default:
					t.Fatalf("unexpected update request %s", req.URL)
				}
				return &http.Response{StatusCode: 200, Body: io.NopCloser(bytes.NewReader(body)), Header: make(http.Header)}, nil
			})
			defer func() { http.DefaultTransport = oldTransport }()
			var out bytes.Buffer
			err := updateWithInput(root, tc.args, strings.NewReader("yes\n"), &out)
			if (err == nil) != tc.wantOK || calls != tc.wantCalls {
				t.Fatalf("update err=%v calls=%d wantOK=%v wantCalls=%d", err, calls, tc.wantOK, tc.wantCalls)
			}
			if tc.wantOK {
				selection, err := loadChannel(root)
				if err != nil || selection.PreviewApproved != tc.wantApproved {
					t.Fatalf("persisted consent=%+v %v", selection, err)
				}
			} else {
				data, e := os.ReadFile(filepath.Join(root, "channel.json"))
				if tc.saved == "" && !os.IsNotExist(e) || tc.saved != "" && (e != nil || string(data) != tc.saved) {
					t.Fatal("failed update changed consent")
				}
			}
			after, _ := os.ReadFile(filepath.Join(root, "current.json"))
			if !bytes.Equal(before, after) {
				t.Fatal("same-version or failed update changed legacy-compatible pointer")
			}
		})
	}
}

func TestUpdateUnknownStateAndBusyGuardsRunBeforeChannelNetwork(t *testing.T) {
	oldTransport := http.DefaultTransport
	defer func() { http.DefaultTransport = oldTransport }()
	http.DefaultTransport = fixtureTransport(func(req *http.Request) (*http.Response, error) {
		t.Fatalf("unsafe updater reached channel network: %s", req.URL)
		return nil, fmt.Errorf("unexpected network")
	})
	for _, scenario := range []string{"pending startup", "unknown runtime", "orphaned state", "missing jobs", "unknown job", "busy state owner"} {
		t.Run(scenario, func(t *testing.T) {
			root, c, _ := lifecycleConfigFixture(t)
			if err := privateRoot(root); err != nil {
				t.Fatal(err)
			}
			if err := writeJSON(filepath.Join(root, "current.json"), Pointer{Version: "v1.0.0-rc.2"}); err != nil {
				t.Fatal(err)
			}
			switch scenario {
			case "pending startup":
				if err := createStartup(root, Startup{Version: "v1.0.0-rc.2", LaunchID: strings.Repeat("a", 64)}); err != nil {
					t.Fatal(err)
				}
			case "unknown runtime":
				if err := os.WriteFile(filepath.Join(root, "runtime.json"), []byte("{}"), 0600); err != nil {
					t.Fatal(err)
				}
			case "orphaned state":
				if err := os.Mkdir(filepath.Join(root, "state"), 0700); err != nil {
					t.Fatal(err)
				}
			default:
				if err := writeJSON(filepath.Join(root, "config.json"), c); err != nil {
					t.Fatal(err)
				}
				if _, err := managedDirectory(root, "state", "jobs"); err != nil {
					t.Fatal(err)
				}
				switch scenario {
				case "missing jobs":
					if err := os.Remove(filepath.Join(root, "state", "jobs")); err != nil {
						t.Fatal(err)
					}
				case "unknown job":
					if err := os.WriteFile(filepath.Join(root, "state", "jobs", "unknown.json"), []byte(`{"status":"running"}`), 0600); err != nil {
						t.Fatal(err)
					}
				case "busy state owner":
					guard, err := lockFile(filepath.Join(root, "state", "node.lock"))
					if err != nil {
						t.Fatal(err)
					}
					defer guard.Close()
				}
			}
			if err := update(root, []string{"--allow-prerelease"}, io.Discard); err == nil {
				t.Fatal("unsafe state allowed update")
			}
			if _, err := os.Stat(filepath.Join(root, "channel.json")); !os.IsNotExist(err) {
				t.Fatal("busy/unknown state persisted new consent")
			}
		})
	}
}

func TestInstallChannelConsentRequiresExplicitChannelChoice(t *testing.T) {
	for _, tc := range []struct {
		channel                    string
		allow, approved, wantError bool
	}{
		{channel: "", allow: false}, {channel: "", allow: true},
		{channel: channelName, allow: false}, {channel: channelName, allow: true, approved: true},
		{channel: "stable", wantError: true}, {channel: "go-v2", wantError: true}, {channel: "GO-V1", wantError: true},
	} {
		selection, err := installChannelSelection(tc.channel, tc.allow)
		if (err != nil) != tc.wantError || selection.PreviewApproved != tc.approved || selection.Channel != channelName {
			t.Fatalf("channel=%q allow=%t selection=%+v err=%v", tc.channel, tc.allow, selection, err)
		}
	}
	root := filepath.Join(t.TempDir(), "uncreated")
	if err := install(root, []string{"--channel", "go-v2", "--version", "v1.0.0", "--allow-prerelease"}, io.Discard); err == nil {
		t.Fatal("unknown channel installed")
	}
	if _, err := os.Stat(root); !os.IsNotExist(err) {
		t.Fatal("unknown channel created root")
	}
}

func TestRollbackPreservesSavedChannelConsent(t *testing.T) {
	root := privateReleaseRoot(t)
	selection := ChannelSelection{Schema: "1", Channel: channelName, PreviewApproved: true}
	if err := writeJSON(filepath.Join(root, "channel.json"), selection); err != nil {
		t.Fatal(err)
	}
	before, _ := os.ReadFile(filepath.Join(root, "channel.json"))
	old := Pointer{Version: "v1.0.0-rc.2"}
	if err := writeJSON(filepath.Join(root, "current.json"), old); err != nil {
		t.Fatal(err)
	}
	if err := switchVersion(root, "v1.0.0-rc.3", old, func() error { return fmt.Errorf("fixture activation failure") }, func() error { return nil }); err == nil {
		t.Fatal("activation failure lost")
	}
	after, err := os.ReadFile(filepath.Join(root, "channel.json"))
	if err != nil || !bytes.Equal(before, after) {
		t.Fatal("rollback changed channel consent")
	}
	pointer, err := current(root)
	if err != nil || pointer != old {
		t.Fatal("rollback did not restore pointer")
	}
}

func TestChannelResolvesArchitectureSpecificDigest(t *testing.T) {
	manifest := fixtureChannelManifest("v1.0.0", strings.Repeat("a", 64))
	manifest = []byte(strings.Replace(string(manifest), `"windowsARM64SHA256":"`+strings.Repeat("a", 64)+`"`, `"windowsARM64SHA256":"`+strings.Repeat("b", 64)+`"`, 1))
	client := &http.Client{Transport: fixtureTransport(func(req *http.Request) (*http.Response, error) {
		if req.URL.String() != channelManifestURL {
			t.Fatalf("unexpected URL: %s", req.URL)
		}
		return &http.Response{StatusCode: 200, Body: io.NopCloser(bytes.NewReader(manifest)), Header: make(http.Header)}, nil
	})}
	for _, arch := range []string{"amd64", "arm64"} {
		target, err := resolveReleaseTarget(context.Background(), client, "", arch)
		want := strings.Repeat("a", 64)
		if arch == "arm64" {
			want = strings.Repeat("b", 64)
		}
		if err != nil || target.Version != "v1.0.0" || target.SourceCommit != fixtureSourceCommit || target.Digest != want {
			t.Fatalf("%s target=%+v err=%v", arch, target, err)
		}
	}
}

func TestUpdaterRejectsLegacyChannelProtocolBeforeReleaseDownloads(t *testing.T) {
	calls := 0
	data := bytes.Replace(fixtureChannelManifest("v1.9.0", strings.Repeat("a", 64)), []byte(`"cliProtocol":"2"`), []byte(`"cliProtocol":"1"`), 1)
	client := &http.Client{Transport: fixtureTransport(func(req *http.Request) (*http.Response, error) {
		calls++
		if req.URL.String() != channelManifestURL {
			t.Fatalf("legacy channel reached release download: %s", req.URL)
		}
		return &http.Response{StatusCode: 200, Body: io.NopCloser(bytes.NewReader(data)), Header: make(http.Header)}, nil
	})}
	if _, err := stageRelease(context.Background(), client, privateReleaseRoot(t), "", "amd64", "", true, "v1.0.0"); err == nil || !strings.Contains(err.Error(), "legacy CLI protocol 1") || calls != 1 {
		t.Fatalf("legacy channel protocol: calls=%d err=%v", calls, err)
	}
}
