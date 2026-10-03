package lifecycle

import (
	"bytes"
	"context"
	"errors"
	"io"
	"net/http"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestInstallProgressDownload(t *testing.T) {
	for _, total := range []int64{1024, -1, 0} {
		var out bytes.Buffer
		now := time.Unix(0, 0)
		p := &installProgress{out: &out, now: func() time.Time { return now }}
		p.stage("Download release")
		p.download(0, total, false)
		for i := 1; i <= 1024; i++ {
			p.download(int64(i), total, false)
		}
		if strings.Count(out.String(), "\r") != 1 {
			t.Fatalf("unbounded redraw: %q", out.String())
		}
		if strings.Contains(out.String(), "100%") {
			t.Fatal("premature completion")
		}
		now = now.Add(time.Second)
		p.download(1024, total, false)
		if total > 0 && !strings.Contains(out.String(), "99%") {
			t.Fatal(out.String())
		}
		p.download(1024, total, true)
		if total > 0 && !strings.Contains(out.String(), "100%  1024 / 1024 bytes") {
			t.Fatal(out.String())
		}
		if total <= 0 && (!strings.Contains(out.String(), "1024 bytes (total unknown)") || strings.Contains(out.String(), "%")) {
			t.Fatal(out.String())
		}
		if !strings.HasSuffix(out.String(), "\n") {
			t.Fatal("dangling redraw")
		}
	}
}

type progressFailWriter struct{ short bool }

func (w progressFailWriter) Write(b []byte) (int, error) {
	if w.short {
		return 0, nil
	}
	return 0, errors.New("closed output")
}
func TestInstallProgressOutputFailure(t *testing.T) {
	for _, short := range []bool{false, true} {
		p := &installProgress{out: progressFailWriter{short: short}}
		p.stage("Download release")
		p.download(0, 100, false)
		if p.out != nil {
			t.Fatal("broken renderer not disabled")
		}
	}
	var quiet *installProgress
	quiet.stage("Download release")
	quiet.download(1, 2, true)
	quiet.failed()
}

type progressPartialReader struct{ first bool }

func (r *progressPartialReader) Read(b []byte) (int, error) {
	if !r.first {
		r.first = true
		return copy(b, []byte("partial")), nil
	}
	return 0, io.ErrUnexpectedEOF
}
func TestInstallProgressNetworkFailureDoesNotComplete(t *testing.T) {
	var out bytes.Buffer
	p := &installProgress{out: &out}
	p.stage("Download release")
	client := &http.Client{Transport: fixtureTransport(func(*http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: 200, ContentLength: 20, Body: io.NopCloser(&progressPartialReader{})}, nil
	})}
	if _, err := fetchProgress(context.Background(), client, "https://github.com/archive", 100, p); err == nil {
		t.Fatal("partial response accepted")
	}
	p.failed()
	if strings.Contains(out.String(), "100%") || strings.Contains(out.String(), "Done") || !strings.Contains(out.String(), "stopped during Download release") {
		t.Fatal(out.String())
	}
}

func TestInstallProgressStageOrderingAndFailure(t *testing.T) {
	for _, failure := range []string{"", "verify", "install", "path"} {
		t.Run(failure, func(t *testing.T) {
			local := t.TempDir()
			ops := freshFixtureOps(local)
			var progress, stdout bytes.Buffer
			ops.progress = &installProgress{out: &progress}
			if failure == "install" {
				ops.finish = func(string, string, ChannelSelection, io.Writer) error { return errors.New("fixture failure") }
			}
			if failure == "path" {
				ops.registerPath = func(string) error { return errors.New("fixture failure") }
			}
			requests := 0
			err := publicInstallWith([]string{"--yes", "--allow-prerelease"}, nil, &stdout, local, false, freshFixtureClient(t, "v1.0.0-rc.4", failure == "verify", &requests), ops)
			if (err != nil) != (failure != "") {
				t.Fatal(err)
			}
			if strings.Contains(stdout.String(), "AWF: ") {
				t.Fatal("progress polluted stdout")
			}
			if failure == "" {
				last := -1
				for _, s := range []string{"Resolve release metadata", "Download release", "Verify release archive", "Prepare installation directory", "Extract verified release", "Install and verify launcher", "Register user PATH", "Check command lookup", "Done"} {
					at := strings.Index(progress.String(), s)
					if at <= last {
						t.Fatalf("bad stages: %q", progress.String())
					}
					last = at
				}
			} else if strings.Contains(progress.String(), "Done") {
				t.Fatal("false success")
			}
			if failure == "verify" && !strings.Contains(progress.String(), "stopped during Verify release archive") {
				t.Fatal(progress.String())
			}
		})
	}
}

func TestInstallProgressFetchFailureAndQuiet(t *testing.T) {
	for _, kind := range []string{"http", "size", "output", "quiet", "known", "unknown"} {
		t.Run(kind, func(t *testing.T) {
			var out bytes.Buffer
			p := &installProgress{out: &out}
			if kind == "quiet" {
				p = nil
			}
			if kind == "output" {
				p.out = progressFailWriter{}
			}
			status, total, limit := 200, int64(5), int64(100)
			if kind == "http" {
				status = 503
			}
			if kind == "size" {
				limit = 3
			}
			if kind == "unknown" {
				total = -1
			}
			client := &http.Client{Transport: fixtureTransport(func(*http.Request) (*http.Response, error) {
				return &http.Response{StatusCode: status, ContentLength: total, Body: io.NopCloser(strings.NewReader("hello"))}, nil
			})}
			data, err := fetchProgress(context.Background(), client, "https://github.com/archive", limit, p)
			success := kind == "quiet" || kind == "known" || kind == "unknown" || kind == "output"
			if (err == nil) != success {
				t.Fatal(err)
			}
			if success && string(data) != "hello" {
				t.Fatal(string(data))
			}
			if !success && strings.Contains(out.String(), "100%") {
				t.Fatal("false transfer success")
			}
			if kind == "quiet" && out.Len() != 0 {
				t.Fatal("noninteractive progress")
			}
			if kind == "known" && !strings.Contains(out.String(), "100%") {
				t.Fatal(out.String())
			}
			if kind == "unknown" && strings.Contains(out.String(), "%") {
				t.Fatal(out.String())
			}
		})
	}
}

func TestInstallProgressOutputFailureNeverInterruptsInstall(t *testing.T) {
	for _, stage := range []string{"before", "after root", "after PATH"} {
		t.Run(stage, func(t *testing.T) {
			local := t.TempDir()
			ops := freshFixtureOps(local)
			var display bytes.Buffer
			ops.progress = &installProgress{out: &display}
			if stage == "before" {
				ops.progress.out = progressFailWriter{}
			}
			finish := ops.finish
			ops.finish = func(root, v string, selection ChannelSelection, out io.Writer) error {
				if stage == "after root" {
					ops.progress.out = progressFailWriter{}
				}
				return finish(root, v, selection, out)
			}
			ops.registerPath = func(string) error {
				if stage == "after PATH" {
					ops.progress.out = progressFailWriter{}
				}
				return nil
			}
			requests := 0
			if err := publicInstallWith([]string{"--yes", "--allow-prerelease"}, nil, io.Discard, local, false, freshFixtureClient(t, "v1.0.0-rc.4", false, &requests), ops); err != nil {
				t.Fatal(err)
			}
			if _, err := current(filepath.Join(local, "AWF")); err != nil {
				t.Fatal(err)
			}
			if ops.progress.out != nil {
				t.Fatal("broken renderer not disabled")
			}
		})
	}
}
