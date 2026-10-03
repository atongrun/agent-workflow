package lifecycle

import (
	"context"
	"crypto/rand"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/netip"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/atongrun/agent-workflow/internal/node"
	"github.com/atongrun/agent-workflow/internal/opencode"
)

type Runtime struct {
	LaunchID string `json:"launchId"`
	URL      string `json:"url"`
	Token    string `json:"token"`
	Version  string `json:"version"`
}

var localHTTP = &http.Client{Timeout: 30 * time.Second, Transport: &http.Transport{Proxy: nil}, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}

func randomToken() (string, error) {
	b := make([]byte, 32)
	if _, e := rand.Read(b); e != nil {
		return "", e
	}
	return hex.EncodeToString(b), nil
}
func runtimePath(root string) string { return filepath.Join(root, "private", "runtime.json") }

// A missing identity means stopped only when no historical root-level token
// remains. Read-only callers never create the private runtime directory.
func checkRuntimeIdentity(root, path string) error {
	if e := rejectLegacyLayout(root); e != nil {
		return e
	}
	if e := checkPrivatePath(filepath.Dir(path)); e != nil {
		return e
	}
	return checkPrivatePath(path)
}
func readRuntime(root string) (Runtime, error) {
	var r Runtime
	if e := checkRuntimeIdentity(root, runtimePath(root)); e != nil {
		return r, e
	}
	e := readJSON(runtimePath(root), &r)
	if e != nil {
		return r, e
	}
	if !strings.HasPrefix(r.URL, "http://127.0.0.1:") || strings.ContainsAny(strings.TrimPrefix(r.URL, "http://127.0.0.1:"), "/?#@") || len(r.Token) != 64 {
		return r, errors.New("invalid managed runtime identity; refusing to target a process")
	}
	if _, e = netip.ParseAddrPort(strings.TrimPrefix(r.URL, "http://")); e != nil {
		return r, errors.New("invalid managed runtime address")
	}
	return r, nil
}
func control(r Runtime, method, path string) error {
	req, e := http.NewRequest(method, r.URL+path, nil)
	if e != nil {
		return e
	}
	req.Header.Set("Authorization", "Bearer "+r.Token)
	res, e := localHTTP.Do(req)
	if e != nil {
		return errors.New("managed runtime cannot be verified; refusing to kill a PID or assume it is stopped")
	}
	defer res.Body.Close()
	if res.StatusCode != 200 {
		b, _ := io.ReadAll(io.LimitReader(res.Body, 4096))
		return fmt.Errorf("managed runtime refused: %s", strings.TrimSpace(string(b)))
	}
	var got struct {
		Version string `json:"version"`
	}
	if path == "/health" {
		if e = json.NewDecoder(res.Body).Decode(&got); e != nil || got.Version != r.Version {
			return errors.New("managed runtime version identity mismatch")
		}
	}
	return nil
}

type Startup struct {
	LaunchID string `json:"launchId"`
	Version  string `json:"version"`
}

