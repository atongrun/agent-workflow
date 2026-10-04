package hostinstall

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

func manifestFixture() (Manifest, map[string][]byte) {
	m := Manifest{Schema: 1, Channel: "linux-host-v1", Version: "v1.0.0-rc.10", SourceCommit: strings.Repeat("a", 40), InstallerProtocol: 1, HostProtocol: "v1", ExtensionProtocol: 1, PiRPCVersion: "1.0.2", OS: "linux", Arch: "amd64", LibC: "glibc"}
	elfBytes := make([]byte, 64)
	copy(elfBytes, []byte{0x7f, 'E', 'L', 'F', 2, 1, 1})
	binary.LittleEndian.PutUint16(elfBytes[16:], 2)
	binary.LittleEndian.PutUint16(elfBytes[18:], 62)
	binary.LittleEndian.PutUint32(elfBytes[20:], 1)
	binary.LittleEndian.PutUint16(elfBytes[52:], 64)
	payloads := map[string][]byte{}
	add := func(id, v, format, name, address string, payload []byte) {
		sum := sha256.Sum256(payload)
		payloads[address] = payload
		a := Artifact{name, address, hex.EncodeToString(sum[:]), int64(len(payload)), format}
		for i := range m.Components {
			if m.Components[i].ID == id {
				m.Components[i].Artifacts = append(m.Components[i].Artifacts, a)
				return
			}
		}
		m.Components = append(m.Components, Component{id, v, []Artifact{a}})
	}
	add("node", "v22.19.0", "tar.gz", "node-v22.19.0-linux-x64.tar.gz", "https://nodejs.org/dist/v22.19.0/node-v22.19.0-linux-x64.tar.gz", []byte("opaque-node-archive"))
	add("pi", "1.0.2", "json", "package.json", "https://pi.dev/api/installer/releases/1.0.2/package.json", []byte(`{"dependencies":{"pi":"1.0.2"}}`))
	add("pi", "1.0.2", "json", "package-lock.json", "https://pi.dev/api/installer/releases/1.0.2/package-lock.json", []byte(`{"lockfileVersion":3}`))
	add("awf-host", m.Version, "tar.gz", "awf_"+m.Version+"_linux_amd64.tar.gz", "https://github.com/atongrun/agent-workflow/releases/download/"+m.Version+"/awf_"+m.Version+"_linux_amd64.tar.gz", []byte("opaque-host-archive"))
	add("awf-extension", m.Version, "tar.gz", "awf-extension_"+m.Version+".tar.gz", "https://github.com/atongrun/agent-workflow/releases/download/"+m.Version+"/awf-extension_"+m.Version+".tar.gz", []byte("opaque-extension-archive"))
	add("magpie", "0.1.855", "elf", "magpie-cli-linux-amd64", "https://github.com/yetone/magpie-releases/releases/download/v0.1.855/magpie-cli-linux-amd64", elfBytes)
	return m, payloads
}
func cloneManifest(m Manifest) Manifest {
	b, _ := json.Marshal(m)
	var out Manifest
	_ = json.Unmarshal(b, &out)
	return out
}
func TestManifestValidation(t *testing.T) {
	m, _ := manifestFixture()
	data, _ := json.Marshal(m)
	if _, err := ParseManifest(data); err != nil {
		t.Fatal(err)
	}
	changes := map[string]func(*Manifest){
		"windows-channel": func(m *Manifest) { m.Channel = "go-v1" }, "unknown-protocol": func(m *Manifest) { m.InstallerProtocol = 2 }, "pi-compat": func(m *Manifest) { m.PiRPCVersion = "latest" },
		"source": func(m *Manifest) { m.SourceCommit = "main" }, "retired-runtime": func(m *Manifest) { m.Version = "v0.2.0" }, "platform": func(m *Manifest) { m.OS = "darwin" }, "musl": func(m *Manifest) { m.LibC = "musl" },
		"unknown-component": func(m *Manifest) { m.Components[0].ID = "plugin" }, "duplicate-component": func(m *Manifest) { m.Components[0] = m.Components[1] }, "missing-default": func(m *Manifest) { m.Components = m.Components[:4] },
		"unmatched-extension": func(m *Manifest) { m.Components[3].Version = "v1.0.0-rc.9" }, "node-too-old": func(m *Manifest) { m.Components[0].Version = "v22.18.0" },
		"no-digest": func(m *Manifest) { m.Components[0].Artifacts[0].SHA256 = "" }, "bad-digest": func(m *Manifest) { m.Components[0].Artifacts[0].SHA256 = strings.Repeat("A", 64) },
		"traversal": func(m *Manifest) { m.Components[0].Artifacts[0].Name = "../file" }, "credential-source": func(m *Manifest) { m.Components[0].Artifacts[0].URL += "?secret=hidden" },
		"mirror": func(m *Manifest) { m.Components[0].Artifacts[0].URL = "https://mirror.invalid/file" }, "wrong-format": func(m *Manifest) { m.Components[0].Artifacts[0].Format = "elf" },
		"oversize": func(m *Manifest) { m.Components[0].Artifacts[0].Bytes = MaxArtifactBytes + 1 }, "null-bytes": func(m *Manifest) { m.Components[0].Artifacts[0].Bytes = 0 },
	}
	for name, change := range changes {
		t.Run(name, func(t *testing.T) {
			x := cloneManifest(m)
			change(&x)
			b, _ := json.Marshal(x)
			if _, err := ParseManifest(b); err == nil {
				t.Fatal("invalid manifest accepted")
			}
		})
	}
	for _, data := range [][]byte{append(data, []byte(`{}`)...), bytes.Replace(data, []byte(`"schema":1`), []byte(`"schema":1,"schema":1`), 1), bytes.Replace(data, []byte(`"bytes":`), []byte(`"unknown":true,"bytes":`), 1), bytes.Repeat([]byte(" "), MaxManifestBytes+1)} {
		if _, err := ParseManifest(data); err == nil {
			t.Fatal("malformed/unknown manifest accepted")
		}
	}
}
func TestPlanUbuntuMatrixAndReservedArm64(t *testing.T) {
	m, _ := manifestFixture()
	good := Environment{"linux", "amd64", "ubuntu", "22.04", true, true}
	for _, release := range []string{"22.04", "24.04"} {
		e := good
		e.Release = release
		p, err := BuildPlan(m, e)
		if err != nil || !p.ReadyToStage || len(p.Components) != 5 || p.Paths["servicePiAgent"] != "/var/lib/awf/pi-agent" {
			t.Fatal(p, err)
		}
	}
	for _, e := range []Environment{{"linux", "arm64", "ubuntu", "24.04", true, true}, {"linux", "amd64", "debian", "12", true, true}, {"linux", "amd64", "ubuntu", "24.04", false, true}, {"linux", "amd64", "ubuntu", "24.04", true, false}} {
		p, err := BuildPlan(m, e)
		if err != nil || p.ReadyToStage {
			t.Fatal(p, err)
		}
	}
}

