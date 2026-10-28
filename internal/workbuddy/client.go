// Package workbuddy drives a loopback CodeBuddy / WorkBuddy daemon.
//
// The HTTP contract was checked against the public beta docs on 2026-10-28:
// https://www.codebuddy.ai/docs/cli/http-api
// https://www.codebuddy.ai/docs/cli/daemon
// https://www.tencentcloud.com/document/product/1316/84473
//
// Those pages specify POST /api/v1/jobs (prompt, cwd, permissionMode, bgIsolation),
// GET /api/v1/jobs/:id, GET /api/v1/jobs/:id/stream, GET /api/v1/jobs/events,
// POST /api/v1/jobs/:id/reply, and POST /api/v1/jobs/:id/stop. Every API call
// sends Authorization: Bearer and X-CodeBuddy-Request: 1. Responses use
// {"data":...} or {"error":{"code","message"}}.
//
// The reply JSON body is not published. This client sends {"text":"..."} once.
// A rejected body stays an error for the node fence; it is not rewritten and resent.
// Lifecycle state/status strings are taken from the same pages. Unknown states
// fail closed instead of being treated as completion.
package workbuddy

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

const headerName = "X-CodeBuddy-Request"

type Config struct {
	URL            string
	Password       string
	PermissionMode string
	HTTPClient     *http.Client
}

type Client struct {
	base       *url.URL
	http       *http.Client
	password   string
	permission string
}

type Job struct {
	ID       string
	Name     string
	CWD      string
	State    string
	Status   string
	Summary  string
	Error    string
	Question string
}

type HTTPError struct {
	StatusCode int
	Code       string
	Body       string
}

func (e *HTTPError) Error() string {
	if e.Code != "" {
		return fmt.Sprintf("WorkBuddy HTTP %d %s: %s", e.StatusCode, e.Code, e.Body)
	}
	return fmt.Sprintf("WorkBuddy HTTP %d: %s", e.StatusCode, e.Body)
}

