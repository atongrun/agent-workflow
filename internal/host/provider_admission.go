package host

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
	"github.com/atongrun/agent-workflow/internal/durablebridge"
	"github.com/atongrun/agent-workflow/internal/pi"
)

type providerFence struct {
	RequestID string `json:"requestId"`
}

func (s *Server) providerFencePath() string {
	return filepath.Join(s.cfg.DataDir, "provider-maintenance.json")
}
func providerBusy() error {
	return fail("provider_busy", "Active or unresolved work prevents provider changes. Wait for tasks to settle, then retry.", 409)
}
func (s *Server) providerAdmissionGuard(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "GET" || r.Method == "HEAD" || strings.HasPrefix(r.URL.Path, "/v1/provider-settings") {
			next.ServeHTTP(w, r)
			return
		}
		s.providerAdmission.RLock()
		defer s.providerAdmission.RUnlock()
		if _, err := os.Lstat(s.providerFencePath()); !os.IsNotExist(err) {
			writeError(w, providerBusy())
			return
		}
		next.ServeHTTP(w, r)
	})
}
func (s *Server) providerIdle() error {
	st := s.store.Snapshot()
	for _, t := range st.Tasks {
		if !taskPiIdle(t) || t.Budget.ActiveSince != nil || lifecycleRequestPending(&st, t.ID) || t.Status == "reporting" || t.Status == "review" || t.Execution != nil && !resultTerminal(t) {
			return providerBusy()
		}
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.closing || s.starting != 0 {
		return providerBusy()
	}
	for key, c := range s.clients {
		if !c.Alive() {
			continue
		}
		parts := strings.SplitN(key, ":", 2)
		if len(parts) != 2 || !piReclaimable(&st, parts[0], parts[1]) {
			return providerBusy()
		}
	}
	return nil
}
func (s *Server) maintenanceEndpoints(ctx context.Context, id string, release bool) error {
	if s.providerMaintenanceCall != nil {
		return s.providerMaintenanceCall(ctx, id, release)
	}
	cfg, err := durablebridge.LoadConfig(s.cfg.DurableConfig)
	if err != nil {
		return providerBusy()
	}
	client, err := durablebridge.NewUnixClient(filepath.Join(cfg.RuntimeDir, "worker.sock"), 10*time.Second)
	if err != nil {
		return providerBusy()
	}
	defer client.Close()
	// Release the legacy gate first. If either release is unconfirmed, the Host
	// fence remains and all new admissions stay closed until a confirmed retry.
	if !release {
		if client.CatalogMaintenance(ctx, id, false) != nil {
			return providerBusy()
		}
	}
	key, err := privateRegular(s.cfg.ContentServiceTokenFile, 4096)
	if err != nil {
		return providerBusy()
	}
	body, _ := json.Marshal(map[string]any{"requestId": id, "release": release})
	req, _ := http.NewRequestWithContext(ctx, "POST", "http://127.0.0.1:8811/content/catalog-maintenance", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+strings.TrimSpace(string(key)))
	req.Header.Set("Content-Type", "application/json")
	res, err := s.http.Do(req)
	if err != nil {
		return providerBusy()
	}
	defer res.Body.Close()
	var value struct {
		Held bool `json:"held"`
	}
	if res.StatusCode != 200 || json.NewDecoder(http.MaxBytesReader(nil, res.Body, 256)).Decode(&value) != nil || value.Held == release {
		return providerBusy()
	}
	if release && client.CatalogMaintenance(ctx, id, true) != nil {
		return providerBusy()
	}
	return nil
}

// Caller holds both the public admission and native Pi lifecycle locks.
func (s *Server) acquireProviderFence(ctx context.Context, id string) error {
	if err := s.providerIdle(); err != nil {
		return err
	}
	var existing providerFence
	if b, err := privateRegular(s.providerFencePath(), 256); err == nil {
		if json.Unmarshal(b, &existing) != nil || existing.RequestID != id {
			return providerBusy()
		}
	} else if !os.IsNotExist(err) {
		return providerBusy()
	}
	if atomicPrivateJSON(s.providerFencePath(), providerFence{id}) != nil {
		return providerFailure()
	}
	if err := s.maintenanceEndpoints(ctx, id, false); err != nil {
		// A lost acquisition response may have committed. Explicit matching release
		// is idempotent; an uncertain cleanup preserves the durable Host fence.
		cleanup, cancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cancel()
		if s.maintenanceEndpoints(cleanup, id, true) == nil && s.removeProviderFence() == nil {
			return err
		}
		return providerFailure()
	}
	// Reclaim only proved-idle native processes, retaining their native histories.
	// The next explicit prompt resumes through the existing model validation.
	s.mu.Lock()
	clients := make([]*pi.Client, 0, len(s.clients))
	for _, c := range s.clients {
		clients = append(clients, c)
	}
	s.mu.Unlock()
	for _, c := range clients {
		if c.Alive() && c.Close() != nil {
			return providerFailure()
		}
	}
	s.mu.Lock()
	s.clients = map[string]*pi.Client{}
	s.mu.Unlock()
	return s.store.Update(func(st *core.State) error {
		for _, t := range st.Tasks {
			for _, ref := range t.Sessions {
				ref.Available = false
			}
		}
		return nil
	})
}
func (s *Server) removeProviderFence() error {
	if err := os.Remove(s.providerFencePath()); err != nil && !os.IsNotExist(err) {
		return err
	}
	d, err := os.Open(s.cfg.DataDir)
	if err != nil {
		return err
	}
	defer d.Close()
	return d.Sync()
}
func (s *Server) releaseProviderFence(id string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	if s.maintenanceEndpoints(ctx, id, true) != nil {
		return providerFailure()
	}
	return s.removeProviderFence()
}