func startupPath(root string) string { return filepath.Join(root, "private", "starting.json") }
func readStartup(root string) (Startup, error) {
	var p Startup
	if e := checkRuntimeIdentity(root, startupPath(root)); e != nil {
		return p, e
	}
	e := readJSON(startupPath(root), &p)
	if e != nil {
		return p, e
	}
	b, e := hex.DecodeString(p.LaunchID)
	if e != nil || len(b) != 32 || validVersion(p.Version) != nil {
		return p, errors.New("startup intent has invalid identity")
	}
	return p, nil
}
func noPendingStartup(root string) error {
	_, e := readStartup(root)
	if os.IsNotExist(e) {
		return nil
	}
	if e != nil {
		return e
	}
	return errors.New("a requested startup is still pending or unknown; stop/update cannot assume the child is absent")
}
func createStartup(root string, p Startup) error {
	if _, e := managedDirectory(root, "private"); e != nil {
		return e
	}
	guard, e := lockFile(filepath.Join(root, "startup.lock"))
	if e != nil {
		return e
	}
	defer guard.Close()
	if e = noPendingStartup(root); e != nil {
		return e
	}
	return writeJSON(startupPath(root), p)
}
func clearStartup(root, id string) error {
	guard, e := lockFile(filepath.Join(root, "startup.lock"))
	if e != nil {
		return e
	}
	defer guard.Close()
	p, e := readStartup(root)
	if os.IsNotExist(e) {
		return nil
	}
	if e != nil {
		return e
	}
	if p.LaunchID != id {
		return errors.New("startup identity changed; refusing to clear it")
	}
	return os.Remove(startupPath(root))
}
func start(root string, out io.Writer) error {
	return startWith(root, out, func(path string) *exec.Cmd { return exec.Command(path, "_serve") }, 30*time.Second)
}
func startWith(root string, out io.Writer, command func(string) *exec.Cmd, wait time.Duration) error {
	if e := noPendingStartup(root); e != nil {
		return e
	}
	config, e := loadConfig(root)
	if e != nil {
		return e
	}
	p, e := current(root)
	if e != nil {
		return e
	}
	if r, e := readRuntime(root); e == nil {
		if r.Version != p.Version {
			return errors.New("running AWF version differs from the selected version; stop it safely before starting again")
		}
		if e = control(r, "GET", "/health"); e != nil {
			return e
		}
		fmt.Fprintf(out, "AWF %s is already running.\n", r.Version)
		return nil
	} else if !os.IsNotExist(e) {
		return e
	}
	// Metadata only: do not decrypt credentials in the parent or change ACLs.
	if st, err := os.Lstat(config.CredentialFile); os.IsNotExist(err) {
		return errors.New("paired node credential is missing; run awf pair before awf start")
	} else if err != nil || !st.Mode().IsRegular() {
		return errors.New("paired node credential cannot be inspected safely; check the configured credential path without replacing an existing identity")
	}
	guard, e := lockFile(filepath.Join(root, "runtime.lock"))
	if e != nil {
		return errors.New("managed runtime is starting or unverified; do not retry until its state is resolved")
	}
	guard.Close()
	id, e := randomToken()
	if e != nil {
		return e
	}
	if e = createStartup(root, Startup{LaunchID: id, Version: p.Version}); e != nil {
		return e
	}
	c := command(binary(root, p.Version))
	var diagnostic startupDiagnostic
	c.Stderr = &diagnostic
	detach(c)
	// No credentials or shell expressions appear in child arguments.
	c.Env = append(cleanEnvironment(os.Environ()), "AWF_LAUNCH_ID="+id)
	if e = c.Start(); e != nil {
		_ = clearStartup(root, id)
		return fmt.Errorf("cannot start AWF runtime: %w", e)
	}
	done := make(chan error, 1)
	go func() { err := c.Wait(); _ = clearStartup(root, id); done <- err }()
	deadline := time.Now().Add(wait)
	for time.Now().Before(deadline) {
		select {
		case <-done:
			return diagnostic.failure()
		default:
		}
		if r, e := readRuntime(root); e == nil && r.Version == p.Version && r.LaunchID == id && control(r, "GET", "/health") == nil && noPendingStartup(root) == nil {
			fmt.Fprintf(out, "AWF %s started.\n", p.Version)
			return nil
		}
		time.Sleep(100 * time.Millisecond)
	}
	return errors.New("startup outcome is unknown; inspect awf start before retrying or updating")
}

// Capture bounded child diagnostics, but never echo arbitrary stderr, paths,
// provider output, or credentials. Only exact known AWF errors are mapped.
type startupDiagnostic struct {
	text     string
	overflow bool
}

func (d *startupDiagnostic) Write(p []byte) (int, error) {
	n := len(p)
	left := 4096 - len(d.text)
	if len(p) > left {
		d.overflow = true
		p = p[:left]
	}
	d.text += string(p)
	return n, nil
}

