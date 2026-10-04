package host

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
	"github.com/atongrun/agent-workflow/internal/pi"
)

type modelCatalog struct {
	Revision string    `json:"revision"`
	Models   []piModel `json:"models"`
}
type modelPreference struct {
	Revision int          `json:"revision"`
	Model    core.PiModel `json:"model"`
}
type modelSettingsSnapshot struct {
	Catalog      modelCatalog    `json:"catalog"`
	Preference   modelPreference `json:"preference"`
	EffectiveFor string          `json:"effectiveFor"`
}
type modelSettingsInput struct {
	Model                   core.PiModel `json:"model"`
	ExpectedRevision        *int         `json:"expectedRevision"`
	ExpectedCatalogRevision string       `json:"expectedCatalogRevision"`
}

func modelRefValid(m core.PiModel) bool {
	return m.Provider != "" && m.ID != "" && len(m.Provider) <= 200 && len(m.ID) <= 300 && !strings.ContainsAny(m.Provider+m.ID, " \t\r\n\x00")
}
func catalogContains(c modelCatalog, m core.PiModel) bool {
	for _, entry := range c.Models {
		if entry.Provider == m.Provider && entry.ID == m.ID {
			return true
		}
	}
	return false
}

// Read only the server-selected native models.json. Never evaluate keys,
// commands or environment interpolation, or expose transport configuration.
func (s *Server) modelCatalog() (modelCatalog, error) {
	unavailable := fail("model_catalog_unavailable", "the configured Pi model catalog is unavailable or unsupported", 503)
	f, err := os.Open(filepath.Join(s.cfg.PiAgentDir, "models.json"))
	if err != nil {
		return modelCatalog{}, unavailable
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil || !info.Mode().IsRegular() || info.Size() > 1024*1024 {
		return modelCatalog{}, unavailable
	}
	b, err := io.ReadAll(io.LimitReader(f, 1024*1024+1))
	if err != nil || len(b) > 1024*1024 {
		return modelCatalog{}, unavailable
	}
	var root struct {
		Providers map[string]json.RawMessage `json:"providers"`
	}
	if rejectDuplicateJSONKeys(b) != nil || json.Unmarshal(b, &root) != nil {
		return modelCatalog{}, unavailable
	}
	var provider struct {
		BaseURL string                       `json:"baseUrl"`
		API     string                       `json:"api"`
		APIKey  string                       `json:"apiKey"`
		Headers json.RawMessage              `json:"headers"`
		Models  []map[string]json.RawMessage `json:"models"`
	}
	providerDecoder := json.NewDecoder(bytes.NewReader(root.Providers[s.cfg.PiProvider]))
	providerDecoder.DisallowUnknownFields()
	if providerDecoder.Decode(&provider) != nil {
		return modelCatalog{}, unavailable
	}
	u, err := url.Parse(provider.BaseURL)
	if err != nil || u.Scheme != "http" || (u.Hostname() != "127.0.0.1" && u.Hostname() != "localhost" && u.Hostname() != "::1") || u.Port() != "3425" || u.Path != "/v1" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || provider.API != "openai-completions" || provider.APIKey != "magpie" || len(provider.Headers) != 0 || len(provider.Models) == 0 || len(provider.Models) > 2000 {
		return modelCatalog{}, unavailable
	}
	models := make([]piModel, 0, len(provider.Models))
	seen := map[string]bool{}
	for _, raw := range provider.Models {
		// Per-model transport overrides cannot escape the configured gateway.
		for _, key := range []string{"baseUrl", "apiKey", "headers", "authHeader", "api"} {
			if _, exists := raw[key]; exists {
				return modelCatalog{}, unavailable
			}
		}
		var id, name string
		if json.Unmarshal(raw["id"], &id) != nil {
			return modelCatalog{}, unavailable
		}
		if v, exists := raw["name"]; exists && json.Unmarshal(v, &name) != nil {
			return modelCatalog{}, unavailable
		}
		if !modelRefValid(core.PiModel{Provider: s.cfg.PiProvider, ID: id}) || seen[id] || len(name) > 500 || strings.ContainsAny(name, "\r\n\x00") {
			return modelCatalog{}, unavailable
		}
		seen[id] = true
		if name == "" {
			name = id
		}
		models = append(models, piModel{Provider: s.cfg.PiProvider, ID: id, Name: name})
	}
	sort.Slice(models, func(i, j int) bool { return models[i].ID < models[j].ID })
	// Include the validated server-side source bytes in the opaque revision so
	// capability/transport changes also invalidate stale selections.
	sum := sha256.Sum256(b)
	return modelCatalog{Revision: hex.EncodeToString(sum[:]), Models: models}, nil
}

func rejectDuplicateJSONKeys(b []byte) error {
	d := json.NewDecoder(bytes.NewReader(b))
	var value func() error
	value = func() error {
		token, err := d.Token()
		if err != nil {
			return err
		}
		delim, compound := token.(json.Delim)
		if !compound {
			return nil
		}
		seen := map[string]bool{}
		for d.More() {
			if delim == '{' {
				key, err := d.Token()
				if err != nil {
					return err
				}
				name, ok := key.(string)
				if !ok || seen[name] {
					return errors.New("duplicate or invalid JSON key")
				}
				seen[name] = true
			}
			if err := value(); err != nil {
				return err
			}
		}
		_, err = d.Token()
		return err
	}
	return value()
}
func modelSnapshot(c modelCatalog, settings core.Settings) modelSettingsSnapshot {
	return modelSettingsSnapshot{Catalog: c, Preference: modelPreference{Revision: settings.PiModelRevision, Model: settings.PiDefaultModel}, EffectiveFor: "new_sessions"}
}
func (s *Server) modelSettings(w http.ResponseWriter, r *http.Request) {
	if len(r.URL.Query()) != 0 {
		writeError(w, fail("invalid_query", "model settings do not accept query parameters", 400))
		return
	}
	var in modelSettingsInput
	if r.Method == "PATCH" {
		if err := decode(w, r, &in); err != nil {
			writeError(w, err)
			return
		}
		if !modelRefValid(in.Model) || in.ExpectedRevision == nil || *in.ExpectedRevision < 0 || in.ExpectedCatalogRevision == "" {
			writeError(w, fail("invalid_model_settings", "model and both expected revisions are required", 400))
			return
		}
	}
	catalog, err := s.modelCatalog()
	if err != nil {
		writeError(w, err)
		return
	}
	var settings core.Settings
	if r.Method == "GET" {
		settings = s.store.Snapshot().Settings
	} else {
		err = s.store.Update(func(st *core.State) error {
			current, err := s.modelCatalog()
			if err != nil {
				return err
			}
			catalog = current
			if *in.ExpectedRevision != st.Settings.PiModelRevision || in.ExpectedCatalogRevision != catalog.Revision {
				return fail("model_settings_conflict", "model settings or catalog changed; refresh before selecting", 409)
			}
			if !catalogContains(catalog, in.Model) {
				return fail("model_not_allowed", "select a model from the current allowed catalog", 400)
			}
			st.Settings.PiDefaultModel = in.Model
			st.Settings.PiModelRevision++
			settings = st.Settings
			core.Emit(st, "", "model.preference_changed", modelSnapshot(catalog, settings))
			return nil
		})
		if err != nil {
			writeError(w, err)
			return
		}
	}
	writeJSON(w, 200, modelSnapshot(catalog, settings))
}

func (s *Server) allowedNativeModel(model *piModel) error {
	catalog, err := s.modelCatalog()
	if err != nil {
		return err
	}
	if model == nil || !catalogContains(catalog, core.PiModel{Provider: model.Provider, ID: model.ID}) {
		return fail("needs_model_selection", "select an allowed model through the idle Pi model control before generating", 409)
	}
	return nil
}
func nativeModelRef(model *piModel) *core.PiModel {
	if model == nil || !validModel(*model) {
		return nil
	}
	return &core.PiModel{Provider: model.Provider, ID: model.ID}
}
func modelRefsEqual(a, b *core.PiModel) bool { return a != nil && b != nil && *a == *b }

func (s *Server) verifyPiGeneration(client *pi.Client, ref *core.Session) error {
	// Implemented by the same native transport; no model request is submitted.
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	data, err := client.Call(ctx, "get_state", nil)
	if err != nil {
		return fail("pi_unavailable", "Pi model state could not be verified", 503)
	}
	var state struct {
		SessionID string   `json:"sessionId"`
		Model     *piModel `json:"model"`
	}
	if json.Unmarshal(data, &state) != nil || state.SessionID != ref.ID {
		return fail("stale_pi_session", "native session changed before generation", 409)
	}
	if !modelRefsEqual(ref.Model, nativeModelRef(state.Model)) {
		return fail("needs_model_selection", "native model changed; explicitly select an allowed idle model", 409)
	}
	return s.allowedNativeModel(state.Model)
}
