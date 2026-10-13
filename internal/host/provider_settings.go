package host

// A narrow adapter to Magpie's native provider persistence. No provider keys,
// transport settings or native management response bodies enter Host state.
import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"
)

type providerPreset struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

var providerPresets = []providerPreset{{"zhipu", "智谱 · 按量 API"}, {"zai", "Z.ai · 按量 API"}}
var providerRequestID = regexp.MustCompile(`^[A-Za-z0-9_-]{1,80}$`)

type providerInput struct {
	RequestID        string   `json:"requestId"`
	Preset           string   `json:"preset"`
	Key              string   `json:"key"`
	Models           []string `json:"models"`
	ExpectedRevision string   `json:"expectedRevision"`
}
type providerPublic struct {
	ID         string   `json:"id"`
	Preset     string   `json:"preset"`
	Configured bool     `json:"configured"`
	Models     []string `json:"models"`
}
type providerSnapshot struct {
	Revision  string           `json:"revision"`
	Presets   []providerPreset `json:"presets"`
	Providers []providerPublic `json:"providers"`
}
type providerReceipt struct {
	Admission string            `json:"admission,omitempty"`
	RequestID string            `json:"requestId"`
	Preset    string            `json:"preset"`
	Models    []string          `json:"models"`
	Status    string            `json:"status"`
	Sync      map[string]string `json:"sync"`
}
type nativeProvider struct {
	ID     string   `json:"id"`
	Preset string   `json:"preset"`
	Chosen []string `json:"chosen"`
	Key    struct {
		Set bool `json:"set"`
	} `json:"key"`
	Chat    string            `json:"chat"`
	Proxy   string            `json:"proxy"`
	Headers map[string]string `json:"headers"`
	Models  []struct {
		ID string `json:"id"`
		On bool   `json:"on"`
	} `json:"models"`
}

func supportedPreset(id string) bool { return id == "zhipu" || id == "zai" }
func providerFailure() error {
	return fail("provider_unavailable", "Provider configuration could not be confirmed. Refresh the existing request; do not replay it.", 503)
}
func privateRegular(path string, limit int64) ([]byte, error) {
	f, e := os.Open(path)
	if e != nil {
		return nil, e
	}
	defer f.Close()
	i, e := f.Stat()
	if e != nil || !i.Mode().IsRegular() || i.Mode().Perm()&0077 != 0 || i.Size() > limit {
		return nil, fmt.Errorf("private file unavailable")
	}
	l, e := os.Lstat(path)
	if e != nil || l.Mode()&os.ModeSymlink != 0 {
		return nil, fmt.Errorf("private file unavailable")
	}
	return io.ReadAll(io.LimitReader(f, limit+1))
}

