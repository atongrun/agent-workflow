//go:build linux

package durablebridge

import (
	"context"
	"errors"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"
)

func workerFixtureConfig(t *testing.T, mode string) (Config, string, string) {
	t.Helper()
	root, err := os.MkdirTemp("/tmp", "awf-worker-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(root) })
	storage := filepath.Join(root, "native")
	runtime := filepath.Join(root, "runtime")
	agent := filepath.Join(root, "pi-agent")
	for _, dir := range []string{storage, runtime, agent} {
		if err := os.Mkdir(dir, 0700); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("AWF_FIXTURE_A", fixtureToken)
	t.Setenv("AWF_HOST_TOKEN", "fixture-host-credential-1234567890")
	exe, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	cfg := Config{StorageDir: storage, RuntimeDir: runtime, PiAgentDir: agent, Worker: Command{Executable: exe, Args: []string{"-test.run=^TestWorkerChildFixture$"}, Env: map[string]string{"AWF_WORKER_FIXTURE_MODE": mode}}, Credentials: []Credential{{Owner: "owner-a", TokenEnv: "AWF_FIXTURE_A"}}, StartupSeconds: 1, ShutdownSeconds: 1, RequestSeconds: 1}
	cfg, err = cfg.normalized()
	if err != nil {
		t.Fatal(err)
	}
	return cfg, storage, runtime
}

func startWorkerFixture(t *testing.T, cfg Config, storage, runtime string) (*Worker, error) {
	t.Helper()
	lease, err := acquireLeaseFile(filepath.Join(storage, ".awf-owner.lock"))
	if err != nil {
		t.Fatal(err)
	}
	run, err := os.MkdirTemp(runtime, "worker-")
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	return startOwned(ctx, cfg, lease, run, []string{os.Getenv("AWF_HOST_TOKEN")})
}

func TestManagedWorkerReadyGracefulStopAndEnvironmentFixture(t *testing.T) {
	cfg, storage, runtime := workerFixtureConfig(t, "ready")
	w, err := startWorkerFixture(t, cfg, storage, runtime)
	if err != nil {
		t.Fatal(err)
	}
	defer w.Close(context.Background())
	if second, err := acquireLeaseFile(filepath.Join(storage, ".awf-owner.lock")); !errors.Is(err, ErrStorageOwned) {
		if second != nil {
			second.Close()
		}
		t.Fatal("live worker allowed a second owner", err)
	}
	if response := publicCall(w.Handler(), "GET", "/requests/"+fixtureRequest, "", fixtureToken); response.Code != 200 {
		t.Fatal(response.Code, response.Body.String())
	}
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if err := w.Close(ctx); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(w.runtimeDir); !os.IsNotExist(err) {
		t.Fatal("own runtime directory retained", err)
	}
	lease, err := acquireLeaseFile(filepath.Join(storage, ".awf-owner.lock"))
	if err != nil {
		t.Fatal(err)
	}
	lease.Close()
	if response := publicCall(w.Handler(), "GET", "/requests/"+fixtureRequest, "", fixtureToken); response.Code != 503 {
		t.Fatal("stopped worker still accepted input", response.Code)
	}
}

func TestWorkerExitMakesUnavailableWithoutRestartFixture(t *testing.T) {
	cfg, storage, runtime := workerFixtureConfig(t, "exit-on-request")
	w, err := startWorkerFixture(t, cfg, storage, runtime)
	if err != nil {
		t.Fatal(err)
	}
	defer w.Close(context.Background())
	pid := w.cmd.Process.Pid
	if response := publicCall(w.Handler(), "GET", "/requests/"+fixtureRequest, "", fixtureToken); response.Code != 503 {
		t.Fatal(response.Code)
	}
	select {
	case <-w.Done():
	case <-time.After(3 * time.Second):
		t.Fatal("worker exit not observed")
	}
	if response := publicCall(w.Handler(), "POST", "/conversations/1/submissions/2/abort", "", fixtureToken); response.Code != 503 || w.cmd.Process.Pid != pid {
		t.Fatal("dead worker restarted or accepted mutation")
	}
	if err := w.Close(context.Background()); !errors.Is(err, ErrWorkerExited) {
		t.Fatal(err)
	}
}

func TestUnreadyWorkerStartupFailsAndCleansFixture(t *testing.T) {
	for _, mode := range []string{"wrong-version", "exit-before-ready"} {
		t.Run(mode, func(t *testing.T) {
			cfg, storage, runtime := workerFixtureConfig(t, mode)
			w, err := startWorkerFixture(t, cfg, storage, runtime)
			if w != nil || !errors.Is(err, ErrUnavailable) {
				t.Fatal("unready worker admitted", err)
			}
			entries, err := os.ReadDir(runtime)
			if err != nil || len(entries) != 0 {
				t.Fatal("failed startup retained own runtime", err)
			}
			lease, err := acquireLeaseFile(filepath.Join(storage, ".awf-owner.lock"))
			if err != nil {
				t.Fatal("failed startup retained lock", err)
			}
			lease.Close()
		})
	}
}

func TestForcedWorkerStopDoesNotClaimDescendantQuiescenceFixture(t *testing.T) {
	cfg, storage, runtime := workerFixtureConfig(t, "ignore-term")
	w, err := startWorkerFixture(t, cfg, storage, runtime)
	if err != nil {
		t.Fatal(err)
	}
	defer w.Close(context.Background())
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()
	if err := w.Close(ctx); !errors.Is(err, ErrForcedStop) {
		t.Fatal("forced termination was silently clean", err)
	}
	select {
	case <-w.Done():
	default:
		t.Fatal("owned worker termination not confirmed")
	}
}

func TestConfigAndCredentialIsolation(t *testing.T) {
	for _, path := range []string{"relative.json", "/", "/tmp/a/../config.json", "/tmp//config.json", "/tmp/config.json\x00"} {
		if _, err := LoadConfig(path); !errors.Is(err, ErrInvalid) {
			t.Fatalf("noncanonical config path accepted: %q %v", path, err)
		}
	}
	cfg, _, _ := workerFixtureConfig(t, "ready")
	if cfg.Worker.Env == nil {
		t.Fatal("bad fixture")
	}
	cfg.Worker.Env["AWF_DURABLE_SOCKET"] = "browser-controlled"
	if _, err := cfg.normalized(); !errors.Is(err, ErrInvalid) {
		t.Fatal("reserved startup field accepted")
	}
	delete(cfg.Worker.Env, "AWF_DURABLE_SOCKET")
	cfg.Worker.Env["OTHER"] = "Bearer " + os.Getenv("AWF_HOST_TOKEN")
	if _, err := Start(context.Background(), cfg, os.Getenv("AWF_HOST_TOKEN")); !errors.Is(err, ErrInvalid) {
		t.Fatal("Host credential copied to worker", err)
	}
	delete(cfg.Worker.Env, "OTHER")
	client, err := NewUnixClient("/tmp/awf-unused.sock", time.Second)
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	if _, err := client.Handler(cfg.Credentials, fixtureToken); !errors.Is(err, ErrInvalid) {
		t.Fatal("content token also granted Host authority")
	}
	if _, err := client.Handler(append(cfg.Credentials, cfg.Credentials[0])); !errors.Is(err, ErrInvalid) {
		t.Fatal("ambiguous token mapping accepted")
	}
	dir := t.TempDir()
	path := filepath.Join(dir, "config.json")
	b := []byte(`{"storageDir":"/tmp/native","runtimeDir":"/tmp/runtime","piAgentDir":"/tmp/pi-agent","worker":{"executable":"/usr/bin/node","args":[],"env":{}},"credentials":[{"owner":"owner-a","tokenEnv":"AWF_FIXTURE_A"}]}`)
	if err := os.WriteFile(path, b, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := readConfig(strings.NewReader(string(b))); err != nil {
		t.Fatal(err)
	}
	if f, err := openPrivateConfig(path); err != nil {
		t.Fatal(err)
	} else {
		f.Close()
	}
	if err := validateDirectoryAncestry(dir, false); err == nil {
		if _, err := LoadConfig(path); err != nil {
			t.Fatal(err)
		}
	} else {
		t.Logf("native config ancestry acceptance unavailable in this executor: %v", err)
	}
	if err := os.Chmod(path, 0644); err != nil {
		t.Fatal(err)
	}
	if f, err := openPrivateConfig(path); !errors.Is(err, ErrInvalid) {
		if f != nil {
			f.Close()
		}
		t.Fatal("public config accepted", err)
	}
	alias := filepath.Join(dir, "link")
	if err := os.Symlink(path, alias); err != nil {
		t.Fatal(err)
	}
	if f, err := openPrivateConfig(alias); err == nil {
		f.Close()
		t.Fatal("config symlink accepted")
	}
}

func TestWorkerChildFixture(t *testing.T) {
	mode := os.Getenv("AWF_WORKER_FIXTURE_MODE")
	if mode == "" {
		t.Skip("subprocess-only fake worker; no Durable SDK")
	}
	if os.Getenv("AWF_HOST_TOKEN") != "" || os.Getenv("AWF_FIXTURE_A") != "" || os.Getenv("AWF_DURABLE_PROTOCOL") != "1" || os.Getenv("PI_CODING_AGENT_DIR") == "" {
		os.Exit(2)
	}
	fd, err := strconv.Atoi(os.Getenv("AWF_DURABLE_OWNER_FD"))
	if err != nil || fd != 3 {
		os.Exit(3)
	}
	lease := os.NewFile(uintptr(fd), "owner")
	info, err := lease.Stat()
	if err != nil {
		os.Exit(4)
	}
	pathInfo, err := os.Stat(filepath.Join(os.Getenv("AWF_DURABLE_STORAGE_DIR"), ".awf-owner.lock"))
	if err != nil || !os.SameFile(info, pathInfo) {
		os.Exit(5)
	}
	syscall.CloseOnExec(fd)
	if mode == "exit-before-ready" {
		os.Exit(17)
	}
	listener, err := net.Listen("unix", os.Getenv("AWF_DURABLE_SOCKET"))
	if err != nil {
		os.Exit(6)
	}
	if err := os.Chmod(os.Getenv("AWF_DURABLE_SOCKET"), 0600); err != nil {
		os.Exit(7)
	}
	server := &http.Server{ReadHeaderTimeout: time.Second, Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/v1/health" {
			version := DurableVersion
			if mode == "wrong-version" {
				version = "not-pinned"
			}
			writeJSON(w, 200, Health{Version: 1, DurableVersion: version, Ready: true})
			return
		}
		if mode == "exit-on-request" {
			os.Exit(23)
		}
		writeJSON(w, 200, fixtureReceipt())
	})}
	if mode == "ignore-term" {
		signal.Ignore(syscall.SIGTERM)
	} else {
		stop := make(chan os.Signal, 1)
		signal.Notify(stop, syscall.SIGTERM)
		go func() {
			<-stop
			ctx, cancel := context.WithTimeout(context.Background(), time.Second)
			defer cancel()
			server.Shutdown(ctx)
			lease.Close()
		}()
	}
	server.Serve(listener)
	listener.Close()
	lease.Close()
	os.Exit(0)
}