func (d *startupDiagnostic) failure() error {
	if !d.overflow {
		switch strings.TrimSpace(d.text) {
		case "native OpenCode port is in use; refusing to adopt or stop another process":
			return errors.New("native OpenCode port 127.0.0.1:4096 is unavailable; resolve the conflicting listener before retrying awf start; no existing process was adopted or stopped")
		case "paired node credential is missing or unreadable; run awf pair first":
			return errors.New("paired node credential is missing or unreadable; check the configured path and run awf pair if no identity exists")
		case "paired credential directory must be private to the current user and SYSTEM, with no reparse point", "paired credential file must be private to the current user and SYSTEM, with no reparse point":
			return errors.New("paired credential privacy checks failed; inspect the configured credential path and permissions; existing credentials were not replaced")
		case "cannot decrypt paired node credential as this Windows user":
			return errors.New("cannot decrypt paired node credential as this Windows user; use the Windows account that paired this node; existing identity was preserved")
		case "invalid DPAPI credential size", "paired credential has invalid format":
			return errors.New("paired credential is invalid; preserve the existing identity and use explicit recovery rather than retrying pairing blindly")
		case "cannot start the configured native OpenCode executable", "native OpenCode exited during startup", "native OpenCode did not become healthy":
			return errors.New("native OpenCode failed to start or become healthy; verify the configured native .exe and its provider setup before retrying awf start")
		case "cannot bind configured node interface":
			return errors.New("cannot bind configured node interface; verify that the configured IP belongs to this Windows machine and its port is available")
		}
	}
	return errors.New("AWF runtime failed to start; verify native OpenCode, paired credential, configured interfaces, and exclusive state access")
}
func stop(root string, out io.Writer) error {
	if e := noPendingStartup(root); e != nil {
		return e
	}
	r, e := readRuntime(root)
	if os.IsNotExist(e) {
		guard, err := lockFile(filepath.Join(root, "runtime.lock"))
		if err != nil {
			return errors.New("managed runtime is starting or unverified; stop state is unknown")
		}
		defer guard.Close()
		c, ce := loadConfig(root)
		if ce != nil {
			return ce
		}
		lock, ce := node.OfflineIdle(c.Node)
		if ce != nil {
			return ce
		}
		lock.Close()
		fmt.Fprintln(out, "AWF is stopped; durable jobs are idle.")
		return nil
	}
	if e != nil {
		return e
	}
	if e = control(r, "POST", "/stop"); e != nil {
		return e
	}
	deadline := time.Now().Add(30 * time.Second)
	for time.Now().Before(deadline) {
		if _, e = os.Stat(runtimePath(root)); os.IsNotExist(e) {
			fmt.Fprintln(out, "AWF stopped. No native job was cancelled.")
			return nil
		}
		time.Sleep(100 * time.Millisecond)
	}
	return errors.New("stop outcome is unknown; update remains blocked")
}
func cleanEnvironment(env []string) []string {
	var out []string
	for _, v := range env {
		k := strings.ToUpper(strings.SplitN(v, "=", 2)[0])
		if strings.HasPrefix(k, "AWF_") || k == "OPENCODE_SERVER_PASSWORD" || k == "OPENCODE_SERVER_USERNAME" {
			continue
		}
		out = append(out, v)
	}
	return out
}

// nativeStateError deliberately projects only a fixed failure class. Native
// response bodies and transport/decode error text can contain credentials,
// workspace paths, or session content and must not reach the control response.
func nativeStateError(state string, err error) error {
	reason := "request failed"
	var status *opencode.HTTPError
	var syntax *json.SyntaxError
	var shape *json.UnmarshalTypeError
	var network net.Error
	switch {
	case errors.As(err, &status):
		reason = fmt.Sprintf("HTTP %d", status.StatusCode)
	case errors.Is(err, context.DeadlineExceeded):
		reason = "request timed out"
	case errors.Is(err, context.Canceled):
		reason = "request canceled"
	case errors.As(err, &network) && network.Timeout():
		reason = "request timed out"
	case errors.As(err, &syntax):
		reason = "malformed JSON response"
	case errors.As(err, &shape):
		reason = "unexpected JSON shape"
	}
	return fmt.Errorf("native %s is unknown (%s); stop/update is blocked", state, reason)
}

