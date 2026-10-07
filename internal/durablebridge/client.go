package durablebridge

import (
	"bytes"
	"context"
	"errors"
	"io"
	"net"
	"net/http"
	"path/filepath"
	"time"
)

// Client sends bounded JSON over one operator-selected Unix socket. It never
// copies browser headers or follows redirects and never retries mutations.
type Client struct {
	http      *http.Client
	transport *http.Transport
	available func() bool
}

var ErrFrameTooLarge = errors.New("Durable request envelope exceeds transport limit")

func NewUnixClient(socket string, timeout time.Duration) (*Client, error) {
	if !filepath.IsAbs(socket) || len(socket) > 107 || timeout <= 0 || timeout > 120*time.Second {
		return nil, ErrInvalid
	}
	transport := &http.Transport{
		// A new connection for every request also removes Transport's stale
		// reused-connection retry path. There are no idempotency-key headers.
		DisableKeepAlives: true, MaxResponseHeaderBytes: 16384,
		ResponseHeaderTimeout: timeout,
		DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
			if err := validateSocket(socket); err != nil {
				return nil, err
			}
			return (&net.Dialer{}).DialContext(ctx, "unix", socket)
		},
	}
	return &Client{transport: transport, http: &http.Client{Transport: transport, Timeout: timeout, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}}, nil
}

func (c *Client) Close() { c.transport.CloseIdleConnections() }

func (c *Client) call(ctx context.Context, method, path string, body any) ([]byte, int, error) {
	if c.available != nil && !c.available() {
		return nil, 0, ErrUnavailable
	}
	return c.exchange(ctx, method, path, body)
}

func (c *Client) exchange(ctx context.Context, method, path string, body any) ([]byte, int, error) {
	var input []byte
	var err error
	if body != nil {
		input, err = marshalFrame(body)
		if err != nil {
			return nil, 0, ErrInvalid
		}
		if len(input) > MaxWorkerRequestBytes {
			return nil, 0, ErrFrameTooLarge
		}
	}
	req, err := http.NewRequestWithContext(ctx, method, "http://durable.local"+path, bytes.NewReader(input))
	if err != nil {
		return nil, 0, ErrInvalid
	}
	req.Header.Set("Content-Type", "application/json")
	res, err := c.http.Do(req)
	if err != nil {
		return nil, 0, ErrUnavailable
	}
	defer res.Body.Close()
	b, err := io.ReadAll(io.LimitReader(res.Body, MaxResponseBytes+1))
	if err != nil || len(b) > MaxResponseBytes {
		return nil, 0, ErrUnavailable
	}
	return b, res.StatusCode, nil
}
