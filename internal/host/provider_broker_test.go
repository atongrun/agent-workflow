package host

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"testing"
)

func TestProviderBrokerRetainsHostIdentityAndAvoidsRootFileReads(t *testing.T) {
	s, writes, _ := providerFixture(t)
	providerPath := filepath.Join(s.cfg.MagpieConfigDir, "providers.json")
	s.cfg.ContentAdminSocket = "/run/awf-provider-admin/provider.sock"
	s.cfg.MagpieWebKeyFile = "/root/inaccessible-key"
	s.cfg.MagpieConfigDir = "/root/inaccessible-magpie"
	rootDir := s.cfg.ContentPiAgentDir
	os.RemoveAll(rootDir)
	paths := []string{}
	s.providerAdminCall = func(ctx context.Context, method, path string, input, output any) error {
		paths = append(paths, path)
		if path == "/sync" {
			v := input.(map[string]any)
			if v["requestId"] != "broker" || v["preset"] != "zhipu" {
				t.Fatal("sync escaped existing receipt", v)
			}
			b := []byte(`{"synced":true}`)
			return json.Unmarshal(b, output)
		}
		nativePath := "/api/providers"
		if path != "/providers" {
			nativePath = "/api/provider" + path
		}
		value := input
		if path == "/save" {
			v := input.(map[string]any)
			if v["requestId"] != "broker" {
				t.Fatal("save missing fence identity")
			}
			copy := map[string]any{}
			for k, x := range v {
				if k != "requestId" {
					copy[k] = x
				}
			}
			value = copy
		}
		b, _ := json.Marshal(value)
		req, _ := http.NewRequestWithContext(ctx, method, "http://127.0.0.1:3430"+nativePath, bytes.NewReader(b))
		req.AddCookie(&http.Cookie{Name: "magpie_web_3430", Value: "private-cookie"})
		res, e := s.http.Do(req)
		if e != nil {
			return e
		}
		defer res.Body.Close()
		b, _ = io.ReadAll(res.Body)
		if path == "/providers" {
			var raw map[string]any
			json.Unmarshal(b, &raw)
			info, _ := os.Stat(providerPath)
			raw["sourceRevision"] = fmt.Sprintf("%d/%d", info.ModTime().UnixNano(), info.Size())
			b, _ = json.Marshal(raw)
		}
		if output != nil {
			return json.Unmarshal(b, output)
		}
		return nil
	}
	in := providerSave(t, s, "broker")
	before := in["expectedRevision"]
	response := call(t, s, "POST", "/v1/provider-settings", in)
	if response.Code != 200 {
		t.Fatal(response.Code, response.Body.String())
	}
	var receipt providerReceipt
	json.Unmarshal(response.Body.Bytes(), &receipt)
	if receipt.Sync["x-studio"] != "synced" || receipt.Sync["awf"] != "synced" || receipt.Sync["x-studio-durable"] != "synced" {
		t.Fatal(receipt)
	}
	if _, e := os.Stat(rootDir); !os.IsNotExist(e) {
		t.Fatal("Host wrote inaccessible root profile")
	}
	snapshot, _, e := s.providerSnapshot(context.Background())
	if e != nil || snapshot.Revision == before {
		t.Fatal("root-provided key-only revision missing", e)
	}
	if call(t, s, "POST", "/v1/provider-settings", in).Code != 200 || *writes != 1 {
		t.Fatal("save replayed")
	}
	foundSync := false
	for _, p := range paths {
		if p == "/sync" {
			foundSync = true
		}
	}
	if !foundSync {
		t.Fatal("root sync not delegated")
	}
}
