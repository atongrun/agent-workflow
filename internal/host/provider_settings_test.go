//go:build linux

package host

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"github.com/atongrun/agent-workflow/internal/core"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

type providerTransport func(*http.Request) (*http.Response, error)

func (f providerTransport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }
func providerFixture(t *testing.T) (*Server, *int, *bool) {
	t.Helper()
	s := testServer(t)
	s.providerMaintenanceCall = func(context.Context, string, bool) error { return nil }
	d := t.TempDir()
	s.cfg.MagpieWebKeyFile = filepath.Join(d, "web-key")
	s.cfg.MagpieConfigDir = d
	s.cfg.ContentServiceTokenFile = filepath.Join(d, "content-key")
	s.cfg.DurableConfig = filepath.Join(d, "durable-config")
	s.cfg.ContentPiAgentDir = filepath.Join(d, "content")
	s.cfg.ContentDurablePiAgentDir = filepath.Join(d, "durable")
	os.WriteFile(s.cfg.MagpieWebKeyFile, []byte("private-cookie"), 0600)
	os.WriteFile(filepath.Join(d, "providers.json"), []byte(`{"providers":[]}`), 0600)
	for _, dir := range []string{s.cfg.PiAgentDir, s.cfg.ContentPiAgentDir, s.cfg.ContentDurablePiAgentDir} {
		os.MkdirAll(dir, 0700)
		os.WriteFile(filepath.Join(dir, "models.json"), []byte(`{"other":"preserved","providers":{"magpie":{"baseUrl":"http://127.0.0.1:3425/v1","api":"openai-completions","apiKey":"magpie","models":[{"id":"qwen-cn/existing","contextWindow":1000,"maxTokens":500}]}}}`), 0600)
		os.WriteFile(filepath.Join(dir, "settings.json"), []byte(`{"defaultModel":"existing"}`), 0600)
	}
	writes := new(int)
	uncertain := new(bool)
	configured := false
	s.http = &http.Client{Transport: providerTransport(func(r *http.Request) (*http.Response, error) {
		if r.URL.Host != "127.0.0.1:3430" && r.URL.Host != "127.0.0.1:3425" {
			t.Fatal("unexpected network destination")
		}
		response := func(v any) *http.Response {
			b, _ := json.Marshal(v)
			return &http.Response{StatusCode: 200, Body: io.NopCloser(bytes.NewReader(b)), Header: http.Header{"Content-Type": []string{"application/json"}}}
		}
		if r.URL.Path == "/v1/models" {
			return response(map[string]any{"data": []any{map[string]any{"id": "dash-zhipu/glm-5", "context_window": 128000, "max_output_tokens": 8192, "reasoning": true, "modalities": map[string]any{"input": []string{"text"}, "output": []string{"text"}}}}}), nil
		}
		c, e := r.Cookie("magpie_web_3430")
		if e != nil || c.Value != "private-cookie" {
			t.Fatal("missing management cookie")
		}
		switch r.URL.Path {
		case "/api/providers":
			p := []any{}
			if configured {
				p = append(p, map[string]any{"id": "dash-zhipu", "preset": "zhipu", "chat": "https://open.bigmodel.cn/api/paas/v4", "chosen": []string{"glm-5"}, "key": map[string]any{"set": true, "masked": "DO-NOT-LEAK"}, "headers": map[string]string{}, "models": []any{map[string]any{"id": "glm-5", "on": true}}})
			}
			return response(map[string]any{"providers": p, "secret": "DO-NOT-LEAK"}), nil
		case "/api/provider/list":
			b, _ := io.ReadAll(r.Body)
			if strings.Contains(string(b), "bad-key") {
				return response(map[string]any{"error": "DO-NOT-LEAK bad-key"}), nil
			}
			return response(map[string]any{"models": []any{map[string]string{"id": "glm-5", "name": "GLM 5"}}, "key": "DO-NOT-LEAK"}), nil
		case "/api/provider/save":
			*writes++
			configured = true
			os.WriteFile(filepath.Join(d, "providers.json"), []byte(`{"providers":["saved"]}`), 0600)
			if *uncertain {
				return nil, errors.New("network DO-NOT-LEAK")
			}
			return response(map[string]any{"saved": true, "key": "DO-NOT-LEAK"}), nil
		default:
			t.Fatal("management action escaped allowlist", r.URL.Path)
			return nil, errors.New("unexpected path")
		}
	})}
	return s, writes, uncertain
}
func providerSave(t *testing.T, s *Server, id string) map[string]any {
	t.Helper()
	var v providerSnapshot
	w := call(t, s, "GET", "/v1/provider-settings", nil)
	if w.Code != 200 {
		t.Fatal(w.Code, w.Body.String())
	}
	json.Unmarshal(w.Body.Bytes(), &v)
	return map[string]any{"requestId": id, "preset": "zhipu", "key": "DO-NOT-LEAK", "models": []string{"glm-5"}, "expectedRevision": v.Revision}
}
func TestProviderSaveProjectionReplayAndSync(t *testing.T) {
	s, writes, _ := providerFixture(t)
	in := providerSave(t, s, "one")
	before := s.store.Snapshot().Settings
	w := call(t, s, "POST", "/v1/provider-settings", in)
	if w.Code != 200 || strings.Contains(w.Body.String(), "DO-NOT-LEAK") {
		t.Fatal(w.Code, w.Body.String())
	}
	var receipt providerReceipt
	json.Unmarshal(w.Body.Bytes(), &receipt)
	for _, v := range receipt.Sync {
		if v != "synced" {
			t.Fatal(receipt)
		}
	}
	if call(t, s, "POST", "/v1/provider-settings", in).Code != 200 || *writes != 1 {
		t.Fatal("duplicate save applied")
	}
	for _, dir := range []string{s.cfg.PiAgentDir, s.cfg.ContentPiAgentDir, s.cfg.ContentDurablePiAgentDir} {
		b, _ := os.ReadFile(filepath.Join(dir, "models.json"))
		if !strings.Contains(string(b), "qwen-cn/existing") || !strings.Contains(string(b), "dash-zhipu/glm-5") || strings.Contains(string(b), "DO-NOT-LEAK") {
			t.Fatal("sync did not preserve safe metadata")
		}
		b, _ = os.ReadFile(filepath.Join(dir, "settings.json"))
		if string(b) != `{"defaultModel":"existing"}` {
			t.Fatal("changed default")
		}
	}
	if s.store.Snapshot().Settings != before {
		t.Fatal("changed host defaults")
	}
	b, _ := os.ReadFile(s.providerReceiptPath("one"))
	if strings.Contains(string(b), "DO-NOT-LEAK") {
		t.Fatal("secret in receipt")
	}
	r := httptest.NewRecorder()
	s.Handler().ServeHTTP(r, httptest.NewRequest("GET", "/v1/provider-settings", nil))
	if r.Code != 401 {
		t.Fatal("missing auth")
	}
}
func TestProviderUnknownSurvivesRestartAndNeverReplays(t *testing.T) {
	s, writes, uncertain := providerFixture(t)
	*uncertain = true
	in := providerSave(t, s, "unknown")
	w := call(t, s, "POST", "/v1/provider-settings", in)
	if w.Code != 202 {
		t.Fatal(w.Code)
	}
	s.Close()
	reopened, e := New(s.cfg)
	if e != nil {
		t.Fatal(e)
	}
	defer reopened.Close()
	reopened.http = s.http
	reopened.providerMaintenanceCall = s.providerMaintenanceCall
	w = call(t, reopened, "POST", "/v1/provider-settings", in)
	if w.Code != 200 || *writes != 1 || !strings.Contains(w.Body.String(), "unknown") {
		t.Fatal("unknown replayed")
	}
	if call(t, reopened, "POST", "/v1/provider-settings/requests/unknown/sync", nil).Code != 409 {
		t.Fatal("synced unknown operation")
	}
}
func TestProviderConcurrentRevisionBadKeyAndPartialSync(t *testing.T) {
	s, writes, _ := providerFixture(t)
	in := providerSave(t, s, "bad")
	in["key"] = "bad-key"
	if call(t, s, "POST", "/v1/provider-settings", in).Code != 400 || *writes != 0 {
		t.Fatal("bad key mutated state")
	}
	in = providerSave(t, s, "one")
	os.Remove(filepath.Join(s.cfg.ContentPiAgentDir, "models.json"))
	var wg sync.WaitGroup
	codes := make(chan int, 2)
	for _, id := range []string{"one", "two"} {
		wg.Add(1)
		go func(id string) {
			defer wg.Done()
			p := map[string]any{}
			for k, v := range in {
				p[k] = v
			}
			p["requestId"] = id
			codes <- call(t, s, "POST", "/v1/provider-settings", p).Code
		}(id)
	}
	wg.Wait()
	close(codes)
	ok, conflict := 0, 0
	for c := range codes {
		if c == 200 {
			ok++
		} else if c == 409 {
			conflict++
		} else {
			t.Fatal(c)
		}
	}
	if ok != 1 || conflict != 1 || *writes != 1 {
		t.Fatal("CAS failed")
	}
	for _, id := range []string{"one", "two"} {
		w := call(t, s, "GET", "/v1/provider-settings/requests/"+id, nil)
		if w.Code == 200 {
			var r providerReceipt
			json.Unmarshal(w.Body.Bytes(), &r)
			if r.Sync["x-studio"] != "failed" || r.Sync["awf"] != "synced" {
				t.Fatal(r)
			}
		}
	}
}

