package host

import (
	"encoding/json"
	"fmt"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"

	"github.com/atongrun/agent-workflow/internal/core"
)

func writeModelCatalog(t *testing.T, s *Server, provider string, ids []string) {
	t.Helper()
	models := []map[string]string{}
	for _, id := range ids {
		models = append(models, map[string]string{"id": id, "name": "Model " + id})
	}
	data, _ := json.Marshal(map[string]any{"providers": map[string]any{provider: map[string]any{"baseUrl": "http://localhost:3425/v1", "api": "openai-completions", "apiKey": "magpie", "models": models}}})
	if err := os.MkdirAll(s.cfg.PiAgentDir, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(s.cfg.PiAgentDir, "models.json"), data, 0600); err != nil {
		t.Fatal(err)
	}
}
func readModelSettings(t *testing.T, s *Server) modelSettingsSnapshot {
	t.Helper()
	w := call(t, s, "GET", "/v1/model-settings", nil)
	if w.Code != 200 {
		t.Fatal(w.Code, w.Body.String())
	}
	var out modelSettingsSnapshot
	if err := json.Unmarshal(w.Body.Bytes(), &out); err != nil {
		t.Fatal(err)
	}
	return out
}
func selectModelInput(snapshot modelSettingsSnapshot, provider, id string) modelSettingsInput {
	return modelSettingsInput{Model: core.PiModel{Provider: provider, ID: id}, ExpectedRevision: &snapshot.Preference.Revision, ExpectedCatalogRevision: snapshot.Catalog.Revision}
}

