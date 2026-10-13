package host

import (
	"context"
	"fmt"
	"reflect"
	"testing"
)

func TestProviderMaintenanceUsesBoundOwnerAndReleaseOrder(t *testing.T) {
	s := testServer(t)
	s.cfg.ContentAdminSocket = "/not/a/discoverable/socket"
	s.cfg.DurableConfig = "/not/a/discoverable/config"
	var calls []string
	s.BindDurableCatalogMaintenance(func(_ context.Context, id string, release bool) error {
		calls = append(calls, fmt.Sprintf("native:%s:%t", id, release))
		return nil
	})
	s.providerAdminCall = func(_ context.Context, method, path string, input, output any) error {
		v := input.(map[string]any)
		release := v["release"].(bool)
		calls = append(calls, fmt.Sprintf("content:%s:%t", v["requestId"], release))
		output.(*struct {
			Held bool `json:"held"`
		}).Held = !release
		return nil
	}
	for _, release := range []bool{false, true} {
		if err := s.maintenanceEndpoints(context.Background(), "same_identity", release); err != nil {
			t.Fatal(err)
		}
	}
	want := []string{"native:same_identity:false", "content:same_identity:false", "content:same_identity:true", "native:same_identity:true"}
	if !reflect.DeepEqual(calls, want) {
		t.Fatal(calls)
	}
}
func TestProviderMaintenanceWithoutOwnedWorkerFailsBeforeContent(t *testing.T) {
	s := testServer(t)
	called := false
	s.providerAdminCall = func(context.Context, string, string, any, any) error { called = true; return nil }
	if s.maintenanceEndpoints(context.Background(), "same_identity", false) == nil || called {
		t.Fatal("unbound native owner accepted")
	}
}
