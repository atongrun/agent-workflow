package node

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestSourceAddressGuard(t *testing.T) {
	for _, tt := range []struct {
		name    string
		allowed []string
		remote  string
		want    int
	}{
		{"default IPv4 loopback", nil, "127.0.0.1:1234", 200},
		{"default IPv6 loopback", nil, "[::1]:1234", 200},
		{"default mapped loopback", nil, "[::ffff:127.0.0.1]:1234", 200},
		{"empty list loopback", []string{}, "127.0.0.1:1234", 200},
		{"default remote denied", nil, "192.0.2.10:1234", 403},
		{"exact IPv4", []string{"192.0.2.10"}, "192.0.2.10:1234", 200},
		{"mapped peer", []string{"192.0.2.10"}, "[::ffff:192.0.2.10]:1234", 200},
		{"mapped configuration", []string{"::ffff:192.0.2.10"}, "192.0.2.10:1234", 200},
		{"canonical IPv6", []string{"2001:db8::a"}, "[2001:db8:0:0:0:0:0:a]:1234", 200},
		{"multiple addresses", []string{"192.0.2.10", "2001:db8::a"}, "[2001:db8::a]:1234", 200},
		{"different IPv4", []string{"192.0.2.10"}, "192.0.2.11:1234", 403},
		{"different IPv6", []string{"2001:db8::a"}, "[2001:db8::b]:1234", 403},
		{"no implicit loopback", []string{"192.0.2.10"}, "127.0.0.1:1234", 403},
		{"missing peer", nil, "", 403},
		{"bare IP", nil, "127.0.0.1", 403},
		{"missing port", nil, "127.0.0.1:", 403},
		{"nonnumeric port", nil, "127.0.0.1:http", 403},
		{"out of range port", nil, "127.0.0.1:65536", 403},
		{"negative port", nil, "127.0.0.1:-1", 403},
		{"hostname", nil, "localhost:1234", 403},
		{"missing brackets", nil, "::1:1234", 403},
		{"zone", nil, "[::1%lo]:1234", 403},
		{"CIDR", nil, "127.0.0.1/32:1234", 403},
		{"whitespace", nil, " 127.0.0.1:1234", 403},
		{"ambiguous IPv4", nil, "127.000.000.001:1234", 403},
	} {
		t.Run(tt.name, func(t *testing.T) {
			f := newNative(t, t.TempDir())
			cfg := configFor(t, f)
			cfg.AllowedSourceIPs = tt.allowed
			s := startNode(t, cfg)
			r := httptest.NewRequest("GET", "/v1/health", nil)
			r.RemoteAddr = tt.remote
			r.Header.Set("Authorization", "Bearer "+cfg.Token)
			w := httptest.NewRecorder()
			s.ServeHTTP(w, r)
			if w.Code != tt.want {
				t.Fatalf("status = %d, want %d: %s", w.Code, tt.want, w.Body.String())
			}
			if tt.want == 403 && !strings.Contains(w.Body.String(), `"code":"source_denied"`) {
				t.Fatalf("missing source denial: %s", w.Body.String())
			}
			if w.Header().Get("Cache-Control") != "no-store" || strings.Contains(w.Body.String(), cfg.Token) {
				t.Fatal("missing no-store or credential disclosure")
			}
		})
	}
}

func TestSourceGuardIgnoresForwardingHeaders(t *testing.T) {
	f := newNative(t, t.TempDir())
	cfg := configFor(t, f)
	cfg.AllowedSourceIPs = []string{"192.0.2.10"}
	s := startNode(t, cfg)
	for _, tt := range []struct {
		name, remote, forwarded string
		want                    int
	}{
		{"cannot authorize denied peer", "192.0.2.11:1234", "192.0.2.10", 403},
		{"cannot supply missing peer", "", "192.0.2.10", 403},
		{"cannot override allowed peer", "192.0.2.10:1234", "192.0.2.11", 200},
	} {
		t.Run(tt.name, func(t *testing.T) {
			r := httptest.NewRequest("GET", "/v1/health", nil)
			r.RemoteAddr = tt.remote
			r.Header.Set("Authorization", "Bearer "+cfg.Token)
			r.Header.Set("X-Forwarded-For", tt.forwarded)
			r.Header.Set("X-Real-IP", tt.forwarded)
			r.Header.Set("Forwarded", "for="+tt.forwarded)
			w := httptest.NewRecorder()
			s.ServeHTTP(w, r)
			if w.Code != tt.want {
				t.Fatalf("status = %d, want %d", w.Code, tt.want)
			}
		})
	}
}