func TestProviderConfirmedPartialSyncRecoversWithoutKey(t *testing.T) {
	s, writes, _ := providerFixture(t)
	in := providerSave(t, s, "recover")
	original, e := os.ReadFile(filepath.Join(s.cfg.ContentPiAgentDir, "models.json"))
	if e != nil {
		t.Fatal(e)
	}
	os.Remove(filepath.Join(s.cfg.ContentPiAgentDir, "models.json"))
	w := call(t, s, "POST", "/v1/provider-settings", in)
	if w.Code != 200 {
		t.Fatal(w.Code)
	}
	os.WriteFile(filepath.Join(s.cfg.ContentPiAgentDir, "models.json"), original, 0600)
	w = call(t, s, "POST", "/v1/provider-settings/requests/recover/sync", map[string]any{"requestId": "recover"})
	var r providerReceipt
	json.Unmarshal(w.Body.Bytes(), &r)
	if w.Code != 200 || r.Sync["x-studio"] != "synced" || *writes != 1 {
		t.Fatal("sync recovery resaved key", w.Code, r, *writes)
	}
}

func TestProviderActivityAndAdmissionRefuseBeforeSave(t *testing.T) {
	for _, kind := range []string{"active", "queued", "uncertain", "durable_busy"} {
		t.Run(kind, func(t *testing.T) {
			s, writes, _ := providerFixture(t)
			task := createTask(t, s, "catalog-test")
			if kind == "durable_busy" {
				s.providerMaintenanceCall = func(_ context.Context, _ string, release bool) error {
					if !release {
						return providerBusy()
					}
					return nil
				}
			} else {
				s.store.Update(func(st *core.State) error {
					switch kind {
					case "active":
						st.Tasks[task.ID].Sessions["architect"] = &core.Session{Busy: true}
					case "queued":
						st.Requests["queued"] = &core.Request{ID: "queued", TaskID: task.ID, Status: "accepted", Operation: "messages"}
					case "uncertain":
						st.Tasks[task.ID].Execution = &core.Execution{Status: "uncertain"}
					}
					return nil
				})
			}
			in := providerSave(t, s, "busy")
			w := call(t, s, "POST", "/v1/provider-settings", in)
			if w.Code != 409 || !strings.Contains(w.Body.String(), "provider_busy") || *writes != 0 {
				t.Fatal("busy save escaped admission", w.Code, w.Body, *writes)
			}
			if _, err := os.Stat(s.providerReceiptPath("busy")); !os.IsNotExist(err) {
				t.Fatal("busy request claimed native save")
			}
		})
	}
}
func TestProviderUnknownKeepsAdmissionFenceAfterRestart(t *testing.T) {
	s, writes, uncertain := providerFixture(t)
	*uncertain = true
	in := providerSave(t, s, "unknown-fence")
	if w := call(t, s, "POST", "/v1/provider-settings", in); w.Code != 202 {
		t.Fatal(w.Code, w.Body)
	}
	s.Close()
	reopened, err := New(s.cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	reopened.http = s.http
	reopened.providerMaintenanceCall = s.providerMaintenanceCall
	w := call(t, reopened, "POST", "/v1/tasks", map[string]any{"requestId": "new-task", "projectId": "demo", "title": "blocked"})
	if w.Code != 409 || !strings.Contains(w.Body.String(), "provider_busy") {
		t.Fatal("restart reopened admission", w.Code, w.Body)
	}
	if *writes != 1 {
		t.Fatal("replayed secret-bearing save")
	}
}
func TestProviderConfirmedReceiptSurvivesLostReleaseAndRecoversWithoutSave(t *testing.T) {
	s, writes, _ := providerFixture(t)
	releaseFails := true
	s.providerMaintenanceCall = func(_ context.Context, _ string, release bool) error {
		if release && releaseFails {
			return providerFailure()
		}
		return nil
	}
	in := providerSave(t, s, "release-recover")
	w := call(t, s, "POST", "/v1/provider-settings", in)
	if w.Code != 503 || *writes != 1 {
		t.Fatal(w.Code, w.Body, *writes)
	}
	s.Close()
	reopened, err := New(s.cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	reopened.http = s.http
	reopened.providerMaintenanceCall = s.providerMaintenanceCall
	if w = call(t, reopened, "GET", "/v1/provider-settings/requests/release-recover", nil); w.Code != 200 || !strings.Contains(w.Body.String(), "saved") {
		t.Fatal("lost confirmed receipt", w.Code, w.Body)
	}
	releaseFails = false
	w = call(t, reopened, "POST", "/v1/provider-settings/requests/release-recover/sync", nil)
	if w.Code != 200 || *writes != 1 {
		t.Fatal("recovery resaved key", w.Code, w.Body, *writes)
	}
	if _, err = os.Stat(reopened.providerFencePath()); !os.IsNotExist(err) {
		t.Fatal("confirmed recovery retained fence")
	}
}
func TestProviderLostAcquisitionCleanupStaysClosed(t *testing.T) {
	s, writes, _ := providerFixture(t)
	s.providerMaintenanceCall = func(context.Context, string, bool) error { return providerFailure() }
	w := call(t, s, "POST", "/v1/provider-settings", providerSave(t, s, "lost-acquire"))
	if w.Code != 503 || *writes != 0 {
		t.Fatal("uncertain admission reached save", w.Code, w.Body, *writes)
	}
	if _, err := os.Stat(s.providerFencePath()); err != nil {
		t.Fatal("lost acquisition reopened host")
	}
}
