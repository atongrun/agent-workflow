// Package opencode is a deliberately small client for the native OpenCode server.
// It never runs a shell, installs OpenCode, or retries mutating requests.
package opencode

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"
)

const maxResponseBytes = 32 << 20

type ModelSelection struct {
	ProviderID string `json:"providerID"`
	ModelID    string `json:"modelID"`
}

func (m *ModelSelection) Validate() error {
	if m == nil {
		return nil
	}
	for _, id := range []string{m.ProviderID, m.ModelID} {
		if id == "" || len(id) > 256 || strings.TrimSpace(id) != id || strings.ContainsAny(id, "\r\n\t\x00") {
			return errors.New("model providerID and modelID must both be nonempty identifiers of at most 256 characters")
		}
	}
	return nil
}

type Config struct {
	URL        string
	Username   string
	Password   string
	HTTPClient *http.Client
}

type Client struct {
	base               *url.URL
	http               *http.Client
	username, password string
}

type Session struct {
	ID        string `json:"id"`
	Title     string `json:"title"`
	Directory string `json:"directory"`
}
type Status struct {
	Type    string  `json:"type"`
	Attempt int     `json:"attempt,omitempty"`
	Message string  `json:"message,omitempty"`
	Next    float64 `json:"next,omitempty"`
}
type Message struct {
	Info  MessageInfo `json:"info"`
	Parts []Part      `json:"parts"`
}
type MessageInfo struct {
	ID        string `json:"id"`
	SessionID string `json:"sessionID"`
	ParentID  string `json:"parentID,omitempty"`
	Role      string `json:"role"`
	Time      struct {
		Created   int64 `json:"created"`
		Completed int64 `json:"completed,omitempty"`
	} `json:"time"`
	Finish string          `json:"finish,omitempty"`
	Error  json.RawMessage `json:"error,omitempty"`
}
type Part struct {
	ID        string          `json:"id"`
	SessionID string          `json:"sessionID"`
	MessageID string          `json:"messageID"`
	Type      string          `json:"type"`
	Text      string          `json:"text,omitempty"`
	Tool      string          `json:"tool,omitempty"`
	CallID    string          `json:"callID,omitempty"`
	State     ToolState       `json:"state,omitempty"`
	Metadata  json.RawMessage `json:"metadata,omitempty"`
}
type ToolState struct {
	Status   string          `json:"status"`
	Input    json.RawMessage `json:"input,omitempty"`
	Output   string          `json:"output,omitempty"`
	Error    string          `json:"error,omitempty"`
	Title    string          `json:"title,omitempty"`
	Metadata json.RawMessage `json:"metadata,omitempty"`
	Time     json.RawMessage `json:"time,omitempty"`
}
type Health struct {
	Healthy bool   `json:"healthy"`
	Version string `json:"version"`
}

type HTTPError struct {
	StatusCode int
	Body       string
}

func (e *HTTPError) Error() string { return fmt.Sprintf("OpenCode HTTP %d: %s", e.StatusCode, e.Body) }

func New(cfg Config) (*Client, error) {
	if cfg.URL == "" {
		cfg.URL = "http://127.0.0.1:4096"
	}
	u, err := url.Parse(cfg.URL)
	if err != nil {
		return nil, fmt.Errorf("OpenCode URL: %w", err)
	}
	host := u.Hostname()
	ip := net.ParseIP(host)
	if (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || (u.Path != "" && u.Path != "/") || (host != "localhost" && (ip == nil || !ip.IsLoopback())) {
		return nil, errors.New("OpenCode URL must be an HTTP(S) loopback origin without credentials, path, query, or fragment")
	}
	u.Path = ""
	var hc http.Client
	if cfg.HTTPClient != nil {
		hc = *cfg.HTTPClient
	} else {
		tr := http.DefaultTransport.(*http.Transport).Clone()
		tr.Proxy = nil
		hc = http.Client{Transport: tr, Timeout: 15 * time.Second}
	}
	// A redirected native call must not leak authentication or replay a prompt.
	hc.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	if hc.Timeout == 0 {
		hc.Timeout = 15 * time.Second
	}
	if cfg.Username == "" {
		cfg.Username = "opencode"
	}
	return &Client{base: u, http: &hc, username: cfg.Username, password: cfg.Password}, nil
}

func (c *Client) request(ctx context.Context, method, path, directory string, body, out any) error {
	u := *c.base
	u.Path = path
	if directory != "" {
		q := url.Values{}
		q.Set("directory", directory)
		u.RawQuery = q.Encode()
	}
	var reader io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return err
		}
		reader = bytes.NewReader(b)
	}
	req, err := http.NewRequestWithContext(ctx, method, u.String(), reader)
	if err != nil {
		return err
	}
	req.Header.Set("Accept", "application/json")
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if c.password != "" {
		req.SetBasicAuth(c.username, c.password)
	}
	res, err := c.http.Do(req)
	if err != nil {
		return fmt.Errorf("OpenCode request: %w", err)
	}
	defer res.Body.Close()
	data, err := io.ReadAll(io.LimitReader(res.Body, maxResponseBytes+1))
	if err != nil {
		return fmt.Errorf("OpenCode response: %w", err)
	}
	if len(data) > maxResponseBytes {
		return errors.New("OpenCode response exceeds 32 MiB; cannot safely reconcile")
	}
	if res.StatusCode < 200 || res.StatusCode >= 300 {
		msg := string(data)
		if len(msg) > 2048 {
			msg = msg[:2048]
		}
		return &HTTPError{res.StatusCode, msg}
	}
	if out == nil {
		return nil
	}
	if err := json.Unmarshal(data, out); err != nil {
		return fmt.Errorf("decode OpenCode response: %w", err)
	}
	return nil
}