// Paths and cookie are server configuration only. Only these two management
// actions and a projected provider list can be reached, always on loopback.
func (s *Server) magpieManagement(ctx context.Context, action string, input any, output any) error {
	if s.cfg.MagpieWebKeyFile == "" {
		return providerFailure()
	}
	key, e := privateRegular(s.cfg.MagpieWebKeyFile, 4096)
	if e != nil {
		return providerFailure()
	}
	k := strings.TrimSpace(string(key))
	if k == "" || strings.ContainsAny(k, "\r\n ;\"\\,") {
		return providerFailure()
	}
	route := "/api/providers"
	method := "GET"
	var body io.Reader
	if action != "" {
		if action != "list" && action != "save" {
			return providerFailure()
		}
		route = "/api/provider/" + action
		method = "POST"
		b, _ := json.Marshal(input)
		body = bytes.NewReader(b)
	}
	req, e := http.NewRequestWithContext(ctx, method, "http://127.0.0.1:3430"+route, body)
	if e != nil {
		return providerFailure()
	}
	req.AddCookie(&http.Cookie{Name: "magpie_web_3430", Value: k})
	req.Header.Set("Content-Type", "application/json")
	res, e := s.http.Do(req)
	if e != nil {
		return providerFailure()
	}
	defer res.Body.Close()
	b, e := io.ReadAll(io.LimitReader(res.Body, 2*1024*1024+1))
	if e != nil || len(b) > 2*1024*1024 || res.StatusCode != 200 {
		return providerFailure()
	}
	var check map[string]json.RawMessage
	if json.Unmarshal(b, &check) != nil || check["error"] != nil {
		return providerFailure()
	}
	if output != nil && json.Unmarshal(b, output) != nil {
		return providerFailure()
	}
	return nil
}
func (s *Server) providerSnapshot(ctx context.Context) (providerSnapshot, []nativeProvider, error) {
	var raw struct {
		Providers []nativeProvider `json:"providers"`
	}
	if e := s.magpieManagement(ctx, "", nil, &raw); e != nil {
		return providerSnapshot{}, nil, e
	}
	out := providerSnapshot{Presets: providerPresets, Providers: []providerPublic{}}
	for _, p := range raw.Providers {
		if p.ID != "dash-"+p.Preset || !supportedPreset(p.Preset) {
			continue
		}
		m := append([]string{}, p.Chosen...)
		sort.Strings(m)
		out.Providers = append(out.Providers, providerPublic{p.ID, p.Preset, p.Key.Set, m})
	}
	sort.Slice(out.Providers, func(i, j int) bool { return out.Providers[i].ID < out.Providers[j].ID })
	// File identity detects key-only saves without reading any existing key.
	info, e := os.Stat(filepath.Join(s.cfg.MagpieConfigDir, "providers.json"))
	if e != nil {
		return out, nil, providerFailure()
	}
	b, _ := json.Marshal(out)
	sum := sha256.Sum256(append(b, []byte(fmt.Sprintf("/%d/%d", info.ModTime().UnixNano(), info.Size()))...))
	out.Revision = hex.EncodeToString(sum[:])
	return out, raw.Providers, nil
}
func (s *Server) providerReceiptPath(id string) string {
	return filepath.Join(s.cfg.DataDir, "provider-requests", id+".json")
}
func atomicPrivateJSON(path string, v any) error {
	dir := filepath.Dir(path)
	if e := os.MkdirAll(dir, 0700); e != nil {
		return e
	}
	i, e := os.Lstat(dir)
	if e != nil || !i.IsDir() || i.Mode()&os.ModeSymlink != 0 || i.Mode().Perm()&0022 != 0 {
		return fmt.Errorf("unsafe directory")
	}
	b, e := json.Marshal(v)
	if e != nil {
		return e
	}
	f, e := os.CreateTemp(dir, ".provider-*")
	if e != nil {
		return e
	}
	name := f.Name()
	defer os.Remove(name)
	if e = f.Chmod(0600); e == nil {
		_, e = f.Write(b)
	}
	if e == nil {
		e = f.Sync()
	}
	closeErr := f.Close()
	if e == nil {
		e = closeErr
	}
	if e != nil {
		return e
	}
	if e = os.Rename(name, path); e != nil {
		return e
	}
	d, e := os.Open(dir)
	if e != nil {
		return e
	}
	defer d.Close()
	return d.Sync()
}
func (s *Server) providerSettings(w http.ResponseWriter, r *http.Request) {
	if r.URL.RawQuery != "" {
		writeError(w, fail("invalid_query", "Provider settings do not accept query parameters", 400))
		return
	}
	s.providerMu.Lock()
	defer s.providerMu.Unlock()
	ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
	defer cancel()
	if r.Method == "GET" {
		v, _, e := s.providerSnapshot(ctx)
		if e != nil {
			writeError(w, e)
			return
		}
		writeJSON(w, 200, v)
		return
	}
	var in providerInput
	// Do not return JSON decoder diagnostics, which may echo an input key.
	if decode(w, r, &in) != nil || !supportedPreset(in.Preset) || len(in.Key) > 4096 || strings.ContainsAny(in.Key, "\r\n\x00") || len(in.Models) > 100 {
		writeError(w, fail("invalid_provider", "Invalid provider input", 400))
		return
	}
	if r.URL.Path == "/v1/provider-settings/models" {
		if strings.TrimSpace(in.Key) == "" {
			writeError(w, fail("key_required", "Enter an API key to fetch models", 400))
			return
		}
		var result struct {
			Models []struct {
				ID   string `json:"id"`
				Name string `json:"name"`
			} `json:"models"`
		}
		if e := s.magpieManagement(ctx, "list", map[string]any{"preset": in.Preset, "key": in.Key}, &result); e != nil {
			writeError(w, fail("provider_catalog_unavailable", "Models could not be fetched. Check the API key and try again.", 400))
			return
		}
		models := []map[string]string{}
		for _, m := range result.Models {
			if safeProviderModel(m.ID) {
				name := m.Name
				if name == "" {
					name = m.ID
				}
				if len(name) > 200 {
					name = m.ID
				}
				models = append(models, map[string]string{"id": m.ID, "name": name})
			}
		}
		writeJSON(w, 200, map[string]any{"models": models})
		return
	}
	if !providerRequestID.MatchString(in.RequestID) || in.ExpectedRevision == "" || len(in.Models) == 0 {
		writeError(w, fail("invalid_provider", "Request identity, revision and selected models are required", 400))
		return
	}
	sort.Strings(in.Models)
	for i, m := range in.Models {
		if !safeProviderModel(m) || i > 0 && m == in.Models[i-1] {
			writeError(w, fail("invalid_provider", "Select distinct listed models", 400))
			return
		}
	}
	path := s.providerReceiptPath(in.RequestID)
	if b, e := privateRegular(path, 65536); e == nil {
		var receipt providerReceipt
		if json.Unmarshal(b, &receipt) != nil {
			writeError(w, providerFailure())
			return
		}
		if receipt.Preset != in.Preset || strings.Join(receipt.Models, "\x00") != strings.Join(in.Models, "\x00") {
			writeError(w, fail("request_conflict", "Use the original request identity and selection", 409))
			return
		}
		// The key is deliberately absent: an existing request never re-applies it.
		writeJSON(w, 200, receipt)
		return
	} else if !os.IsNotExist(e) {
		writeError(w, providerFailure())
		return
	}
	snapshot, providers, e := s.providerSnapshot(ctx)
	if e != nil {
		writeError(w, e)
		return
	}
	if snapshot.Revision != in.ExpectedRevision {
		writeError(w, fail("provider_conflict", "Provider configuration changed. Refresh before saving", 409))
		return
	}
	exists := false
	for _, p := range providers {
		if p.ID == "dash-"+in.Preset {
			exists = true
			expected := "https://open.bigmodel.cn/api/paas/v4"
			if in.Preset == "zai" {
				expected = "https://api.z.ai/api/paas/v4"
			}
			if p.Preset != in.Preset || p.Chat != expected || p.Proxy != "" || len(p.Headers) != 0 {
				writeError(w, fail("provider_conflict", "This provider needs native Magpie review", 409))
				return
			}
		}
	}
	if !exists && strings.TrimSpace(in.Key) == "" {
		writeError(w, fail("key_required", "A new provider requires an API key", 400))
		return
	}
	// Verify a typed key by listing; this does not send paid model requests.
	if in.Key != "" {
		var list struct {
			Models []struct {
				ID string `json:"id"`
			} `json:"models"`
		}
		if s.magpieManagement(ctx, "list", map[string]any{"preset": in.Preset, "key": in.Key}, &list) != nil {
			writeError(w, fail("provider_catalog_unavailable", "Check the API key before saving", 400))
			return
		}
		allowed := map[string]bool{}
		for _, m := range list.Models {
			allowed[m.ID] = true
		}
		for _, m := range in.Models {
			if !allowed[m] {
				writeError(w, fail("model_unavailable", "Select models from the current provider list", 400))
				return
			}
		}
	} else {
		for _, m := range in.Models {
			found := false
			for _, p := range providers {
				if p.ID == "dash-"+in.Preset {
					for _, x := range p.Models {
						if x.ID == m {
							found = true
						}
					}
				}
			}
			if !found {
				writeError(w, fail("model_unavailable", "Fetch models with a key before adding a selection", 400))
				return
			}
		}
	}
	latest, _, err := s.providerSnapshot(ctx)
	if err != nil {
		writeError(w, err)
		return
	}
	if latest.Revision != in.ExpectedRevision {
		writeError(w, fail("provider_conflict", "Provider configuration changed. Refresh before saving", 409))
		return
	}
	s.providerAdmission.Lock()
	defer s.providerAdmission.Unlock()
	s.piLifecycle.Lock()
	defer s.piLifecycle.Unlock()
	if e := s.acquireProviderFence(ctx, in.RequestID); e != nil {
		writeError(w, e)
		return
	}
	receipt := providerReceipt{Admission: "held", RequestID: in.RequestID, Preset: in.Preset, Models: in.Models, Status: "unknown", Sync: map[string]string{}}
	if atomicPrivateJSON(path, receipt) != nil {
		writeError(w, providerFailure())
		return
	}
	if s.magpieManagement(ctx, "save", map[string]any{"id": "dash-" + in.Preset, "preset": in.Preset, "key": in.Key, "models": in.Models, "noModels": false}, nil) != nil {
		writeJSON(w, 202, receipt)
		return
	}
	receipt.Status = "saved"
	if atomicPrivateJSON(path, receipt) != nil {
		writeError(w, providerFailure())
		return
	}
	receipt.Sync = s.syncProviderModels(ctx, receipt)
	if atomicPrivateJSON(path, receipt) != nil {
		writeError(w, providerFailure())
		return
	}
	if s.releaseProviderFence(in.RequestID) != nil {
		writeError(w, providerFailure())
		return
	}
	receipt.Admission = "released"
	if atomicPrivateJSON(path, receipt) != nil {
		writeError(w, providerFailure())
		return
	}
	writeJSON(w, 200, receipt)
}
func safeProviderModel(id string) bool {
	return id != "" && len(id) <= 160 && !strings.ContainsAny(id, " \t\r\n\x00/")
}
func (s *Server) providerRequest(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("requestId")
	if !providerRequestID.MatchString(id) || r.URL.RawQuery != "" {
		writeError(w, fail("invalid_request", "Invalid request identity", 400))
		return
	}
	s.providerMu.Lock()
	defer s.providerMu.Unlock()
	b, e := privateRegular(s.providerReceiptPath(id), 65536)
	if e != nil {
		if os.IsNotExist(e) {
			writeError(w, fail("request_not_found", "Request has not been recorded; do not automatically replay", 404))
		} else {
			writeError(w, providerFailure())
		}
		return
	}
	var receipt providerReceipt
	if json.Unmarshal(b, &receipt) != nil {
		writeError(w, providerFailure())
		return
	}
	if r.Method == "POST" {
		if receipt.Status != "saved" {
			writeError(w, fail("provider_unconfirmed", "Only a confirmed save can retry catalog sync", 409))
			return
		}
		s.providerAdmission.Lock()
		defer s.providerAdmission.Unlock()
		s.piLifecycle.Lock()
		defer s.piLifecycle.Unlock()
		if e := s.acquireProviderFence(r.Context(), id); e != nil {
			writeError(w, e)
			return
		}
		receipt.Admission = "held"
		receipt.Sync = s.syncProviderModels(r.Context(), receipt)
		if atomicPrivateJSON(s.providerReceiptPath(id), receipt) != nil {
			writeError(w, providerFailure())
			return
		}
		if s.releaseProviderFence(id) != nil {
			writeError(w, providerFailure())
			return
		}
		receipt.Admission = "released"
		if atomicPrivateJSON(s.providerReceiptPath(id), receipt) != nil {
			writeError(w, providerFailure())
			return
		}
	}
	writeJSON(w, 200, receipt)
}
func (s *Server) syncProviderModels(ctx context.Context, receipt providerReceipt) map[string]string {
	status := map[string]string{}
	dirs := map[string]string{"awf": s.cfg.PiAgentDir, "x-studio": s.cfg.ContentPiAgentDir, "x-studio-durable": s.cfg.ContentDurablePiAgentDir}
	req, _ := http.NewRequestWithContext(ctx, "GET", "http://127.0.0.1:3425/v1/models", nil)
	req.Header.Set("Authorization", "Bearer magpie")
	res, e := s.http.Do(req)
	if e != nil {
		for name := range dirs {
			status[name] = "failed"
		}
		return status
	}
	defer res.Body.Close()
	var catalog struct {
		Data []struct {
			ID        string   `json:"id"`
			Name      string   `json:"display_name"`
			Context   int      `json:"context_window"`
			Output    int      `json:"max_output_tokens"`
			Reasoning bool     `json:"reasoning"`
			Input     []string `json:"modalities"`
		} `json:"data"`
	}
	b, e := io.ReadAll(io.LimitReader(res.Body, 2*1024*1024+1))
	if e != nil || res.StatusCode != 200 || len(b) > 2*1024*1024 || json.Unmarshal(b, &catalog) != nil {
		for name := range dirs {
			status[name] = "failed"
		}
		return status
	}
	for _, id := range receipt.Models {
		found := false
		for _, m := range catalog.Data {
			if m.ID == "dash-"+receipt.Preset+"/"+id {
				found = true
			}
		}
		if !found {
			for name := range dirs {
				status[name] = "failed"
			}
			return status
		}
	}
	for name, dir := range dirs {
		status[name] = "failed"
		if dir == "" {
			continue
		}
		path := filepath.Join(dir, "models.json")
		b, e := privateRegular(path, 1024*1024)
		if e != nil {
			continue
		}
		var root map[string]json.RawMessage
		var providers map[string]json.RawMessage
		var block map[string]json.RawMessage
		var existing []map[string]any
		if rejectDuplicateJSONKeys(b) != nil || json.Unmarshal(b, &root) != nil || json.Unmarshal(root["providers"], &providers) != nil || json.Unmarshal(providers["magpie"], &block) != nil || json.Unmarshal(block["models"], &existing) != nil {
			continue
		}
		var base, api, key string
		json.Unmarshal(block["baseUrl"], &base)
		json.Unmarshal(block["api"], &api)
		json.Unmarshal(block["apiKey"], &key)
		if base != "http://127.0.0.1:3425/v1" || api != "openai-completions" || key != "magpie" {
			continue
		}
		models := []map[string]any{}
		for _, m := range existing {
			id, _ := m["id"].(string)
			if !strings.HasPrefix(id, "dash-"+receipt.Preset+"/") {
				models = append(models, m)
			}
		}
		valid := true
		for _, m := range catalog.Data {
			if !strings.HasPrefix(m.ID, "dash-"+receipt.Preset+"/") {
				continue
			}
			if m.Context <= 0 || m.Output <= 0 || m.Output > m.Context {
				valid = false
				break
			}
			input := []string{"text"}
			for _, i := range m.Input {
				if i == "image" {
					input = append(input, "image")
				}
			}
			modelName := m.Name
			if modelName == "" {
				modelName = m.ID
			}
			models = append(models, map[string]any{"id": m.ID, "name": modelName, "reasoning": m.Reasoning, "input": input, "contextWindow": m.Context, "maxTokens": m.Output})
		}
		if !valid {
			continue
		}
		block["models"], _ = json.Marshal(models)
		providers["magpie"], _ = json.Marshal(block)
		root["providers"], _ = json.Marshal(providers)
		if atomicPrivateJSON(path, root) == nil {
			status[name] = "synced"
		}
	}
	return status
}
