package lifecycle

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func freshFixtureOps(local string) freshInstallOps {
	return freshInstallOps{
		context: func() error { return nil }, knownFolder: func() (string, error) { return local, nil }, architecture: func() (string, error) { return "amd64", nil },
		path: func(string, bool) error { return nil }, reparse: func(string) error { return nil }, checkRoot: validateInstallRoot,
		finish: func(root, v string, s ChannelSelection, out io.Writer) error {
			return finishInstallChecked(root, v, s, out, func(string, string) error { return nil })
		},
		registerPath: func(string) error { return nil }, previewPath: func(string) (bool, error) { return true, nil },
	}
}
func freshFixtureClient(t *testing.T, v string, corrupt bool, requests *int) *http.Client {
	t.Helper()
	payload := archiveFixture(t, releaseEntries(v, "amd64"))
	sum := sha256.Sum256(payload)
	digest := hex.EncodeToString(sum[:])
	name := assetName(v, "amd64")
	meta, _ := json.Marshal(releaseInfo{Tag: v, TargetCommitish: fixtureSourceCommit, Prerelease: prereleaseVersion(v), Assets: []releaseAsset{{name, officialAsset(v, name)}, {"SHA256SUMS", officialAsset(v, "SHA256SUMS")}}})
	return &http.Client{Transport: fixtureTransport(func(req *http.Request) (*http.Response, error) {
		*requests++
		var body []byte
		switch req.URL.String() {
		case channelManifestURL:
			body = bytes.Replace(fixtureChannelManifest(v, digest), []byte(`"cliProtocol":"2"`), []byte(`"cliProtocol":"3"`), 1)
		case releaseMetadataURL(v):
			body = meta
		case releaseRefURL(v):
			body = fixtureReleaseRef(v, fixtureSourceCommit)
		case officialAsset(v, "SHA256SUMS"):
			body = []byte(digest + "  " + name + "\n")
		case officialAsset(v, name):
			body = payload
			if corrupt {
				body = append(append([]byte{}, payload...), 1)
			}
		default:
			t.Fatalf("unexpected installer URL: %s", req.URL)
		}
		return &http.Response{StatusCode: 200, Body: io.NopCloser(bytes.NewReader(body)), Header: make(http.Header)}, nil
	})}
}
func TestFreshInstallRefusesEveryExistingRootBeforeNetworkAndACL(t *testing.T) {
	for _, kind := range []string{"empty", "credentials", "current.json", "config.json", "runtime.json", "state", "file-root"} {
		t.Run(kind, func(t *testing.T) {
			local := t.TempDir()
			root := filepath.Join(local, "AWF")
			if kind == "file-root" {
				if err := os.WriteFile(root, []byte("keep"), 0600); err != nil {
					t.Fatal(err)
				}
			} else {
				if err := os.Mkdir(root, 0700); err != nil {
					t.Fatal(err)
				}
				if kind != "empty" {
					if err := os.WriteFile(filepath.Join(root, kind), []byte("SECRET keep"), 0600); err != nil {
						t.Fatal(err)
					}
				}
			}
			before := doctorSnapshot(t, local)
			ops := freshFixtureOps(local)
			ops.checkRoot = func(string) error { t.Fatal("existing root ACL changed"); return nil }
			requests := 0
			err := publicInstallWith([]string{"--yes", "--allow-prerelease"}, nil, io.Discard, local, false, freshFixtureClient(t, "v1.0.0-rc.3", false, &requests), ops)
			if err == nil || !strings.Contains(err.Error(), "already exists") {
				t.Fatal(err)
			}
			if requests != 0 || !reflect.DeepEqual(before, doctorSnapshot(t, local)) {
				t.Fatal("existing root operation had side effects")
			}
		})
	}
}
func TestFreshInstallConsentAndHashRefusalHaveNoWrites(t *testing.T) {
	cases := []struct {
		name, answer         string
		args                 []string
		interactive, corrupt bool
	}{
		{name: "EOF", interactive: true}, {name: "decline", answer: "n\n", interactive: true}, {name: "unterminated yes", answer: "yes", interactive: true},
		{name: "piped yes", answer: "yes\n"}, {name: "preview yes alone", args: []string{"--yes"}},
		{name: "hash mismatch", args: []string{"--yes", "--allow-prerelease"}, corrupt: true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			local := t.TempDir()
			before := doctorSnapshot(t, local)
			ops := freshFixtureOps(local)
			ops.checkRoot = func(string) error { t.Fatal("refusal reached ACL mutation"); return nil }
			ops.registerPath = func(string) error { t.Fatal("refusal changed PATH"); return nil }
			requests := 0
			err := publicInstallWith(tc.args, strings.NewReader(tc.answer), io.Discard, local, tc.interactive, freshFixtureClient(t, "v1.0.0-rc.3", tc.corrupt, &requests), ops)
			if err == nil {
				t.Fatal("unsafe consent/download accepted")
			}
			if !reflect.DeepEqual(before, doctorSnapshot(t, local)) {
				t.Fatal("refusal changed files")
			}
		})
	}
}
func TestFreshInstallContextProfileAndPathRefusal(t *testing.T) {
	for _, kind := range []string{"packaged", "unknown context", "profile mismatch", "unknown architecture", "redirected parent", "reparse parent"} {
		t.Run(kind, func(t *testing.T) {
			local := t.TempDir()
			ops := freshFixtureOps(local)
			switch kind {
			case "packaged", "unknown context":
				ops.context = func() error { return errors.New(kind) }
			case "profile mismatch":
				ops.knownFolder = func() (string, error) { return filepath.Join(local, "other"), nil }
			case "unknown architecture":
				ops.architecture = func() (string, error) { return "386", nil }
			case "redirected parent":
				ops.path = func(string, bool) error { return errors.New("redirected") }
			case "reparse parent":
				ops.reparse = func(string) error { return errors.New("reparse") }
			}
			before := doctorSnapshot(t, local)
			requests := 0
			err := publicInstallWith([]string{"--yes", "--allow-prerelease"}, nil, io.Discard, local, false, freshFixtureClient(t, "v1.0.0-rc.3", false, &requests), ops)
			if err == nil || requests != 0 || !reflect.DeepEqual(before, doctorSnapshot(t, local)) {
				t.Fatalf("unsafe preflight: %v requests=%d", err, requests)
			}
		})
	}
}
func TestFreshInstallSuccessAndPathOrdering(t *testing.T) {
	for _, noPath := range []bool{false, true} {
		t.Run(fmt.Sprint(noPath), func(t *testing.T) {
			local := t.TempDir()
			root := filepath.Join(local, "AWF")
			ops := freshFixtureOps(local)
			registered := 0
			launcherVerified := false
			ops.path = func(p string, _ bool) error {
				if p == filepath.Join(root, "bin", "awf.exe") {
					launcherVerified = true
				}
				return nil
			}
			ops.registerPath = func(bin string) error {
				if !launcherVerified || bin != filepath.Join(root, "bin") {
					t.Fatal("PATH before verified launcher")
				}
				if _, err := current(root); err != nil {
					t.Fatal(err)
				}
				registered++
				return nil
			}
			args := []string{"--yes", "--allow-prerelease"}
			if noPath {
				args = append(args, "--no-path")
			}
			requests := 0
			if err := publicInstallWith(args, nil, io.Discard, local, false, freshFixtureClient(t, "v1.0.0-rc.3", false, &requests), ops); err != nil {
				t.Fatal(err)
			}
			if (!noPath && registered != 1) || (noPath && registered != 0) {
				t.Fatal("PATH registration mismatch")
			}
			selection, err := loadChannel(root)
			if err != nil || !selection.PreviewApproved {
				t.Fatal(selection, err)
			}
			for _, name := range []string{"config.json", "credentials", "runtime.json", "starting.json", "state"} {
				if _, err := os.Lstat(filepath.Join(root, name)); !os.IsNotExist(err) {
					t.Fatalf("implicit setup: %s", name)
				}
			}
		})
	}
}
func TestFreshInstallChangedRootDuringDownloadIsPreserved(t *testing.T) {
	local := t.TempDir()
	root := filepath.Join(local, "AWF")
	ops := freshFixtureOps(local)
	calls := 0
	base := ops.path
	ops.path = func(p string, missing bool) error {
		if p == local {
			calls++
			if calls == 2 {
				if err := os.Mkdir(root, 0700); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(filepath.Join(root, "keep"), []byte("keep"), 0600); err != nil {
					t.Fatal(err)
				}
			}
		}
		return base(p, missing)
	}
	ops.checkRoot = func(string) error { t.Fatal("changed existing root ACL"); return nil }
	requests := 0
	err := publicInstallWith([]string{"--yes", "--allow-prerelease"}, nil, io.Discard, local, false, freshFixtureClient(t, "v1.0.0-rc.3", false, &requests), ops)
	if err == nil {
		t.Fatal("existing root accepted")
	}
	if b, err := os.ReadFile(filepath.Join(root, "keep")); err != nil || string(b) != "keep" {
		t.Fatal("lost raced data")
	}
}
func TestFreshInstallLatePathFailureDoesNotRegister(t *testing.T) {
	local := t.TempDir()
	root := filepath.Join(local, "AWF")
	ops := freshFixtureOps(local)
	ops.path = func(p string, _ bool) error {
		if p == filepath.Join(root, "bin", "awf.exe") {
			return errors.New("redirected launcher")
		}
		return nil
	}
	ops.registerPath = func(string) error { t.Fatal("PATH changed after launcher refusal"); return nil }
	requests := 0
	err := publicInstallWith([]string{"--yes", "--allow-prerelease"}, nil, io.Discard, local, false, freshFixtureClient(t, "v1.0.0-rc.3", false, &requests), ops)
	if err == nil {
		t.Fatal("redirected launcher accepted")
	}
}