func nativeIdle(ctx context.Context, n *opencode.Client, c Config) error {
	h, e := n.Health(ctx)
	if e != nil {
		return nativeStateError("OpenCode health", e)
	}
	if !h.Healthy {
		return errors.New("native OpenCode health is unknown; stop/update is blocked")
	}
	for _, workspace := range c.Node.Projects {
		statuses, e := n.Statuses(ctx, workspace)
		if e != nil {
			return nativeStateError("session status", e)
		}
		if statuses == nil {
			return errors.New("native session status is unknown (null response); stop/update is blocked")
		}
		for _, s := range statuses {
			if s.Type != "idle" {
				return errors.New("a native OpenCode session is busy or unknown; stop/update is blocked")
			}
		}
		p, e := n.PendingPermissions(ctx, workspace)
		if e != nil {
			return nativeStateError("permission state", e)
		}
		if p == nil {
			return errors.New("native permission state is unknown (null response); stop/update is blocked")
		}
		if len(p) != 0 {
			return errors.New("native permission state is pending; stop/update is blocked")
		}
		q, e := n.PendingQuestions(ctx, workspace)
		if e != nil {
			return nativeStateError("question state", e)
		}
		if q == nil {
			return errors.New("native question state is unknown (null response); stop/update is blocked")
		}
		if len(q) != 0 {
			return errors.New("native question state is pending; stop/update is blocked")
		}
	}
	return nil
}
func serve(root string) error {
	pending, e := readStartup(root)
	if e != nil {
		return errors.New("managed runtime requires a verified startup intent")
	}
	if pending.LaunchID != os.Getenv("AWF_LAUNCH_ID") || pending.Version != Version {
		return errors.New("managed startup identity does not match this child")
	}
	selected, e := current(root)
	if e != nil || selected.Version != pending.Version {
		return errors.New("selected version changed before startup")
	}

	c, e := loadConfig(root)
	if e != nil {
		return e
	}
	processLock, e := lockFile(filepath.Join(root, "runtime.lock"))
	if e != nil {
		return errors.New("managed runtime already exists or cannot be locked")
	}
	defer processLock.Close()
	check, e := readStartup(root)
	if e != nil || check != pending {
		return errors.New("startup intent changed before runtime ownership was acquired")
	}
	if _, e = os.Stat(runtimePath(root)); e == nil {
		return errors.New("previous runtime identity remains; inspect it before recovery")
	} else if !os.IsNotExist(e) {
		return e
	}
	token, e := readNodeToken(c.CredentialFile)
	if e != nil {
		return e
	}
	// Reserve/check the native port before spawning. Health alone must never adopt
	// an unrelated already-running server, even if its password happens to match.
	probe, e := net.Listen("tcp", "127.0.0.1:4096")
	if e != nil {
		return errors.New("native OpenCode port is in use; refusing to adopt or stop another process")
	}
	probe.Close()
	pass, e := randomToken()
	if e != nil {
		return e
	}
	native := exec.Command(c.OpenCodeBinary, "serve", "--hostname", "127.0.0.1", "--port", "4096")
	native.Dir = root
	detach(native)
	native.Env = append(cleanEnvironment(os.Environ()), "OPENCODE_SERVER_USERNAME=opencode", "OPENCODE_SERVER_PASSWORD="+pass)
	if e = native.Start(); e != nil {
		return errors.New("cannot start the configured native OpenCode executable")
	}
	nativeDone := make(chan error, 1)
	go func() { nativeDone <- native.Wait() }()
	nativeExited := false
	preserveNative := false
	defer func() {
		if !nativeExited && !preserveNative {
			_ = native.Process.Kill()
			<-nativeDone
		}
	}()
	n, e := opencode.New(opencode.Config{URL: c.Node.OpenCodeURL, Username: "opencode", Password: pass})
	if e != nil {
		return e
	}
	ready := false
	for until := time.Now().Add(20 * time.Second); time.Now().Before(until); {
		select {
		case <-nativeDone:
			nativeExited = true
			return errors.New("native OpenCode exited during startup")
		default:
		}
		ctx, cancel := context.WithTimeout(context.Background(), time.Second)
		h, err := n.Health(ctx)
		cancel()
		if err == nil && h.Healthy {
			ready = true
			break
		}
		time.Sleep(100 * time.Millisecond)
	}
	if !ready {
		return errors.New("native OpenCode did not become healthy")
	}
	c.Node.Token = token
	c.Node.OpenCodeUsername = "opencode"
	c.Node.OpenCodePassword = pass
	listener, e := net.Listen("tcp", c.Node.ListenAddress)
	if e != nil {
		return errors.New("cannot bind configured node interface")
	}
	defer listener.Close()
	ctrl, e := net.Listen("tcp", "127.0.0.1:0")
	if e != nil {
		return e
	}
	defer ctrl.Close()
	controlToken, e := randomToken()
	if e != nil {
		return e
	}
	r := Runtime{LaunchID: pending.LaunchID, URL: "http://" + ctrl.Addr().String(), Token: controlToken, Version: Version}
	if e = writeJSON(runtimePath(root), r); e != nil {
		return e
	}
	defer func() {
		if !preserveNative {
			_ = os.Remove(runtimePath(root))
		}
	}()
	handler, e := node.New(c.Node)
	if e != nil {
		return e
	}
	s := handler.(*node.Server)
	defer s.Close()

	// node.New starts recovery workers. From this point an unexpected supervisor
	// failure must preserve native work, even before the CLI observes readiness.
	preserveNative = true

	var admission sync.RWMutex
	draining := false
	nodeHTTP := &http.Server{ReadHeaderTimeout: 10 * time.Second, ReadTimeout: 30 * time.Second, WriteTimeout: 60 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 16 << 10, Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "GET" {
			admission.RLock()
			defer admission.RUnlock()
			if draining {
				http.Error(w, "node is stopping", http.StatusServiceUnavailable)
				return
			}
		}
		s.ServeHTTP(w, r)
	})}
	stopping := make(chan struct{})
	var once sync.Once
	ctrlHTTP := &http.Server{ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 30 * time.Second, WriteTimeout: 30 * time.Second, Handler: http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		if subtle.ConstantTimeCompare([]byte(req.Header.Get("Authorization")), []byte("Bearer "+controlToken)) != 1 {
			http.Error(w, "unauthorized", 401)
			return
		}
		if req.Method == "GET" && req.URL.Path == "/health" {
			ctx, cancel := context.WithTimeout(req.Context(), 2*time.Second)
			defer cancel()
			h, err := n.Health(ctx)
			if err != nil || !h.Healthy {
				http.Error(w, "native runtime unhealthy", 503)
				return
			}
			_ = json.NewEncoder(w).Encode(map[string]string{"version": Version})
			return
		}
		if req.Method == "POST" && (req.URL.Path == "/stop" || req.URL.Path == "/idle") {
			admission.Lock()
			defer admission.Unlock()
			if draining {
				http.Error(w, "stop already in progress", 409)
				return
			}
			if err := s.Idle(); err != nil {
				http.Error(w, err.Error(), 409)
				return
			}
			ctx, cancel := context.WithTimeout(req.Context(), 20*time.Second)
			defer cancel()
			if err := nativeIdle(ctx, n, c); err != nil {
				http.Error(w, err.Error(), 409)
				return
			}
			if req.URL.Path == "/idle" {
				fmt.Fprintln(w, "idle")
				return
			}
			draining = true
			fmt.Fprintln(w, "stopping")
			once.Do(func() { close(stopping) })
			return
		}
		http.Error(w, "not found", 404)
	})}
	errorsCh := make(chan error, 2)
	go func() { errorsCh <- nodeHTTP.Serve(listener) }()
	go func() { errorsCh <- ctrlHTTP.Serve(ctrl) }()
	if e = clearStartup(root, pending.LaunchID); e != nil {
		return e
	}
	select {
	case <-stopping:
		preserveNative = false
	case <-nativeDone:
		preserveNative = false
		nativeExited = true
		e = errors.New("owned native OpenCode exited")
	case <-errorsCh:
		preserveNative = true
		e = errors.New("managed listener failed; native process preserved because job state may be active")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = nodeHTTP.Shutdown(ctx)
	_ = ctrlHTTP.Shutdown(ctx)
	_ = s.Close()
	if !nativeExited && !preserveNative {
		_ = native.Process.Kill()
		<-nativeDone
		nativeExited = true
	}
	return e
}
