package durablebridge

import (
	"context"
	"errors"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"sync"
	"sync/atomic"
	"time"
)

var ErrWorkerExited = errors.New("Durable worker exited; Host must stop")
var ErrForcedStop = errors.New("Durable worker needed forced termination; descendant cleanup requires service control-group verification")
var ErrStopUnknown = errors.New("Durable worker termination was not confirmed")

type Worker struct {
	cmd        *exec.Cmd
	lease      *StorageLease
	runtimeDir string
	client     *Client
	handler    http.Handler
	done       chan struct{}
	ready      atomic.Bool
	waitErr    error // written before done closes; only read after that close
	closeOnce  sync.Once
	closeErr   error
}

// Start opens no native database and implements no agent recovery. PRIVATE
// opens its Harness, resumes native work, and advertises readiness over UDS.
func Start(ctx context.Context, cfg Config, protectedTokens ...string) (*Worker, error) {
	cfg, err := cfg.normalized()
	if err != nil {
		return nil, err
	}
	if err := validateWorkerSecrets(cfg.Worker, cfg.Credentials, protectedTokens); err != nil {
		return nil, err
	}
	for _, dir := range []string{cfg.RuntimeDir, cfg.PiAgentDir} {
		if err := validateDirectory(dir); err != nil {
			return nil, err
		}
	}
	lease, err := AcquireStorageLease(cfg.StorageDir)
	if err != nil {
		return nil, err
	}
	runtimeDir, err := os.MkdirTemp(cfg.RuntimeDir, "worker-")
	if err != nil {
		lease.Close()
		return nil, err
	}
	w, err := startOwned(ctx, cfg, lease, runtimeDir, protectedTokens)
	if err != nil {
		return nil, err
	}
	return w, nil
}

// The lower-level entry is used by local subprocess fixtures, which deliberately
// do not bypass production directory checks through an exported configuration.
func startOwned(ctx context.Context, cfg Config, lease *StorageLease, runtimeDir string, protected []string) (*Worker, error) {
	client, err := NewUnixClient(filepath.Join(runtimeDir, "worker.sock"), cfg.RequestTimeout())
	if err != nil {
		lease.Close()
		os.RemoveAll(runtimeDir)
		return nil, err
	}
	handler, err := client.Handler(cfg.Credentials, protected...)
	if err != nil {
		client.Close()
		lease.Close()
		os.RemoveAll(runtimeDir)
		return nil, err
	}
	cmd := exec.Command(cfg.Worker.Executable, cfg.Worker.Args...)
	cmd.Env = []string{"PATH=/usr/local/bin:/usr/bin:/bin"}
	keys := make([]string, 0, len(cfg.Worker.Env))
	for key := range cfg.Worker.Env {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, key := range keys {
		if key == "PATH" {
			cmd.Env[0] = "PATH=" + cfg.Worker.Env[key]
		} else {
			cmd.Env = append(cmd.Env, key+"="+cfg.Worker.Env[key])
		}
	}
	cmd.Env = append(cmd.Env, "AWF_DURABLE_PROTOCOL=1", "AWF_DURABLE_OWNER_FD=3", "AWF_DURABLE_SOCKET="+filepath.Join(runtimeDir, "worker.sock"), "AWF_DURABLE_STORAGE_DIR="+cfg.StorageDir, "PI_CODING_AGENT_DIR="+cfg.PiAgentDir)
	cmd.ExtraFiles = []*os.File{lease.File()}
	cmd.Stdout = io.Discard
	cmd.Stderr = io.Discard
	if err := configureWorker(cmd); err != nil {
		client.Close()
		lease.Close()
		os.RemoveAll(runtimeDir)
		return nil, err
	}
	if ctx.Err() != nil {
		client.Close()
		lease.Close()
		os.RemoveAll(runtimeDir)
		return nil, ctx.Err()
	}
	if err := cmd.Start(); err != nil {
		client.Close()
		lease.Close()
		os.RemoveAll(runtimeDir)
		return nil, ErrUnavailable
	}
	w := &Worker{cmd: cmd, lease: lease, runtimeDir: runtimeDir, client: client, handler: handler, done: make(chan struct{})}
	client.available = func() bool {
		if !w.ready.Load() {
			return false
		}
		select {
		case <-w.done:
			return false
		default:
			return true
		}
	}
	go func() { w.waitErr = cmd.Wait(); w.ready.Store(false); close(w.done) }()
	startup, cancel := context.WithTimeout(ctx, time.Duration(cfg.StartupSeconds)*time.Second)
	defer cancel()
	for {
		b, status, err := client.exchange(startup, http.MethodGet, "/v1/health", "", nil)
		var health Health
		if err == nil && status == 200 && strictJSON(b, &health) == nil && health.Version == ProtocolVersion && health.DurableVersion == DurableVersion && health.Ready {
			select {
			case <-w.done:
				goto failed
			default:
				w.ready.Store(true)
				return w, nil
			}
		}
		select {
		case <-startup.Done():
			goto failed
		case <-w.done:
			goto failed
		case <-time.After(50 * time.Millisecond):
		}
	}
failed:
	shutdown, stop := context.WithTimeout(context.Background(), time.Duration(cfg.ShutdownSeconds)*time.Second)
	defer stop()
	if err := w.Close(shutdown); err != nil {
		return nil, errors.Join(ErrUnavailable, err)
	}
	return nil, ErrUnavailable
}

func (w *Worker) Handler() http.Handler { return w.handler }
func (w *Worker) Done() <-chan struct{} { return w.done }

// Close stops this one worker. It never restarts a process or resubmits input.
// Forced group termination is an explicit error, not a claim that native
// detached tools are quiescent. Production replacement requires systemd to
// finish control-group cleanup before the next Host opens storage.
func (w *Worker) Close(ctx context.Context) error {
	w.closeOnce.Do(func() {
		w.ready.Store(false)
		select {
		case <-w.done:
		default:
			_ = signalWorker(w.cmd, false)
			select {
			case <-w.done:
			case <-ctx.Done():
				w.closeErr = ErrForcedStop
				_ = signalWorker(w.cmd, true)
				select {
				case <-w.done:
				case <-time.After(2 * time.Second):
					w.closeErr = ErrStopUnknown
					return
				}
			}
		}
		w.client.Close()
		if w.closeErr == nil && w.waitErr != nil {
			w.closeErr = ErrWorkerExited
		}
		if err := os.RemoveAll(w.runtimeDir); w.closeErr == nil && err != nil {
			w.closeErr = err
		}
		if err := w.lease.Close(); w.closeErr == nil && err != nil {
			w.closeErr = err
		}
	})
	return w.closeErr
}