type fixtureTransport func(*http.Request) (*http.Response, error)

func (f fixtureTransport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

type recorder struct {
	events []ProgressEvent
	mu     sync.Mutex
}

func (r *recorder) Event(e ProgressEvent) { r.mu.Lock(); r.events = append(r.events, e); r.mu.Unlock() }
func fixtureClient(m Manifest, payloads map[string][]byte, count *int, unknown bool) *http.Client {
	return &http.Client{Transport: fixtureTransport(func(r *http.Request) (*http.Response, error) {
		if count != nil {
			*count++
		}
		var data []byte
		if strings.Contains(r.URL.Path, "/git/ref/") {
			data = []byte(`{"object":{"type":"commit","sha":"` + m.SourceCommit + `"}}`)
		} else {
			data = payloads[r.URL.String()]
		}
		if data == nil {
			return nil, errors.New("private-secret request failure")
		}
		total := int64(len(data))
		if unknown {
			total = -1
		}
		return &http.Response{StatusCode: 200, Body: io.NopCloser(bytes.NewReader(data)), ContentLength: total, Header: make(http.Header), Request: r}, nil
	})}
}
func privateParent(t *testing.T) string {
	t.Helper()
	p := t.TempDir()
	if err := os.Chmod(p, 0700); err != nil {
		t.Fatal(err)
	}
	return p
}
func TestStageVerifiedIdempotentAndProgress(t *testing.T) {
	m, payloads := manifestFixture()
	parent := privateParent(t)
	count := 0
	observer := &recorder{}
	path, err := Stage(context.Background(), m, parent, fixtureClient(m, payloads, &count, false), observer)
	if err != nil {
		t.Fatal(err)
	}
	if count != 7 {
		t.Fatal("expected source verification plus six artifacts", count)
	}
	data, _ := os.ReadFile(filepath.Join(path, "stage.json"))
	var receipt StageReceipt
	if json.Unmarshal(data, &receipt) != nil || !receipt.ArtifactsVerified || receipt.Installed {
		t.Fatal(string(data))
	}
	_, err = Stage(context.Background(), m, parent, fixtureClient(m, payloads, &count, false), observer)
	if err != nil || count != 7 {
		t.Fatal("verified exact staging retry downloaded again", count, err)
	}
	for _, event := range observer.events {
		if event.Stage == "install" || event.Stage == "extract" || event.Stage == "config" || event.Stage == "health" {
			t.Fatal("unperformed stage reported")
		}
	}
	if err = os.WriteFile(filepath.Join(path, "node", m.Components[0].Artifacts[0].Name), []byte("tampered"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err = Stage(context.Background(), m, parent, fixtureClient(m, payloads, &count, false), observer); err == nil {
		t.Fatal("tampered stage reused")
	}
}
func TestStageFailuresCleanUpAndDoNotLeak(t *testing.T) {
	for _, mode := range []string{"hash", "truncated", "oversize", "elf-arch", "request", "tag", "cancel"} {
		t.Run(mode, func(t *testing.T) {
			m, payloads := manifestFixture()
			parent := privateParent(t)
			observer := &recorder{}
			switch mode {
			case "hash":
				m.Components[0].Artifacts[0].SHA256 = strings.Repeat("b", 64)
			case "truncated":
				u := m.Components[0].Artifacts[0].URL
				payloads[u] = payloads[u][:3]
			case "oversize":
				u := m.Components[0].Artifacts[0].URL
				payloads[u] = append(payloads[u], 1)
			case "elf-arch":
				u := m.Components[4].Artifacts[0].URL
				binary.LittleEndian.PutUint16(payloads[u][18:], 183)
				sum := sha256.Sum256(payloads[u])
				m.Components[4].Artifacts[0].SHA256 = hex.EncodeToString(sum[:])
			case "request":
				delete(payloads, m.Components[0].Artifacts[0].URL)
			}
			client := fixtureClient(m, payloads, nil, true)
			if mode == "tag" {
				client = fixtureClient(Manifest{SourceCommit: strings.Repeat("b", 40)}, payloads, nil, false)
			}
			ctx := context.Background()
			if mode == "cancel" {
				var cancel context.CancelFunc
				ctx, cancel = context.WithCancel(ctx)
				cancel()
			}
			_, err := Stage(ctx, m, parent, client, observer)
			if err == nil {
				t.Fatal("failed stage accepted")
			}
			if strings.Contains(err.Error(), "private-secret") || strings.Contains(err.Error(), "https://") {
				t.Fatal("diagnostic leaked transport details", err)
			}
			entries, _ := os.ReadDir(parent)
			if len(entries) != 0 {
				t.Fatal("failed stage left install/staging files", entries)
			}
		})
	}
}
func TestStageRejectsSymlinkParentAndMissingObserver(t *testing.T) {
	m, payloads := manifestFixture()
	p := privateParent(t)
	if _, err := Stage(context.Background(), m, p, fixtureClient(m, payloads, nil, false), nil); err == nil {
		t.Fatal("missing progress observer accepted")
	}
	link := filepath.Join(t.TempDir(), "link")
	if err := os.Symlink(p, link); err != nil {
		t.Skip(err)
	}
	if _, err := Stage(context.Background(), m, link, fixtureClient(m, payloads, nil, false), &recorder{}); err == nil {
		t.Fatal("symlink stage parent accepted")
	}
}
func TestProgressKnownUnknownAndBrokenOutput(t *testing.T) {
	for _, tty := range []bool{false, true} {
		for _, total := range []int64{0, 200} {
			var output bytes.Buffer
			p := &Progress{Out: &output, TTY: tty}
			p.Event(ProgressEvent{Component: "node", Stage: "download", State: "progress", Bytes: 100, Total: total})
			p.Event(ProgressEvent{Component: "node", Stage: "verify", State: "failed"})
			text := output.String()
			if total == 0 && strings.Contains(text, "%") || total == 200 && !strings.Contains(text, "50.0%") {
				t.Fatal(text)
			}
			if !tty && (strings.Contains(text, "\r") || strings.Contains(text, "\x1b")) {
				t.Fatal("pipe output contains controls", text)
			}
		}
	}
	m, payloads := manifestFixture()
	if _, err := Stage(context.Background(), m, privateParent(t), fixtureClient(m, payloads, nil, false), &Progress{Out: brokenWriter{}}); err != nil {
		t.Fatal("display failure changed outcome", err)
	}
}

type brokenWriter struct{}

func (brokenWriter) Write([]byte) (int, error) { return 0, io.ErrClosedPipe }

func TestDoctorAndCLIReadOnly(t *testing.T) {
	m, _ := manifestFixture()
	e := Environment{"linux", "amd64", "ubuntu", "24.04", true, true}
	existing := privateParent(t)
	info, _ := os.Lstat(existing)
	paths := []string{}
	p, err := inspectDoctor(m, e, func(path string) (os.FileInfo, error) {
		paths = append(paths, path)
		if path == "/opt/pi-cli" {
			return info, nil
		}
		return nil, os.ErrNotExist
	}, func(name string) (string, error) {
		if name == "pi" {
			return "/existing/pi", nil
		}
		return "", os.ErrNotExist
	}, func(port int) string {
		if port == 3425 {
			return "occupied"
		}
		return "free_observed"
	})
	if err != nil || p.ReadyToStage || len(paths) != 6 {
		t.Fatal(p, err)
	}
	data, _ := json.Marshal(m)
	file := filepath.Join(privateParent(t), "manifest.json")
	if err = os.WriteFile(file, data, 0600); err != nil {
		t.Fatal(err)
	}
	var output bytes.Buffer
	if err = Run([]string{"plan", "--manifest", file, "--json"}, &output); err != nil {
		t.Fatal(err)
	}
	var report Plan
	if json.Unmarshal(output.Bytes(), &report) != nil || len(report.Pending) == 0 {
		t.Fatal(output.String())
	}
	after, _ := os.ReadFile(file)
	entries, _ := os.ReadDir(filepath.Dir(file))
	if !bytes.Equal(data, after) || len(entries) != 1 {
		t.Fatal("read-only planning wrote files")
	}
	for _, command := range []string{"install", "start", "update", "init", "stage"} {
		if err := Run([]string{command}, io.Discard); err == nil {
			t.Fatal("mutating CLI exposed", command)
		}
	}
}
func TestStageAnnotatedTagAndRedirectPolicy(t *testing.T) {
	m, payloads := manifestFixture()
	base := fixtureClient(m, payloads, nil, false)
	for _, mode := range []string{"annotated", "official-cdn", "foreign-cdn", "dependency-redirect", "metadata-redirect"} {
		t.Run(mode, func(t *testing.T) {
			client := *base
			client.Transport = fixtureTransport(func(r *http.Request) (*http.Response, error) {
				if mode == "annotated" && strings.Contains(r.URL.Path, "/git/ref/") {
					return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(`{"object":{"type":"tag","sha":"` + strings.Repeat("b", 40) + `"}}`)), Header: make(http.Header), Request: r}, nil
				}
				if mode == "annotated" && strings.Contains(r.URL.Path, "/git/tags/") {
					return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(`{"object":{"type":"commit","sha":"` + m.SourceCommit + `"}}`)), Header: make(http.Header), Request: r}, nil
				}
				original := m.Components[2].Artifacts[0]
				redirect := r.URL.String() == original.URL
				if mode == "dependency-redirect" {
					redirect = r.URL.String() == m.Components[0].Artifacts[0].URL
				}
				if mode == "metadata-redirect" {
					redirect = strings.Contains(r.URL.Path, "/git/ref/")
				}
				if mode != "annotated" && redirect {
					target := "https://release-assets.githubusercontent.com/fixture?signature=private-secret"
					if mode == "foreign-cdn" {
						target = "https://foreign.invalid/private-secret"
					}
					return &http.Response{StatusCode: 302, Body: io.NopCloser(strings.NewReader("")), Header: http.Header{"Location": []string{target}}, Request: r}, nil
				}
				if r.URL.Host == "release-assets.githubusercontent.com" {
					b := payloads[original.URL]
					return &http.Response{StatusCode: 200, Body: io.NopCloser(bytes.NewReader(b)), ContentLength: int64(len(b)), Header: make(http.Header), Request: r}, nil
				}
				return base.Transport.RoundTrip(r)
			})
			_, err := Stage(context.Background(), m, privateParent(t), &client, &recorder{})
			shouldPass := mode == "annotated" || mode == "official-cdn"
			if (err == nil) != shouldPass {
				t.Fatal(mode, err)
			}
			if err != nil && strings.Contains(err.Error(), "private-secret") {
				t.Fatal("redirect diagnostic leaked")
			}
		})
	}
}
func TestConcurrentStageCommitsOneVerifiedBundle(t *testing.T) {
	m, payloads := manifestFixture()
	parent := privateParent(t)
	client := fixtureClient(m, payloads, nil, false)
	var wg sync.WaitGroup
	results := make(chan string, 4)
	failures := make(chan error, 4)
	for i := 0; i < 4; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			observer := &recorder{}
			p, err := Stage(context.Background(), m, parent, client, observer)
			if err == nil {
				last := observer.events[len(observer.events)-1]
				if last.Component != "bundle" || last.State != "completed" {
					err = errors.New("concurrent caller lacked terminal completion")
				}
			}
			if err != nil {
				failures <- err
			} else {
				results <- p
			}
		}()
	}
	wg.Wait()
	close(results)
	close(failures)
	for err := range failures {
		t.Fatal(err)
	}
	expected := ""
	for p := range results {
		if expected != "" && p != expected {
			t.Fatal("concurrent stage selected different bundle")
		}
		expected = p
	}
	entries, _ := os.ReadDir(parent)
	if len(entries) != 1 {
		t.Fatal("temporary or duplicate stages survived", entries)
	}
}
func TestTypedNilProgressAndSecretReceiptLinkAreRejected(t *testing.T) {
	m, payloads := manifestFixture()
	parent := privateParent(t)
	client := fixtureClient(m, payloads, nil, false)
	var observer *Progress
	if _, err := Stage(context.Background(), m, parent, client, observer); err == nil {
		t.Fatal("typed nil progress accepted")
	}
	if _, err := Stage(context.Background(), m, parent, client, &Progress{}); err == nil {
		t.Fatal("missing progress output accepted")
	}
	path, err := Stage(context.Background(), m, parent, client, &recorder{})
	if err != nil {
		t.Fatal(err)
	}
	receipt := filepath.Join(path, "stage.json")
	if err = os.Remove(receipt); err != nil {
		t.Fatal(err)
	}
	secret := filepath.Join(t.TempDir(), "private-secret")
	if err = os.WriteFile(secret, []byte("secret"), 0600); err != nil {
		t.Fatal(err)
	}
	if err = os.Symlink(secret, receipt); err != nil {
		t.Skip(err)
	}
	if _, err = Stage(context.Background(), m, parent, client, &recorder{}); err == nil || strings.Contains(err.Error(), secret) {
		t.Fatal("linked receipt accepted or leaked", err)
	}
}