func TestModelSettingsCatalogCASPersistenceAndNoTaskEffects(t *testing.T) {
	s := testServer(t)
	writeModelCatalog(t, s, "magpie", []string{"deepseek/deepseek-v4-pro", "qwen-cn/qwen3.8-flash"})
	task := createTask(t, s, "preserve-task")
	before, _ := s.task(task.ID)
	snapshot := readModelSettings(t, s)
	if snapshot.EffectiveFor != "new_sessions" || snapshot.Preference.Model != core.Defaults().PiDefaultModel || len(snapshot.Catalog.Models) != 2 || len(snapshot.Catalog.Revision) != 64 {
		t.Fatal(snapshot)
	}
	w := call(t, s, "GET", "/v1/model-settings", nil)
	for _, secret := range []string{"baseUrl", "apiKey", "headers", "localhost", "pi-agent"} {
		if strings.Contains(w.Body.String(), secret) {
			t.Fatal("transport leaked", secret)
		}
	}
	in := selectModelInput(snapshot, "magpie", "qwen-cn/qwen3.8-flash")
	var wg sync.WaitGroup
	codes := make(chan int, 12)
	for range 12 {
		wg.Add(1)
		go func() { defer wg.Done(); codes <- call(t, s, "PATCH", "/v1/model-settings", in).Code }()
	}
	wg.Wait()
	close(codes)
	writes := 0
	for code := range codes {
		if code == 200 {
			writes++
		} else if code != 409 {
			t.Fatal(code)
		}
	}
	if writes != 1 {
		t.Fatal("CAS wrote more than once", writes)
	}
	after, _ := s.task(task.ID)
	if !reflect.DeepEqual(before, after) || len(s.clients) != 0 {
		t.Fatal("global default changed a task or started Pi")
	}
	confirmed := readModelSettings(t, s)
	if confirmed.Preference.Revision != 1 || confirmed.Preference.Model != in.Model {
		t.Fatal(confirmed)
	}
	// A lost PATCH response is reconciled by GET, never a blind replay.
	if w := call(t, s, "PATCH", "/v1/model-settings", in); w.Code != 409 {
		t.Fatal("stale retry applied", w.Code)
	}
	s.Close()
	reopened, err := New(s.cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	if got := readModelSettings(t, reopened); !reflect.DeepEqual(got, confirmed) {
		t.Fatal("preference lost after restart", got)
	}
}

func TestModelSettingsValidationAndCatalogRevision(t *testing.T) {
	s := testServer(t)
	writeModelCatalog(t, s, "magpie", []string{"deepseek/deepseek-v4-pro", "qwen-cn/qwen3.8-flash"})
	snapshot := readModelSettings(t, s)
	for _, body := range []any{
		map[string]any{"model": snapshot.Preference.Model, "expectedCatalogRevision": snapshot.Catalog.Revision},
		map[string]any{"model": snapshot.Preference.Model, "expectedRevision": 0},
		map[string]any{"model": snapshot.Preference.Model, "expectedRevision": 0, "expectedCatalogRevision": snapshot.Catalog.Revision, "baseUrl": "http://evil.invalid"},
		map[string]any{"model": snapshot.Preference.Model, "expectedRevision": 0, "expectedCatalogRevision": snapshot.Catalog.Revision, "apiKey": "secret"},
		selectModelInput(snapshot, "deepseek", "deepseek-chat"), selectModelInput(snapshot, "magpie", "missing"),
	} {
		if w := call(t, s, "PATCH", "/v1/model-settings", body); w.Code != 400 {
			t.Fatal(w.Code, w.Body.String())
		}
	}
	writeModelCatalog(t, s, "magpie", []string{"deepseek/deepseek-v4-pro"})
	if w := call(t, s, "PATCH", "/v1/model-settings", selectModelInput(snapshot, "magpie", "qwen-cn/qwen3.8-flash")); w.Code != 409 {
		t.Fatal("stale catalog accepted", w.Code)
	}
	if s.store.Snapshot().Settings.PiModelRevision != 0 {
		t.Fatal("rejected patch changed revision")
	}
}

func TestModelCatalogFailClosed(t *testing.T) {
	for _, mode := range []string{"missing", "directory", "malformed", "remote", "secret_command", "model_override", "provider_override", "duplicate_id", "duplicate_key"} {
		t.Run(mode, func(t *testing.T) {
			s := testServer(t)
			writeModelCatalog(t, s, "magpie", []string{"deepseek/deepseek-v4-pro"})
			path := filepath.Join(s.cfg.PiAgentDir, "models.json")
			b, _ := os.ReadFile(path)
			switch mode {
			case "missing":
				os.Remove(path)
			case "directory":
				os.Remove(path)
				os.Mkdir(path, 0700)
			case "malformed":
				b = []byte("{")
			case "remote":
				b = []byte(strings.Replace(string(b), "http://localhost:3425/v1", "https://remote.invalid/v1", 1))
			case "secret_command":
				b = []byte(strings.Replace(string(b), `"apiKey":"magpie"`, `"apiKey":"!echo secret"`, 1))
			case "model_override":
				b = []byte(strings.Replace(string(b), `"id":"deepseek/deepseek-v4-pro"`, `"id":"deepseek/deepseek-v4-pro","baseUrl":"https://remote.invalid"`, 1))
			case "provider_override":
				b = []byte(strings.Replace(string(b), `"apiKey":"magpie"`, `"apiKey":"magpie","modelOverrides":{"deepseek/deepseek-v4-pro":{"baseUrl":"https://remote.invalid"}}`, 1))
			case "duplicate_id":
				writeModelCatalog(t, s, "magpie", []string{"deepseek/deepseek-v4-pro", "deepseek/deepseek-v4-pro"})
			case "duplicate_key":
				b = []byte(strings.Replace(string(b), `"apiKey":"magpie"`, `"apiKey":"secret","apiKey":"magpie"`, 1))
			}
			if mode != "missing" && mode != "directory" && mode != "duplicate_id" {
				if err := os.WriteFile(path, b, 0600); err != nil {
					t.Fatal(err)
				}
			}
			if w := call(t, s, "GET", "/v1/model-settings", nil); w.Code != 503 || strings.Contains(w.Body.String(), "secret") || strings.Contains(w.Body.String(), "remote.invalid") {
				t.Fatal(w.Code, w.Body.String())
			}
			if len(s.clients) != 0 {
				t.Fatal("catalog read started a process")
			}
		})
	}
}

func TestModelSettingsPersistenceFailureAndAuthentication(t *testing.T) {
	s := testServer(t)
	writeModelCatalog(t, s, "magpie", []string{"deepseek/deepseek-v4-pro", "qwen-cn/qwen3.8-flash"})
	snapshot := readModelSettings(t, s)
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, httptest.NewRequest("GET", "/v1/model-settings", nil))
	if w.Code != 401 {
		t.Fatal("model settings bypassed auth", w.Code)
	}
	path := filepath.Join(s.cfg.DataDir, "state.json")
	backup := path + "-saved"
	if err := os.Rename(path, backup); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(path, 0700); err != nil {
		t.Fatal(err)
	}
	defer func() { os.Remove(path); os.Rename(backup, path) }()
	if w := call(t, s, "PATCH", "/v1/model-settings", selectModelInput(snapshot, "magpie", "qwen-cn/qwen3.8-flash")); w.Code != 500 {
		t.Fatal("failed persistence reported success", w.Code)
	}
	if settings := s.store.Snapshot().Settings; settings.PiModelRevision != 0 || settings.PiDefaultModel != snapshot.Preference.Model {
		t.Fatal("failed persistence exposed new preference", settings)
	}
}