func TestFreshInstallPathPreviewFailureHasNoSideEffects(t *testing.T) {
	local := t.TempDir()
	before := doctorSnapshot(t, local)
	ops := freshFixtureOps(local)
	ops.previewPath = func(string) (bool, error) { return false, errors.New("unsafe PATH value") }
	requests := 0
	err := publicInstallWith([]string{"--yes", "--allow-prerelease"}, nil, io.Discard, local, false, freshFixtureClient(t, "v1.0.0-rc.3", false, &requests), ops)
	if err == nil || requests != 0 || !reflect.DeepEqual(before, doctorSnapshot(t, local)) {
		t.Fatal("PATH preflight side effects", err)
	}
}

func TestFreshInstallDirectCommandQuoting(t *testing.T) {
	windows := `C:\Users\O'Brien $name\AppData\Local\AWF\bin\awf.exe`
	want := `& 'C:\Users\O''Brien $name\AppData\Local\AWF\bin\awf.exe' init`
	if got := installInitCommand(windows); got != want {
		t.Fatalf("got %q", got)
	}
	local := filepath.Join(t.TempDir(), "O'Brien with space")
	if err := os.Mkdir(local, 0700); err != nil {
		t.Fatal(err)
	}
	ops := freshFixtureOps(local)
	ops.previewPath = func(string) (bool, error) { t.Fatal("--no-path inspected registration"); return false, nil }
	var out bytes.Buffer
	requests := 0
	if err := publicInstallWith([]string{"--yes", "--no-path", "--allow-prerelease"}, nil, &out, local, false, freshFixtureClient(t, "v1.0.0-rc.3", false, &requests), ops); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), installInitCommand(filepath.Join(local, "AWF", "bin", "awf.exe"))) {
		t.Fatal("missing correctly quoted direct command", out.String())
	}
}