func New(cfg Config) (*Client, error) {
	if cfg.URL == "" {
		return nil, errors.New("WorkBuddy URL is required")
	}
	if len(strings.TrimSpace(cfg.Password)) < 8 {
		return nil, errors.New("WorkBuddy password must contain at least 8 characters")
	}
	mode := cfg.PermissionMode
	if mode == "" {
		mode = "acceptEdits"
	}
	switch mode {
	case "default", "acceptEdits", "plan":
	default:
		return nil, errors.New("WorkBuddy permissionMode must be default, acceptEdits, or plan")
	}
	u, err := url.Parse(cfg.URL)
	if err != nil {
		return nil, fmt.Errorf("WorkBuddy URL: %w", err)
	}
	host := u.Hostname()
	ip := net.ParseIP(host)
	if (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || (u.Path != "" && u.Path != "/") || (host != "localhost" && (ip == nil || !ip.IsLoopback())) {
		return nil, errors.New("WorkBuddy URL must be an HTTP(S) loopback origin without credentials, path, query, or fragment")
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
	hc.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	if hc.Timeout == 0 {
		hc.Timeout = 15 * time.Second
	}
	return &Client{base: u, http: &hc, password: cfg.Password, permission: mode}, nil
}

func (c *Client) Health(ctx context.Context) (bool, string, error) {
	var data map[string]any
	if err := c.call(ctx, "GET", "/api/v1/health", nil, nil, &data); err != nil {
		return false, "", err
	}
	version, _ := data["version"].(string)
	if version == "" {
		version = "unspecified"
	}
	status, _ := data["status"].(string)
	if status != "" && status != "ok" {
		return false, version, nil
	}
	if healthy, ok := data["healthy"].(bool); ok && !healthy {
		return false, version, nil
	}
	return true, version, nil
}

type Dispatch struct {
	Prompt string
	CWD    string
	Name   string
}

func (c *Client) Dispatch(ctx context.Context, in Dispatch) (Job, error) {
	if strings.TrimSpace(in.Prompt) == "" || strings.TrimSpace(in.CWD) == "" || strings.TrimSpace(in.Name) == "" {
		return Job{}, errors.New("WorkBuddy dispatch requires prompt, cwd, and name")
	}
	body := map[string]string{
		"prompt":         in.Prompt,
		"cwd":            in.CWD,
		"permissionMode": c.permission,
		"bgIsolation":    "worktree",
		"name":           in.Name,
	}
	var data map[string]any
	if err := c.call(ctx, "POST", "/api/v1/jobs", nil, body, &data); err != nil {
		return Job{}, err
	}
	job, err := jobFromMap(data)
	if err != nil {
		return Job{}, err
	}
	return job, nil
}

func (c *Client) Get(ctx context.Context, id string) (Job, error) {
	if !safeID(id) {
		return Job{}, errors.New("invalid WorkBuddy job id")
	}
	var data map[string]any
	if err := c.call(ctx, "GET", "/api/v1/jobs/"+url.PathEscape(id), nil, nil, &data); err != nil {
		return Job{}, err
	}
	return jobFromMap(data)
}

func (c *Client) List(ctx context.Context, cwd string) ([]Job, error) {
	q := url.Values{}
	if cwd != "" {
		q.Set("cwd", cwd)
	}
	var raw json.RawMessage
	if err := c.call(ctx, "GET", "/api/v1/jobs", q, nil, &raw); err != nil {
		return nil, err
	}
	return jobsFromList(raw)
}

func (c *Client) Reply(ctx context.Context, id, text string) error {
	if !safeID(id) {
		return errors.New("invalid WorkBuddy job id")
	}
	if strings.TrimSpace(text) == "" {
		return errors.New("WorkBuddy reply text is required")
	}
	return c.call(ctx, "POST", "/api/v1/jobs/"+url.PathEscape(id)+"/reply", nil, map[string]string{"text": text}, nil)
}

func (c *Client) Stop(ctx context.Context, id string) error {
	if !safeID(id) {
		return errors.New("invalid WorkBuddy job id")
	}
	return c.call(ctx, "POST", "/api/v1/jobs/"+url.PathEscape(id)+"/stop", nil, map[string]any{}, nil)
}

func (c *Client) call(ctx context.Context, method, path string, query url.Values, body any, out any) error {
	u := *c.base
	u.Path = path
	u.RawQuery = query.Encode()
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
	req.Header.Set(headerName, "1")
	req.Header.Set("Authorization", "Bearer "+c.password)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	res, err := c.http.Do(req)
	if err != nil {
		return fmt.Errorf("WorkBuddy request: %w", err)
	}
	defer res.Body.Close()
	data, err := io.ReadAll(io.LimitReader(res.Body, 8<<20+1))
	if err != nil {
		return fmt.Errorf("WorkBuddy response: %w", err)
	}
	if len(data) > 8<<20 {
		return errors.New("WorkBuddy response exceeds 8 MiB")
	}
	if res.StatusCode < 200 || res.StatusCode >= 300 {
		msg := strings.TrimSpace(string(data))
		if len(msg) > 2048 {
			msg = msg[:2048]
		}
		code := ""
		var envelope struct {
			Error struct {
				Code    string `json:"code"`
				Message string `json:"message"`
			} `json:"error"`
		}
		if json.Unmarshal(data, &envelope) == nil && envelope.Error.Message != "" {
			msg = envelope.Error.Message
			code = envelope.Error.Code
		}
		return &HTTPError{StatusCode: res.StatusCode, Code: code, Body: msg}
	}
	if out == nil {
		return nil
	}
	var envelope struct {
		Data json.RawMessage `json:"data"`
	}
	if err := json.Unmarshal(data, &envelope); err != nil {
		return fmt.Errorf("decode WorkBuddy response: %w", err)
	}
	if len(envelope.Data) == 0 {
		return errors.New("WorkBuddy response is missing data")
	}
	if err := json.Unmarshal(envelope.Data, out); err != nil {
		return fmt.Errorf("decode WorkBuddy data: %w", err)
	}
	return nil
}

func safeID(id string) bool {
	if id == "" || len(id) > 200 || id == "." || id == ".." {
		return false
	}
	for _, c := range id {
		if !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '_' || c == '-') {
			return false
		}
	}
	return true
}

func jobFromMap(raw map[string]any) (Job, error) {
	if raw == nil {
		return Job{}, errors.New("WorkBuddy job object is empty")
	}
	job := Job{
		ID:       stringField(raw, "id"),
		Name:     stringField(raw, "name"),
		CWD:      firstString(raw, "cwd", "directory", "workspace"),
		State:    stringField(raw, "state"),
		Status:   stringField(raw, "status"),
		Summary:  firstString(raw, "summary", "result", "output", "text"),
		Error:    firstString(raw, "error", "errorMessage"),
		Question: firstString(raw, "question", "pendingInput", "input", "waitReason", "blockedReason"),
	}
	if job.ID == "" {
		return Job{}, errors.New("WorkBuddy job is missing id")
	}
	if !safeID(job.ID) {
		return Job{}, errors.New("WorkBuddy job id is not a safe token")
	}
	return job, nil
}

func jobsFromList(raw json.RawMessage) ([]Job, error) {
	if len(raw) == 0 || string(raw) == "null" {
		return nil, errors.New("WorkBuddy job list is missing")
	}
	var list []map[string]any
	if json.Unmarshal(raw, &list) == nil {
		return mapsToJobs(list)
	}
	var wrapped map[string]json.RawMessage
	if json.Unmarshal(raw, &wrapped) != nil {
		return nil, errors.New("WorkBuddy job list has an unknown shape")
	}
	for _, key := range []string{"jobs", "items"} {
		if wrapped[key] != nil && json.Unmarshal(wrapped[key], &list) == nil {
			return mapsToJobs(list)
		}
	}
	return nil, errors.New("WorkBuddy job list has an unknown shape")
}

func mapsToJobs(list []map[string]any) ([]Job, error) {
	out := make([]Job, 0, len(list))
	for _, item := range list {
		job, err := jobFromMap(item)
		if err != nil {
			return nil, err
		}
		out = append(out, job)
	}
	return out, nil
}

func stringField(raw map[string]any, key string) string {
	v, _ := raw[key].(string)
	return v
}

func firstString(raw map[string]any, keys ...string) string {
	for _, key := range keys {
		if v, ok := raw[key].(string); ok && strings.TrimSpace(v) != "" {
			return v
		}
		if key == "error" {
			if obj, ok := raw[key].(map[string]any); ok {
				if msg, _ := obj["message"].(string); msg != "" {
					return msg
				}
			}
		}
	}
	return ""
}