func TestSourceAndTokenRequiredForEveryRoute(t *testing.T) {
	f := newNative(t, t.TempDir())
	cfg := configFor(t, f)
	cfg.AllowedSourceIPs = []string{"192.0.2.10"}
	s := startNode(t, cfg)
	for _, route := range []struct {
		method, path string
		allowedCode  int
	}{
		{"GET", "/v1/health", 200},
		{"GET", "/v1/projects", 200},
		{"POST", "/v1/jobs", 400},
		{"GET", "/v1/jobs/absent", 404},
		{"POST", "/v1/jobs/absent/cancel", 400},
		{"GET", "/unknown", 404},
	} {
		for _, remote := range []string{"192.0.2.10:1234", "192.0.2.11:1234"} {
			for _, auth := range []struct{ name, value string }{
				{"missing token", ""}, {"wrong token", "Bearer incorrect"}, {"valid token", "Bearer " + cfg.Token},
			} {
				t.Run(route.method+route.path+"/"+remote+"/"+auth.name, func(t *testing.T) {
					r := httptest.NewRequest(route.method, route.path, strings.NewReader(`{}`))
					r.RemoteAddr = remote
					r.Header.Set("Authorization", auth.value)
					w := httptest.NewRecorder()
					s.ServeHTTP(w, r)
					want := route.allowedCode
					if remote != "192.0.2.10:1234" {
						want = 403
					} else if auth.value != "Bearer "+cfg.Token {
						want = 401
					}
					if w.Code != want {
						t.Fatalf("status = %d, want %d: %s", w.Code, want, w.Body.String())
					}
					if strings.Contains(w.Body.String(), cfg.Token) {
						t.Fatal("credential disclosure")
					}
				})
			}
		}
	}
	if creates, prompts, aborts := f.counts(); creates != 0 || prompts != 0 || aborts != 0 {
		t.Fatal("invalid or denied requests reached native execution")
	}
}

func TestSourceConfigurationValidation(t *testing.T) {
	for _, tt := range []struct {
		name, listen string
		allowed      []string
		valid        bool
	}{
		{"default", "", nil, true},
		{"IPv4 loopback", "127.0.0.1:8788", nil, true},
		{"IPv6 loopback", "[::1]:8788", nil, true},
		{"mapped loopback", "[::ffff:127.0.0.1]:8788", nil, true},
		{"restricted remote", "192.0.2.20:8788", []string{"192.0.2.10"}, true},
		{"restricted wildcard", "0.0.0.0:8788", []string{"192.0.2.10"}, true},
		{"restricted IPv6", "[2001:db8::b]:8788", []string{"2001:db8::a"}, true},
		{"duplicate normalized IPs", "", []string{"192.0.2.10", "::ffff:192.0.2.10"}, true},
		{"unrestricted remote", "192.0.2.20:8788", nil, false},
		{"unrestricted wildcard", "0.0.0.0:8788", nil, false},
		{"unrestricted IPv6 wildcard", "[::]:8788", nil, false},
		{"unrestricted empty list", "192.0.2.20:8788", []string{}, false},
		{"hostname listener", "localhost:8788", []string{"127.0.0.1"}, false},
		{"missing listener IP", ":8788", []string{"127.0.0.1"}, false},
		{"missing listener port", "127.0.0.1", nil, false},
		{"nonnumeric listener port", "127.0.0.1:http", nil, false},
		{"out of range listener port", "127.0.0.1:65536", nil, false},
		{"listener zone", "[::1%lo]:8788", nil, false},
		{"empty entry", "", []string{""}, false},
		{"hostname entry", "", []string{"host.example"}, false},
		{"CIDR entry", "", []string{"192.0.2.0/24"}, false},
		{"entry with port", "", []string{"192.0.2.10:8788"}, false},
		{"bracketed entry", "", []string{"[2001:db8::a]"}, false},
		{"entry with zone", "", []string{"fe80::1%eth0"}, false},
		{"entry whitespace", "", []string{" 192.0.2.10"}, false},
		{"malformed entry", "", []string{"192.0.2.999"}, false},
		{"IPv4 wildcard entry", "", []string{"0.0.0.0"}, false},
		{"IPv6 wildcard entry", "", []string{"::"}, false},
		{"mapped wildcard entry", "", []string{"::ffff:0.0.0.0"}, false},
		{"multicast entry", "", []string{"224.0.0.1"}, false},
		{"IPv6 multicast entry", "", []string{"ff02::1"}, false},
		{"broadcast entry", "", []string{"255.255.255.255"}, false},
		{"mixed valid and invalid entries", "", []string{"192.0.2.10", "invalid"}, false},
	} {
		t.Run(tt.name, func(t *testing.T) {
			f := newNative(t, t.TempDir())
			cfg := configFor(t, f)
			cfg.ListenAddress, cfg.AllowedSourceIPs = tt.listen, tt.allowed
			h, err := New(cfg)
			if h != nil {
				defer h.(*Server).Close()
			}
			if (err == nil) != tt.valid {
				t.Fatalf("valid = %v, error = %v", tt.valid, err)
			}
			if err != nil && strings.Contains(err.Error(), cfg.Token) {
				t.Fatal("credential disclosure")
			}
		})
	}
}

func TestSourceConfigurationSnapshot(t *testing.T) {
	f := newNative(t, t.TempDir())
	cfg := configFor(t, f)
	cfg.AllowedSourceIPs = []string{"192.0.2.10"}
	s := startNode(t, cfg)
	cfg.AllowedSourceIPs[0] = "192.0.2.11"
	if !s.sourceAllowed("192.0.2.10:1234") || s.sourceAllowed("192.0.2.11:1234") {
		t.Fatal("caller mutation changed the server's source policy")
	}
}

func TestDefaultSourcePolicyOverLoopbackHTTP(t *testing.T) {
	f := newNative(t, t.TempDir())
	cfg := configFor(t, f)
	s := startNode(t, cfg)
	server := httptest.NewServer(s)
	defer server.Close()
	r, err := http.NewRequest("GET", server.URL+"/v1/health", nil)
	if err != nil {
		t.Fatal(err)
	}
	r.Header.Set("Authorization", "Bearer "+cfg.Token)
	resp, err := server.Client().Do(r)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("default loopback request: %d", resp.StatusCode)
	}
}