func TestFreshLocalArchiveNeedsExactHashBeforeRoot(t *testing.T) {
	for _, args := range [][]string{
		{"--yes", "--archive", "missing.zip"},
		{"--yes", "--version", "v1.0.0", "--archive", "missing.zip"},
		{"--yes", "--version", "v1.0.0", "--archive", "missing.zip", "--sha256", strings.Repeat("0", 64)},
	} {
		local := t.TempDir()
		ops := freshFixtureOps(local)
		client := &http.Client{Transport: fixtureTransport(func(*http.Request) (*http.Response, error) {
			t.Fatal("local archive accessed network")
			return nil, nil
		})}
		if err := publicInstallWith(args, nil, io.Discard, local, false, client, ops); err == nil {
			t.Fatal("invalid local archive accepted")
		}
		if _, err := os.Lstat(filepath.Join(local, "AWF")); !os.IsNotExist(err) {
			t.Fatal("invalid local archive created root")
		}
	}
}
func TestFreshInstallRefusesPublishedLegacyChannel(t *testing.T) {
	local := t.TempDir()
	ops := freshFixtureOps(local)
	client := &http.Client{Transport: fixtureTransport(func(req *http.Request) (*http.Response, error) {
		if req.URL.String() != channelManifestURL {
			t.Fatal("legacy channel downloaded payload")
		}
		return &http.Response{StatusCode: 200, Body: io.NopCloser(bytes.NewReader(bytes.Replace(fixtureChannelManifest("v1.0.0", strings.Repeat("a", 64)), []byte(`"cliProtocol":"3"`), []byte(`"cliProtocol":"2"`), 1))), Header: make(http.Header)}, nil
	})}
	err := publicInstallWith([]string{"--yes"}, nil, io.Discard, local, false, client, ops)
	if err == nil || !strings.Contains(err.Error(), "protocol 3") {
		t.Fatal(err)
	}
	if _, err := os.Lstat(filepath.Join(local, "AWF")); !os.IsNotExist(err) {
		t.Fatal("legacy channel created root")
	}
}

func TestFreshLayoutMarkerRefusesHistoryWithoutWrites(t *testing.T) {
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "current.json"), []byte(`{"version":"v1.0.0"}`), 0600); err != nil {
		t.Fatal(err)
	}
	before := doctorSnapshot(t, root)
	if err := requireFreshLayout(root); err == nil {
		t.Fatal("historical root accepted")
	}
	if !reflect.DeepEqual(before, doctorSnapshot(t, root)) {
		t.Fatal("historical files changed")
	}
	if err := writeJSON(filepath.Join(root, "installation.json"), freshLayout{1, "fresh-v1"}); err != nil {
		t.Fatal(err)
	}
	if err := requireFreshLayout(root); err != nil {
		t.Fatal(err)
	}
}
