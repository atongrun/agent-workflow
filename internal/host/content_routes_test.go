package host

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestContentModuleSharesHostListenerAndKeepsCredentialsScoped(t *testing.T) {
	s := testServer(t)
	contentToken := "content-fixture-token-123456789"
	s.cfg.ContentHandler = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer "+contentToken {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		w.WriteHeader(http.StatusAccepted)
	})
	h := s.Handler()
	for _, c := range []struct {
		path, token string
		status      int
	}{
		{"/v1/content/jobs", contentToken, 202},
		{"/v1/content/jobs", s.token, 401},
		{"/v1/tasks", contentToken, 401},
		{"/v1/tasks", s.token, 200},
	} {
		r := httptest.NewRequest("GET", c.path, nil)
		r.Header.Set("Authorization", "Bearer "+c.token)
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		if w.Code != c.status {
			t.Fatalf("route %s: %d, want %d", c.path, w.Code, c.status)
		}
	}
}