func TestPiGlobalDefaultOnlyAffectsNewNativeSessions(t *testing.T) {
	s, task, _, log, _ := piControlFixture(t, "")
	s.cfg.MaxPiProcesses = 2
	original, _ := s.task(task.ID)
	snapshot := readModelSettings(t, s)
	// The product preference is writable while a task has active work.
	if err := s.store.Update(func(st *core.State) error { st.Tasks[task.ID].Sessions["architect"].Busy = true; return nil }); err != nil {
		t.Fatal(err)
	}
	if w := call(t, s, "PATCH", "/v1/model-settings", selectModelInput(snapshot, "test", "two")); w.Code != 200 {
		t.Fatal(w.Code, w.Body.String())
	}
	current, _ := s.task(task.ID)
	if !modelRefsEqual(current.Sessions["architect"].Model, original.Sessions["architect"].Model) || current.Sessions["architect"].ID != original.Sessions["architect"].ID || methodCount(t, log, "set_model") != 0 {
		t.Fatal("default mutated existing native session")
	}
	other := createTask(t, s, "new-native-default")
	if _, err := s.client(other.ID, "architect"); err != nil {
		t.Fatal(err)
	}
	other, _ = s.task(other.ID)
	if other.Sessions["architect"].Model == nil || other.Sessions["architect"].Model.ID != "two" || other.Sessions["architect"].ModelStatus != "ready" {
		t.Fatal("new session ignored preference", other.Sessions["architect"])
	}
}