// Callback observers let cancellation target the last verification and commit
// boundary deterministically, without sleeps or external network calls.
type callbackObserver func(ProgressEvent)

func (f callbackObserver) Event(e ProgressEvent) { f(e) }
func TestCancellationAtFinalVerificationAndCommitBoundary(t *testing.T) {
	for _, boundary := range []string{"verify", "stage"} {
		t.Run(boundary, func(t *testing.T) {
			m, payloads := manifestFixture()
			parent := privateParent(t)
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			observer := callbackObserver(func(e ProgressEvent) {
				if boundary == "verify" && e.Component == "magpie" && e.Stage == "verify" && e.State == "completed" || boundary == "stage" && e.Component == "bundle" && e.Stage == "stage" && e.State == "started" {
					cancel()
				}
			})
			if _, err := Stage(ctx, m, parent, fixtureClient(m, payloads, nil, false), observer); err == nil {
				t.Fatal("cancelled stage committed")
			}
			entries, _ := os.ReadDir(parent)
			if len(entries) != 0 {
				t.Fatal("cancelled stage retained files", entries)
			}
			if _, err := Stage(context.Background(), m, parent, fixtureClient(m, payloads, nil, false), &recorder{}); err != nil {
				t.Fatal("fresh retry failed", err)
			}
		})
	}
	m, payloads := manifestFixture()
	var nilFunction callbackObserver
	if _, err := Stage(context.Background(), m, privateParent(t), fixtureClient(m, payloads, nil, false), nilFunction); err == nil {
		t.Fatal("nil callback accepted")
	}
}

