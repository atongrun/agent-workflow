package host

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
	"github.com/atongrun/agent-workflow/internal/pi"
)

type NodeConfig struct {
	URL      string `json:"url"`
	TokenEnv string `json:"tokenEnv"`
}
type Config struct {
	EnableMaintenance bool                  `json:"enableMaintenance,omitempty"`
	PiAgentDir        string                `json:"piAgentDir,omitempty"`
	PiProvider        string                `json:"piProvider,omitempty"`
	EnableReviewer    bool                  `json:"enableReviewer,omitempty"`
	MaxPiProcesses    int                   `json:"maxPiProcesses,omitempty"`
	Listen            string                `json:"listen"`
	DataDir           string                `json:"dataDir"`
	TokenEnv          string                `json:"tokenEnv"`
	ExtensionTokenEnv string                `json:"extensionTokenEnv"`
	PiBinary          string                `json:"piBinary"`
	PiExtension       string                `json:"piExtension"`
	InternalURL       string                `json:"internalUrl"`
	Projects          map[string]string     `json:"projects"`
	Nodes             map[string]NodeConfig `json:"nodes"`
}
type Server struct {
	cfg                   Config
	store                 *core.Store
	token, extensionToken string
	// Serializes Pi startup, eviction, and task deletion without holding the store lock during process I/O.
	piLifecycle sync.Mutex
	// Lock order for maintenance: piLifecycle, then nativeEffects, then store.
	// Effect senders never acquire piLifecycle while holding nativeEffects.
	nativeEffects sync.RWMutex
	mu            sync.Mutex
	clients       map[string]*pi.Client
	dispatches    map[string]*sync.Mutex
	monitors      map[string]bool
	http          *http.Client
	stop          chan struct{}
	once          sync.Once
	wg            sync.WaitGroup
	closing       bool
	starting      int
}

