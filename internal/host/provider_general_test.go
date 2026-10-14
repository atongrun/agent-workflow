package host

import (
	"encoding/json"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestGeneralProviderOfficialPresetsUseNativeNewWithoutEndpoints(t *testing.T) {
	for _, preset := range providerPresets {
		t.Run(preset.ID, func(t *testing.T) {
			s, writes, _ := providerFixture(t)
			original := s.http.Transport
			s.http.Transport = providerTransport(func(r *http.Request) (*http.Response, error) {
				if r.URL.Path == "/api/provider/save" {
					var body map[string]any
					json.NewDecoder(r.Body).Decode(&body)
					if body["preset"] != preset.ID || body["new"] != true || body["id"] != "dash-"+preset.ID {
						t.Fatal("native addition identity mismatch")
					}
					if body["chat"] != nil || body["headers"] != nil {
						t.Fatal("arbitrary transport forwarded")
					}
					b, _ := json.Marshal(body)
					r.Body = io.NopCloser(strings.NewReader(string(b)))
				}
				return original.RoundTrip(r)
			})
			in := providerSave(t, s, "official")
			in["preset"] = preset.ID
			w := call(t, s, "POST", "/v1/provider-settings", in)
			if w.Code != 200 || *writes != 1 {
				t.Fatal(w.Code, w.Body)
			}
			var snapshot providerSnapshot
			json.Unmarshal(call(t, s, "GET", "/v1/provider-settings", nil).Body.Bytes(), &snapshot)
			if len(snapshot.Presets) != 14 {
				t.Fatal("two-preset limit retained")
			}
		})
	}
}
func existingProviderFixture(t *testing.T) (*Server, *int) {
	s, writes, _ := providerFixture(t)
	original := s.http.Transport
	s.http.Transport = providerTransport(func(r *http.Request) (*http.Response, error) {
		var raw string
		switch r.URL.Path {
		case "/api/providers":
			raw = `{"providers":[{"id":"custom-native","preset":"custom","chosen":["vendor/model"],"key":{"set":true,"value":"DO-NOT-LEAK"},"chat":"https://existing.example/v1","headers":{"Authorization":"DO-NOT-LEAK"},"proxy":"https://existing-proxy.example"}]}`
		case "/v1/models":
			raw = `{"data":[{"id":"custom-native/vendor/model","context_window":1000,"max_output_tokens":500,"modalities":{"input":["text","image"],"output":["text"]}},{"id":"unrelated/no-metadata"}]}`
		default:
			return original.RoundTrip(r)
		}
		return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(raw)), Header: http.Header{"Content-Type": []string{"application/json"}}}, nil
	})
	return s, writes
}
func TestExistingProviderSyncPreservesNativeConfigAndOpaqueModels(t *testing.T) {
	s, writes := existingProviderFixture(t)
	var snapshot providerSnapshot
	w := call(t, s, "GET", "/v1/provider-settings", nil)
	if w.Code != 200 || strings.Contains(w.Body.String(), "DO-NOT-LEAK") || strings.Contains(w.Body.String(), "https:") {
		t.Fatal("native private configuration leaked")
	}
	json.Unmarshal(w.Body.Bytes(), &snapshot)
	in := map[string]any{"requestId": "existing", "preset": "existing", "providerId": "custom-native", "key": "", "models": []string{"vendor/model"}, "expectedRevision": snapshot.Revision}
	providerBefore, _ := os.ReadFile(filepath.Join(s.cfg.MagpieConfigDir, "providers.json"))
	w = call(t, s, "POST", "/v1/provider-settings", in)
	if w.Code != 200 || *writes != 0 {
		t.Fatal(w.Code, w.Body, "native config rewritten")
	}
	var receipt providerReceipt
	json.Unmarshal(w.Body.Bytes(), &receipt)
	if receipt.ProviderID != "custom-native" || receipt.Status != "saved" {
		t.Fatal("receipt lost provider identity")
	}
	for _, status := range receipt.Sync {
		if status != "synced" {
			t.Fatal(receipt)
		}
	}
	for _, dir := range []string{s.cfg.PiAgentDir, s.cfg.ContentPiAgentDir, s.cfg.ContentDurablePiAgentDir} {
		data, err := os.ReadFile(filepath.Join(dir, "models.json"))
		if err != nil {
			t.Fatal(err)
		}
		var root struct {
			Providers map[string]struct {
				Models []struct {
					ID    string   `json:"id"`
					Input []string `json:"input"`
				} `json:"models"`
			} `json:"providers"`
		}
		if json.Unmarshal(data, &root) != nil {
			t.Fatal("invalid catalog")
		}
		found := false
		for _, m := range root.Providers["magpie"].Models {
			if m.ID == "custom-native/vendor/model" {
				found = len(m.Input) == 2 && m.Input[1] == "image"
			}
		}
		if !found {
			t.Fatal("native image input not preserved")
		}
	}
	providerAfter, _ := os.ReadFile(filepath.Join(s.cfg.MagpieConfigDir, "providers.json"))
	if string(providerBefore) != string(providerAfter) {
		t.Fatal("provider bytes changed")
	}
	if call(t, s, "POST", "/v1/provider-settings", in).Code != 200 || *writes != 0 {
		t.Fatal("existing selection replayed native save")
	}
	in["requestId"] = "invalid"
	in["key"] = "DO-NOT-LEAK"
	if call(t, s, "POST", "/v1/provider-settings", in).Code != 400 {
		t.Fatal("existing key write accepted")
	}
}
func TestExistingProviderCannotSyncUnchosenModelsOrArbitraryID(t *testing.T) {
	for _, kind := range []string{"unselected", "foreign", "path"} {
		t.Run(kind, func(t *testing.T) {
			s, writes := existingProviderFixture(t)
			var snapshot providerSnapshot
			json.Unmarshal(call(t, s, "GET", "/v1/provider-settings", nil).Body.Bytes(), &snapshot)
			in := map[string]any{"requestId": "invalid", "preset": "existing", "providerId": "custom-native", "key": "", "models": []string{"vendor/model"}, "expectedRevision": snapshot.Revision}
			switch kind {
			case "unselected":
				in["models"] = []string{"vendor/unselected"}
			case "foreign":
				in["providerId"] = "not-configured"
			case "path":
				in["providerId"] = "../escape"
			}
			w := call(t, s, "POST", "/v1/provider-settings", in)
			if w.Code < 400 || *writes != 0 {
				t.Fatal("unapproved existing selection accepted")
			}
		})
	}
}

