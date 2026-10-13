package host

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net"
	"net/http"
)

// The existing root content process owns native administration and its own
// model files. Host remains awf; the Unix listener has root-owned ancestry.
func (s *Server) contentAdmin(ctx context.Context, method, path string, input, output any) error {
	if s.providerAdminCall != nil {
		return s.providerAdminCall(ctx, method, path, input, output)
	}
	if validateProviderSocket(s.cfg.ContentAdminSocket) != nil {
		return providerFailure()
	}
	var body io.Reader
	if input != nil {
		b, e := json.Marshal(input)
		if e != nil {
			return providerFailure()
		}
		body = bytes.NewReader(b)
	}
	transport := &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		connection, err := (&net.Dialer{}).DialContext(ctx, "unix", s.cfg.ContentAdminSocket)
		if err != nil {
			return nil, err
		}
		if err = validateProviderPeer(connection); err != nil {
			connection.Close()
			return nil, err
		}
		return connection, nil
	}}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport}
	req, e := http.NewRequestWithContext(ctx, method, "http://unix"+path, body)
	if e != nil {
		return providerFailure()
	}
	req.Header.Set("Content-Type", "application/json")
	res, e := client.Do(req)
	if e != nil {
		return providerFailure()
	}
	defer res.Body.Close()
	b, e := io.ReadAll(io.LimitReader(res.Body, 2*1024*1024+1))
	if e != nil || len(b) > 2*1024*1024 || res.StatusCode != 200 {
		return providerFailure()
	}
	var envelope map[string]json.RawMessage
	if json.Unmarshal(b, &envelope) != nil || envelope["error"] != nil {
		return providerFailure()
	}
	if output != nil && json.Unmarshal(b, output) != nil {
		return providerFailure()
	}
	return nil
}