func validID(id string) error {
	if id == "" || strings.ContainsAny(id, "/\\?#\x00") || id == "." || id == ".." {
		return errors.New("invalid native session ID")
	}
	return nil
}
func (c *Client) Health(ctx context.Context) (Health, error) {
	var h Health
	err := c.request(ctx, "GET", "/global/health", "", nil, &h)
	return h, err
}
func (c *Client) CreateSession(ctx context.Context, directory, title string) (Session, error) {
	var s Session
	err := c.request(ctx, "POST", "/session", directory, map[string]string{"title": title}, &s)
	if err == nil {
		err = validID(s.ID)
	}
	return s, err
}
func (c *Client) Sessions(ctx context.Context, directory string) ([]Session, error) {
	var s []Session
	err := c.request(ctx, "GET", "/session", directory, nil, &s)
	return s, err
}
func (c *Client) Session(ctx context.Context, directory, id string) (Session, error) {
	var s Session
	if err := validID(id); err != nil {
		return s, err
	}
	err := c.request(ctx, "GET", "/session/"+id, directory, nil, &s)
	return s, err
}
func (c *Client) PromptAsync(ctx context.Context, directory, id, messageID, prompt string, selection ...*ModelSelection) error {
	if err := validID(id); err != nil {
		return err
	}
	var model *ModelSelection
	if len(selection) > 1 {
		return errors.New("at most one native model selection allowed")
	}
	if len(selection) == 1 {
		model = selection[0]
	}
	if err := model.Validate(); err != nil {
		return err
	}
	return c.request(ctx, "POST", "/session/"+id+"/prompt_async", directory, struct {
		MessageID string              `json:"messageID"`
		Parts     []map[string]string `json:"parts"`
		Model     *ModelSelection     `json:"model,omitempty"`
	}{messageID, []map[string]string{{"type": "text", "text": prompt}}, model}, nil)
}
func (c *Client) Statuses(ctx context.Context, directory string) (map[string]Status, error) {
	var s map[string]Status
	err := c.request(ctx, "GET", "/session/status", directory, nil, &s)
	return s, err
}
func (c *Client) Messages(ctx context.Context, directory, id string) ([]Message, error) {
	var m []Message
	if err := validID(id); err != nil {
		return m, err
	}
	err := c.request(ctx, "GET", "/session/"+id+"/message", directory, nil, &m)
	return m, err
}
func (c *Client) Abort(ctx context.Context, directory, id string) (bool, error) {
	if err := validID(id); err != nil {
		return false, err
	}
	var ok bool
	err := c.request(ctx, "POST", "/session/"+id+"/abort", directory, nil, &ok)
	return ok, err
}

// PendingPermissions and PendingQuestions recover waiting state after SSE gaps.
// Reading these lists never grants permission or answers on the user's behalf.
func (c *Client) PendingPermissions(ctx context.Context, directory string) ([]json.RawMessage, error) {
	var out []json.RawMessage
	err := c.request(ctx, "GET", "/permission", directory, nil, &out)
	return out, err
}
func (c *Client) PendingQuestions(ctx context.Context, directory string) ([]json.RawMessage, error) {
	var out []json.RawMessage
	err := c.request(ctx, "GET", "/question", directory, nil, &out)
	return out, err
}