func TestNativeModalitiesMalformedFailsWithoutCatalogWrites(t *testing.T) {
	for _, shape := range []string{`["text"]`, `{"input":"image"}`, `{"input":[1]}`} {
		t.Run(shape, func(t *testing.T) {
			s, _, _ := providerFixture(t)
			originals := map[string]string{}
			for _, dir := range []string{s.cfg.PiAgentDir, s.cfg.ContentPiAgentDir, s.cfg.ContentDurablePiAgentDir} {
				p := filepath.Join(dir, "models.json")
				b, _ := os.ReadFile(p)
				originals[p] = string(b)
			}
			s.http.Transport = providerTransport(func(r *http.Request) (*http.Response, error) {
				return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(`{"data":[{"id":"qwen-cn/qwen-max","context_window":1000,"max_output_tokens":500,"modalities":` + shape + `}]}`))}, nil
			})
			result := s.syncProviderModels(t.Context(), providerReceipt{RequestID: "shape", Preset: "existing", ProviderID: "qwen-cn", Models: []string{"qwen-max"}})
			for _, v := range result {
				if v != "failed" {
					t.Fatal(result)
				}
			}
			for p, b := range originals {
				after, _ := os.ReadFile(p)
				if string(after) != b {
					t.Fatal("invalid native field wrote catalog")
				}
			}
		})
	}
}