func LoadConfig(path string) (Config, error) {
	var c Config
	b, err := os.ReadFile(path)
	if err == nil {
		err = json.Unmarshal(b, &c)
	}
	return c, err
}
func New(c Config) (*Server, error) {
	if c.MaxPiProcesses == 0 {
		c.MaxPiProcesses = 1
	}
	if c.MaxPiProcesses < 1 || c.MaxPiProcesses > 4 {
		return nil, errors.New("maxPiProcesses must be 1–4")
	}
	if c.TokenEnv == "" || c.ExtensionTokenEnv == "" {
		return nil, errors.New("tokenEnv and extensionTokenEnv are required")
	}
	token, extension := os.Getenv(c.TokenEnv), os.Getenv(c.ExtensionTokenEnv)
	if len(token) < 24 || len(extension) < 24 || token == extension {
		return nil, errors.New("distinct host and extension tokens of at least 24 characters required")
	}
	if c.DataDir == "" {
		return nil, errors.New("dataDir required")
	}
	absoluteDataDir, err := filepath.Abs(c.DataDir)
	if err != nil {
		return nil, err
	}
	c.DataDir = absoluteDataDir
	if c.PiAgentDir == "" {
		c.PiAgentDir = filepath.Join(c.DataDir, "pi-agent")
	}
	if !filepath.IsAbs(c.PiAgentDir) {
		return nil, errors.New("piAgentDir must be an explicit absolute directory")
	}
	if c.PiProvider == "" {
		c.PiProvider = "magpie"
	}
	if !modelRefValid(core.PiModel{Provider: c.PiProvider, ID: "configured"}) {
		return nil, errors.New("invalid piProvider")
	}
	for id, dir := range c.Projects {
		if id == "" || !filepath.IsAbs(dir) {
			return nil, errors.New("project directories must be explicit absolute paths")
		}
		info, err := os.Stat(dir)
		if err != nil || !info.IsDir() {
			return nil, errors.New("configured project directory unavailable")
		}
	}
	u, urlErr := url.Parse(c.InternalURL)
	if urlErr != nil || u.Scheme != "http" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || (u.Path != "" && u.Path != "/") || (u.Hostname() != "127.0.0.1" && u.Hostname() != "localhost" && u.Hostname() != "::1") {
		return nil, errors.New("internalUrl must use loopback")
	}
	for _, n := range c.Nodes {
		u, e := url.Parse(n.URL)
		if e != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || (u.Path != "" && u.Path != "/") {
			return nil, errors.New("node URL must be an explicit HTTP(S) origin")
		}
		if len(os.Getenv(n.TokenEnv)) < 24 {
			return nil, errors.New("node token environment must contain at least 24 characters")
		}
	}
	st, err := core.Open(c.DataDir)
	if err != nil {
		return nil, err
	}
	s := &Server{cfg: c, store: st, token: token, extensionToken: extension, clients: map[string]*pi.Client{}, monitors: map[string]bool{}, http: &http.Client{Timeout: 15 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}, stop: make(chan struct{})}
	if persisted := st.Snapshot().Maintenance; persisted != nil && persisted.Phase == "sealed" {
		// Preserve the sealed durable view on restart. Bound native reads still
		// require a live owned client; startup/dispatch are fenced until release.
		s.launch(s.watchExecutionResults)
		return s, nil
	}
	err = st.Update(func(state *core.State) error {
		if state.Settings.PiDefaultModel == (core.PiModel{}) {
			state.Settings.PiDefaultModel = core.Defaults().PiDefaultModel
		}
		state.Settings.Reviewer = "disabled"
		if c.EnableReviewer {
			state.Settings.Reviewer = "pi"
		}
		for _, t := range state.Tasks {
			for _, session := range t.Sessions {
				session.Available = false
				session.Busy = false
				session.Streaming = false
				session.Compacting = false
				session.Pending = false
				session.PendingCommands = nil
				session.NativeQueued = 0
				session.AwaitingStart = false
				session.PendingUI = nil
			}
			if t.Budget.ActiveSince != nil {
				if time.Since(*t.Budget.ActiveSince) >= time.Second {
					t.Budget.TaskSeconds++
					t.Budget.PlanSeconds++
				}
				t.Budget.ActiveSince = nil
				t.LastError = "Host restarted during activity; verify native sessions before continuing"
			}
			if t.Execution != nil && (t.Execution.Status == "running" || t.Execution.Status == "dispatching") {
				t.Status = "needs_verification"
				t.Execution.Status = "uncertain"
				core.Changed(state, t)
			}
		}
		for _, r := range state.Requests {
			if r.Operation == "execution_result" && r.Status == "accepted" && !r.Dispatched {
				r.Status = "queued"
				r.ProcessID = ""
			} else if r.Status == "accepted" {
				r.Status = "needs_verification"
			}
		}
		// Restart cannot establish the outcome of an earlier native control.
		for _, task := range state.Tasks {
			for role, session := range task.Sessions {
				rebuildPiControlFence(state, task.ID, role, session)
			}
		}
		return nil
	})
	if err != nil {
		_ = st.Close()
		return nil, err
	}
	s.recoverExecutions()
	s.launch(s.watchExecutionResults)
	return s, nil
}
func (s *Server) launch(fn func()) bool {
	s.mu.Lock()
	if s.closing {
		s.mu.Unlock()
		return false
	}
	s.wg.Add(1)
	s.mu.Unlock()
	go func() { defer s.wg.Done(); fn() }()
	return true
}
func (s *Server) Close() {
	s.once.Do(func() {
		s.mu.Lock()
		s.closing = true
		close(s.stop)
		clients := make([]*pi.Client, 0, len(s.clients))
		for _, c := range s.clients {
			clients = append(clients, c)
		}
		s.mu.Unlock()
		for _, c := range clients {
			_ = c.Close()
		}
		s.wg.Wait()
		_ = s.store.Close()
	})
}