func TestPiOldSessionVerifiedModelAndExplicitRecovery(t *testing.T) {
	for _, allowed := range []bool{true, false} {
		t.Run(map[bool]string{true: "allowed", false: "requires_selection"}[allowed], func(t *testing.T) {
			s, task, _, log, _ := piControlFixture(t, "")
			s.Close()
			ref := task.Sessions["architect"]
			model := piModel{Provider: "test", ID: "two", Name: "Restored"}
			if !allowed {
				model = piModel{Provider: "deepseek", ID: "old-direct-model", Name: "Unavailable old provider"}
			}
			history := filepath.Join(t.TempDir(), "native.jsonl")
			b, _ := json.Marshal(map[string]any{"sessionId": ref.ID, "model": model})
			if err := os.WriteFile(history, b, 0600); err != nil {
				t.Fatal(err)
			}
			st, err := core.Open(s.cfg.DataDir)
			if err != nil {
				t.Fatal(err)
			}
			if err := st.Update(func(state *core.State) error {
				x := state.Tasks[task.ID].Sessions["architect"]
				x.File, x.Persisted, x.Model, x.ModelStatus = history, true, nil, ""
				return nil
			}); err != nil {
				t.Fatal(err)
			}
			st.Close()
			if err := os.WriteFile(log, nil, 0600); err != nil {
				t.Fatal(err)
			}
			t.Setenv("PI_CODING_AGENT_DIR", "/inherited-must-not-be-used")
			reopened, err := New(s.cfg)
			if err != nil {
				t.Fatal(err)
			}
			defer reopened.Close()
			if _, err := reopened.client(task.ID, "architect"); err != nil {
				t.Fatal(err)
			}
			current, _ := reopened.task(task.ID)
			got := current.Sessions["architect"]
			if got.ID != ref.ID || got.Model == nil || got.Model.Provider != model.Provider || got.Model.ID != model.ID {
				t.Fatal("resume guessed a model or replaced session", got)
			}
			raw, _ := os.ReadFile(log)
			var launch struct {
				Args     []string `json:"args"`
				AgentDir string   `json:"agentDir"`
			}
			if json.Unmarshal([]byte(strings.SplitN(string(raw), "\n", 2)[0]), &launch) != nil || launch.AgentDir != s.cfg.PiAgentDir {
				t.Fatal("resume used inherited directory", launch)
			}
			for _, arg := range launch.Args {
				if arg == "--model" || arg == "--provider" {
					t.Fatal("resume overrode native selection")
				}
			}
			if !allowed {
				if got.ModelStatus != "needs_model_selection" {
					t.Fatal(got)
				}
				if w := call(t, reopened, "POST", "/v1/tasks/"+task.ID+"/messages", actionInput{RequestID: "blocked-model-prompt", Text: "must not reach model", Role: "architect"}); w.Code != 409 || !strings.Contains(w.Body.String(), "needs_model_selection") {
					t.Fatal(w.Code, w.Body.String())
				}
				in := piControlInput{RequestID: "explicit-recovery", Role: "architect", ExpectedSessionID: got.ID, ExpectedProcessID: got.ProcessID, Provider: "test", ModelID: "two"}
				if w := call(t, reopened, "POST", "/v1/tasks/"+task.ID+"/pi/model", in); w.Code != 202 {
					t.Fatal(w.Code, w.Body.String())
				}
				awaitPiRequest(t, reopened, in.RequestID, "completed")
				current, _ = reopened.task(task.ID)
				if current.Sessions["architect"].ID != ref.ID || current.Sessions["architect"].Model.ID != "two" || current.Sessions["architect"].ModelStatus != "ready" || methodCount(t, log, "set_model") != 1 || methodCount(t, log, "prompt") != 0 {
					t.Fatal("explicit recovery replaced session or generated")
				}
			}
			if after, _ := os.ReadFile(history); string(after) != string(b) {
				t.Fatal("adapter rewrote native history")
			}
		})
	}
}

func TestPiFailedUnstartedModelCanUseChangedDefault(t *testing.T) {
	s, _, _, log, _ := piControlFixture(t, "")
	s.cfg.MaxPiProcesses = 2
	snapshot := readModelSettings(t, s)
	if w := call(t, s, "PATCH", "/v1/model-settings", selectModelInput(snapshot, "test", "missing")); w.Code != 200 {
		t.Fatal(w.Code)
	}
	task := createTask(t, s, "unstarted-recovery")
	if _, err := s.client(task.ID, "architect"); err == nil {
		t.Fatal("native unavailable model accepted")
	}
	snapshot = readModelSettings(t, s)
	if w := call(t, s, "PATCH", "/v1/model-settings", selectModelInput(snapshot, "test", "two")); w.Code != 200 {
		t.Fatal(w.Code)
	}
	if _, err := s.client(task.ID, "architect"); err != nil {
		t.Fatal("failed new session stranded by old default", err)
	}
	current, _ := s.task(task.ID)
	if current.Sessions["architect"].Model.ID != "two" || current.Sessions["architect"].ModelStatus != "ready" || methodCount(t, log, "prompt") != 0 {
		t.Fatal("unstarted recovery generated or lost model")
	}
}

