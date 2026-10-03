package lifecycle

import (
	"bytes"
	"context"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// Exercise the public-install seam twice at the same disposable path so stdout
// must remain byte-identical with the progress observer enabled or absent.
func TestInstallProgressPreservesStdoutAndNoPath(t *testing.T) {
	for _, noPath := range []bool{false, true} {
		name := "with path"
		if noPath {
			name = "no path"
		}
		t.Run(name, func(t *testing.T) {
			local := t.TempDir()
			args := []string{"--yes", "--allow-prerelease"}
			if noPath {
				args = append(args, "--no-path")
			}
			var baseline string
			for _, display := range []bool{false, true} {
				ops := freshFixtureOps(local)
				var stdout, stderr bytes.Buffer
				if display {
					ops.progress = &installProgress{out: &stderr}
				}
				pathCalls := 0
				ops.registerPath = func(string) error { pathCalls++; return nil }
				requests := 0
				err := publicInstallWith(args, nil, &stdout, local, false,
					freshFixtureClient(t, "v1.0.0-rc.4", false, &requests), ops)
				if err != nil {
					t.Fatal(err)
				}
				wantPathCalls := 1
				if noPath {
					wantPathCalls = 0
				}
				if pathCalls != wantPathCalls {
					t.Fatalf("PATH calls: got %d, want %d", pathCalls, wantPathCalls)
				}
				if !display {
					baseline = stdout.String()
					if stderr.Len() != 0 {
						t.Fatal("quiet install emitted progress")
					}
				} else {
					if stdout.String() != baseline {
						t.Fatalf("progress changed stdout:\nquiet %q\nshown %q", baseline, stdout.String())
					}
					if strings.Contains(stderr.String(), "Register user PATH") == noPath {
						t.Fatalf("wrong PATH stage: %q", stderr.String())
					}
					if !strings.HasSuffix(stderr.String(), "AWF: Done\n") {
						t.Fatalf("successful install did not finish progress: %q", stderr.String())
					}
				}
				// Only the synthetic installation in this test's temp directory.
				if err := os.RemoveAll(filepath.Join(local, "AWF")); err != nil {
					t.Fatal(err)
				}
			}
		})
	}
}

type progressCancelledReader struct {
	ctx    context.Context
	cancel context.CancelFunc
}

func (r progressCancelledReader) Read(b []byte) (int, error) {
	// Even receiving all declared bytes cannot imply success when that same
	// read reports cancellation instead of a clean end of stream.
	n := copy(b, "partial")
	r.cancel()
	return n, r.ctx.Err()
}

func TestInstallProgressCancellationDoesNotComplete(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	var out bytes.Buffer
	now := time.Unix(0, 0)
	p := &installProgress{out: &out, now: func() time.Time {
		now = now.Add(time.Second)
		return now
	}}
	p.stage("Download release")
	client := &http.Client{Transport: fixtureTransport(func(*http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: 200, ContentLength: 7,
			Body: io.NopCloser(progressCancelledReader{ctx: ctx, cancel: cancel})}, nil
	})}
	_, err := fetchProgress(ctx, client, "https://github.com/archive?token=DO_NOT_LOG", 100, p)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("cancellation result changed: %v", err)
	}
	p.failed()
	text := out.String()
	if !strings.Contains(text, "99%") || strings.Contains(text, "100%") ||
		strings.Contains(text, "Done") || !strings.Contains(text, "stopped during Download release") {
		t.Fatalf("cancelled download misreported: %q", text)
	}
	if strings.Contains(text, "https://") || strings.Contains(text, "DO_NOT_LOG") {
		t.Fatal("progress exposed request details")
	}
}

func TestInstallProgressDirectoryFailureStage(t *testing.T) {
	local := t.TempDir()
	ops := freshFixtureOps(local)
	var stdout, stderr bytes.Buffer
	ops.progress = &installProgress{out: &stderr}
	ops.checkRoot = func(string) error { return errors.New("fixture directory failure") }
	requests := 0
	err := publicInstallWith([]string{"--yes", "--allow-prerelease"}, nil, &stdout, local, false,
		freshFixtureClient(t, "v1.0.0-rc.4", false, &requests), ops)
	if err == nil || !strings.Contains(err.Error(), "fixture directory failure") {
		t.Fatal(err)
	}
	if !strings.Contains(stderr.String(), "stopped during Prepare installation directory") ||
		strings.Contains(stderr.String(), "Done") || strings.Contains(stdout.String(), " installed.") {
		t.Fatalf("incorrect directory failure feedback: stdout=%q stderr=%q", stdout.String(), stderr.String())
	}
}