func TestStageRejectsAmbiguousOrExtendedReceipt(t *testing.T) {
	for _, mode := range []string{"duplicate", "unknown"} {
		t.Run(mode, func(t *testing.T) {
			m, payloads := manifestFixture()
			parent := privateParent(t)
			client := fixtureClient(m, payloads, nil, false)
			path, err := Stage(context.Background(), m, parent, client, &recorder{})
			if err != nil {
				t.Fatal(err)
			}
			receiptPath := filepath.Join(path, "stage.json")
			data, err := os.ReadFile(receiptPath)
			if err != nil {
				t.Fatal(err)
			}
			extra := `"installed":true,`
			if mode == "unknown" {
				extra = `"unexpected":true,`
			}
			data = append([]byte("{"+extra), data[1:]...)
			if err := os.WriteFile(receiptPath, data, 0600); err != nil {
				t.Fatal(err)
			}
			if _, err := Stage(context.Background(), m, parent, client, &recorder{}); err == nil {
				t.Fatal("ambiguous receipt reused")
			}
		})
	}
}

func TestStageBoundsSuppliedClientTimeout(t *testing.T) {
	for _, timeout := range []time.Duration{0, 5 * time.Minute, 30 * time.Second} {
		t.Run(timeout.String(), func(t *testing.T) {
			m, payloads := manifestFixture()
			client := fixtureClient(m, payloads, nil, false)
			transport := client.Transport
			client.Timeout = timeout
			client.Transport = fixtureTransport(func(r *http.Request) (*http.Response, error) {
				deadline, ok := r.Context().Deadline()
				bound := 2 * time.Minute
				if timeout > 0 && timeout < bound {
					bound = timeout
				}
				if !ok || time.Until(deadline) > bound {
					t.Fatal("supplied client removed request deadline")
				}
				return transport.RoundTrip(r)
			})
			if _, err := Stage(context.Background(), m, privateParent(t), client, &recorder{}); err != nil {
				t.Fatal(err)
			}
		})
	}
}