func TestPiCrashWindowRecoversExactHistoryWithoutDefault(t *testing.T) {
	s, task, _, log, _ := piControlFixture(t, "")
	s.Close()
	historyDir := filepath.Join(s.cfg.DataDir, "sessions", task.ID, "architect")
	if err := os.MkdirAll(historyDir, 0700); err != nil {
		t.Fatal(err)
	}
	history := filepath.Join(historyDir, "fixture.jsonl")
	b, _ := json.Marshal(map[string]any{"type": "session", "id": task.Sessions["architect"].ID, "model": piModel{Provider: "test", ID: "two", Name: "Recovered"}})
	if err := os.WriteFile(history, b, 0600); err != nil {
		t.Fatal(err)
	}
	st, err := core.Open(s.cfg.DataDir)
	if err != nil {
		t.Fatal(err)
	}
	if err := st.Update(func(state *core.State) error {
		ref := state.Tasks[task.ID].Sessions["architect"]
		ref.File, ref.Persisted, ref.Model, ref.ModelStatus = "", false, nil, ""
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	st.Close()
	if err := os.WriteFile(log, nil, 0600); err != nil {
		t.Fatal(err)
	}
	reopened, err := New(s.cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	if _, err := reopened.client(task.ID, "architect"); err != nil {
		t.Fatal(err)
	}
	current, _ := reopened.task(task.ID)
	if current.Sessions["architect"].ID != task.Sessions["architect"].ID || current.Sessions["architect"].Model.ID != "two" {
		t.Fatal("crash recovery changed native session")
	}
	raw, _ := os.ReadFile(log)
	var launch struct {
		Args []string `json:"args"`
	}
	if json.Unmarshal([]byte(strings.SplitN(string(raw), "\n", 2)[0]), &launch) != nil {
		t.Fatal("invalid fixture launch")
	}
	sessionFlag := false
	for i, arg := range launch.Args {
		if arg == "--model" || arg == "--provider" || arg == "--session-id" {
			t.Fatal("crash recovery substituted new startup", launch.Args)
		}
		if arg == "--session" && i+1 < len(launch.Args) && launch.Args[i+1] == history {
			sessionFlag = true
		}
	}
	if !sessionFlag {
		t.Fatal("did not explicitly resume original history")
	}
	if after, _ := os.ReadFile(history); string(after) != string(b) {
		t.Fatal("rewrote crash-window history")
	}
}

func TestPiCrashWindowInvalidHistoryNeverLaunches(t *testing.T) {
	for _, header := range []string{`{"type":"session","id":"other-session"}`, `{bad`, strings.Repeat("x", 65537)} {
		t.Run(fmt.Sprintf("header-length-%d", len(header)), func(t *testing.T) {
			s, task, _, log, _ := piControlFixture(t, "")
			s.Close()
			dir := filepath.Join(s.cfg.DataDir, "sessions", task.ID, "architect")
			if err := os.MkdirAll(dir, 0700); err != nil {
				t.Fatal(err)
			}
			path := filepath.Join(dir, "unverified.jsonl")
			if err := os.WriteFile(path, []byte(header), 0600); err != nil {
				t.Fatal(err)
			}
			st, err := core.Open(s.cfg.DataDir)
			if err != nil {
				t.Fatal(err)
			}
			if err := st.Update(func(state *core.State) error {
				ref := state.Tasks[task.ID].Sessions["architect"]
				ref.File, ref.Persisted = "", false
				return nil
			}); err != nil {
				t.Fatal(err)
			}
			st.Close()
			if err := os.WriteFile(log, nil, 0600); err != nil {
				t.Fatal(err)
			}
			reopened, err := New(s.cfg)
			if err != nil {
				t.Fatal(err)
			}
			defer reopened.Close()
			if _, err := reopened.client(task.ID, "architect"); err == nil {
				t.Fatal("invalid history replaced by startup")
			}
			if b, _ := os.ReadFile(log); len(b) != 0 || len(reopened.clients) != 0 {
				t.Fatal("invalid history started Pi")
			}
			if b, _ := os.ReadFile(path); string(b) != header {
				t.Fatal("invalid history rewritten")
			}
		})
	}
}
