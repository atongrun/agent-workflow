package lifecycle

import (
	"bytes"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// Exercise the updater's HTTP selection/download/staging path, not only the
// renderer. Fast transfers must still emit start, completion and stage text.
func TestUpdateProgressWiringAndStdout(t *testing.T) {
	for _, tc := range []struct {
		name                    string
		unknown, corrupt, newer bool
	}{
		{name: "fast known length"},
		{name: "fast unknown length", unknown: true},
		{name: "hash failure", corrupt: true},
		{name: "executable check failure", newer: true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var baseline string
			for _, shown := range []bool{false, true} {
				root := privateReleaseRoot(t)
				old := "v1.2.3"
				if tc.newer {
					old = "v1.2.2"
				}
				if err := writeJSON(filepath.Join(root, "current.json"), Pointer{Version: old}); err != nil {
					t.Fatal(err)
				}
				requests := 0
				client := freshFixtureClient(t, "v1.2.3", tc.corrupt, &requests)
				transport := client.Transport
				client.Transport = fixtureTransport(func(req *http.Request) (*http.Response, error) {
					res, err := transport.RoundTrip(req)
					if err == nil && req.URL.String() == officialAsset("v1.2.3", assetName("v1.2.3", "amd64")) {
						data, readErr := io.ReadAll(res.Body)
						res.Body.Close()
						if readErr != nil {
							return nil, readErr
						}
						res.Body = io.NopCloser(bytes.NewReader(data))
						res.ContentLength = int64(len(data))
						if tc.unknown {
							res.ContentLength = -1
						}
					}
					return res, err
				})
				var stdout, stderr bytes.Buffer
				var progress *installProgress
				if shown {
					progress = &installProgress{out: &stderr}
				}
				err := updateWithProgress(root, nil, strings.NewReader(""), &stdout, client, progress)
				if (err != nil) != (tc.corrupt || tc.newer) {
					t.Fatalf("update result: %v", err)
				}
				if requests < 5 {
					t.Fatal("updater did not reach actual HTTP download path")
				}
				if strings.Contains(stdout.String(), "AWF:") {
					t.Fatal("progress changed stdout contract")
				}
				if !shown {
					baseline = stdout.String()
					if stderr.Len() != 0 {
						t.Fatal("quiet updater emitted progress")
					}
				} else {
					if stdout.String() != baseline {
						t.Fatal("progress changed updater stdout")
					}
					text := stderr.String()
					for _, want := range []string{"Resolve update release", "Download release", "AWF: Download ", "Verify release archive"} {
						if !strings.Contains(text, want) {
							t.Fatalf("missing %q: %s", want, text)
						}
					}
					if tc.unknown {
						if !strings.Contains(text, "bytes (total unknown)") || strings.Contains(text, "%") {
							t.Fatal("unknown total invented a percentage")
						}
					} else if !strings.Contains(text, "100%") {
						t.Fatal("fast transfer hid completion")
					}
					if strings.Count(text, "\r") > 3 {
						t.Fatal("fast download redraws were not throttled")
					}
					if tc.corrupt || tc.newer {
						if strings.Contains(text, "AWF: Done") || !strings.Contains(text, "stopped during") {
							t.Fatal("failed update falsely displayed success")
						}
					} else if !strings.Contains(text, "Extract verified release") || !strings.HasSuffix(text, "AWF: Done\n") {
						t.Fatal("successful update hid completion")
					}
				}
				if p, err := current(root); err != nil || p.Version != old {
					t.Fatal("fixture update changed selected pointer")
				}
				if _, err := os.Stat(filepath.Join(root, "state")); !os.IsNotExist(err) {
					t.Fatal("fixture update created node state")
				}
			}
		})
	}
}

func TestProgressConsoleDetectionRejectsRedirectedOutput(t *testing.T) {
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	defer r.Close()
	defer w.Close()
	if interactiveUpdateInput(w) || interactiveUpdateInput(bytes.NewBuffer(nil)) {
		t.Fatal("redirected output was treated as a console")
	}
	_, _ = io.WriteString(w, "fixture")
}

func TestProgressNativeWindowsConsole(t *testing.T) {
	if runtime.GOOS != "windows" {
		t.Skip("native Windows console probe")
	}
	console, err := os.OpenFile("CONOUT$", os.O_RDWR, 0)
	if err != nil {
		t.Skip("executor has no attached native console; redirected pipes are covered separately")
	}
	defer console.Close()
	if !interactiveUpdateInput(console) {
		t.Fatal("native console was not detected")
	}
	// A fixture-only display: no network, files, install, or node operations.
	p := &installProgress{out: console}
	p.stage("Update progress console fixture")
	p.download(0, -1, false)
	p.download(1, -1, true)
	p.stage("Done")
	if p.out == nil {
		t.Fatal("native console rejected fixture progress output")
	}
	t.Logf("native console detected; process stderr console=%t", interactiveUpdateInput(os.Stderr))
}
