package lifecycle

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

type activationProgressWriter struct {
	bytes.Buffer
	t    *testing.T
	root string
}

func (w *activationProgressWriter) WriteString(s string) (int, error) {
	return w.Write([]byte(s))
}

func (w *activationProgressWriter) Write(b []byte) (int, error) {
	if strings.Contains(string(b), "AWF: Done") {
		if p, err := current(w.root); err != nil || p.Version != "v1.2.3" {
			w.t.Fatal("Done appeared before new version activation")
		}
		if _, err := os.Stat(filepath.Join(w.root, "channel.json")); err != nil {
			w.t.Fatal("Done appeared before update channel was saved")
		}
	}
	return w.Buffer.Write(b)
}

func TestUpdateProgressSuccessfulVersionActivation(t *testing.T) {
	if runtime.GOOS != "windows" {
		t.Skip("native Windows update executable fixture")
	}
	// Compile a real native executable that supports only the two self-check
	// commands. It cannot install, pair, start a node or open a listener.
	build := t.TempDir()
	source := filepath.Join(build, "main.go")
	program := `package main
import ("fmt"; "os")
func main() {
 if len(os.Args) != 2 { os.Exit(2) }
 switch os.Args[1] {
 case "version": fmt.Println("v1.2.3")
 case "install-protocol": fmt.Println("3")
 default: os.Exit(2)
 }
}`
	if err := os.WriteFile(source, []byte(program), 0600); err != nil {
		t.Fatal(err)
	}
	executable := filepath.Join(build, "fixture.exe")
	command := exec.Command(filepath.Join(runtime.GOROOT(), "bin", "go.exe"), "build", "-trimpath", "-buildvcs=false", "-o", executable, source)
	command.Env = append(os.Environ(), "GOTOOLCHAIN=local", "CGO_ENABLED=0", "GOFLAGS=")
	if output, err := command.CombinedOutput(); err != nil {
		t.Fatalf("compile native self-check fixture: %v\n%s", err, output)
	}
	native, err := os.ReadFile(executable)
	if err != nil {
		t.Fatal(err)
	}
	entries := releaseEntries("v1.2.3", runtime.GOARCH)
	entries[0].data, entries[1].data = native, native
	payload := archiveFixture(t, entries)
	sum := sha256.Sum256(payload)
	digest := hex.EncodeToString(sum[:])
	asset := assetName("v1.2.3", runtime.GOARCH)
	var baseline string
	for _, shown := range []bool{false, true} {
		root := privateReleaseRoot(t)
		if err := writeJSON(filepath.Join(root, "current.json"), Pointer{Version: "v1.2.2"}); err != nil {
			t.Fatal(err)
		}
		oldDirectory, err := managedDirectory(root, "versions", "v1.2.2")
		if err != nil {
			t.Fatal(err)
		}
		oldPath := filepath.Join(oldDirectory, "awf.exe")
		mustWriteFixture(t, oldPath, []byte("unchanged prior fixture executable"))
		requests := 0
		client := freshFixtureClient(t, "v1.2.3", false, &requests)
		original := client.Transport
		client.Transport = fixtureTransport(func(req *http.Request) (*http.Response, error) {
			var body []byte
			switch req.URL.String() {
			case releaseMetadataURL("v1.2.3"):
				body, _ = json.Marshal(releaseInfo{Tag: "v1.2.3", TargetCommitish: fixtureSourceCommit, Assets: []releaseAsset{{asset, officialAsset("v1.2.3", asset)}, {"SHA256SUMS", officialAsset("v1.2.3", "SHA256SUMS")}}})
			case channelManifestURL:
				body = bytes.Replace(fixtureChannelManifest("v1.2.3", digest), []byte(`"cliProtocol":"2"`), []byte(`"cliProtocol":"3"`), 1)
			case officialAsset("v1.2.3", "SHA256SUMS"):
				body = []byte(fmt.Sprintf("%s  %s\n", digest, asset))
			case officialAsset("v1.2.3", asset):
				body = payload
			default:
				return original.RoundTrip(req)
			}
			requests++
			return &http.Response{StatusCode: 200, ContentLength: int64(len(body)), Body: io.NopCloser(bytes.NewReader(body)), Header: make(http.Header)}, nil
		})
		var stdout bytes.Buffer
		stderr := &activationProgressWriter{t: t, root: root}
		var progress *installProgress
		if shown {
			progress = &installProgress{out: stderr}
		}
		if err := updateWithProgress(root, nil, strings.NewReader(""), &stdout, client, progress); err != nil {
			t.Fatal(err)
		}
		if requests < 5 {
			t.Fatal("update skipped the HTTP download chain")
		}
		if p, err := current(root); err != nil || p.Version != "v1.2.3" {
			t.Fatal("updater did not activate the new version")
		}
		if old, err := os.ReadFile(oldPath); err != nil || string(old) != "unchanged prior fixture executable" {
			t.Fatal("update modified old version")
		}
		if _, err := os.Stat(filepath.Join(root, "state")); !os.IsNotExist(err) {
			t.Fatal("update created node state")
		}
		want := "AWF updated to v1.2.3. Configuration, credentials, native authentication, and job state were preserved.\n"
		if stdout.String() != want {
			t.Fatalf("stdout contract changed: %q", stdout.String())
		}
		if !shown {
			baseline = stdout.String()
			if stderr.Len() != 0 {
				t.Fatal("quiet update emitted progress")
			}
		} else {
			if stdout.String() != baseline {
				t.Fatal("progress changed stdout")
			}
			last := -1
			for _, stage := range []string{"Resolve update release", "Download release", "100%", "Verify release archive", "Extract verified release", "Check downloaded executable", "Activate update", "AWF: Done"} {
				next := strings.Index(stderr.String(), stage)
				if next <= last {
					t.Fatalf("missing or out-of-order %q: %s", stage, stderr.String())
				}
				last = next
			}
		}
	}
}
