// Package pi adapts the native Pi JSONL RPC transport. It does not own model
// messages, context, compaction, or the agent loop.
package pi

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
)

type Config struct {
	LifecycleRevision                                                                                    int
	Restricted                                                                                           bool
	Binary, Directory, SessionDirectory, SessionID, SessionFile, Extension, HostURL, Token, TaskID, Role string
	OnEvent                                                                                              func(json.RawMessage)
	ExcludeEnv                                                                                           []string
}
type Client struct {
	mu          sync.Mutex
	writeMu     sync.Mutex
	cmd         *exec.Cmd
	stdin       io.WriteCloser
	pending     map[string]chan response
	ui          map[string]bool
	done        chan struct{}
	err         error
	intentional bool
	onEvent     func(json.RawMessage)
}
type response struct {
	Method  string          `json:"method"`
	Type    string          `json:"type"`
	ID      string          `json:"id"`
	Success bool            `json:"success"`
	Error   string          `json:"error"`
	Data    json.RawMessage `json:"data"`
}

func Start(cfg Config) (*Client, error) {
	if cfg.Restricted && (cfg.Directory == "" || cfg.Extension == "") {
		return nil, errors.New("restricted Pi requires a managed directory and explicit trusted extension")
	}
	if cfg.Binary == "" {
		return nil, errors.New("Pi binary is not configured")
	}
	if err := os.MkdirAll(cfg.SessionDirectory, 0700); err != nil {
		return nil, err
	}
	args := []string{"--mode", "rpc", "--session-dir", cfg.SessionDirectory, "--append-system-prompt", "You are participating in one AWF task. Call awf_task to read the task goal, acceptance criteria, current plan and role before planning or reviewing. Architecture uses awf_plan for a structured plan proposal. Only an explicit user Confirm Plan and Start Execution action authorizes remote execution; ordinary conversation does not. Preserve user work. All Git operations belong to agents. The default task uses one Pi for planning and execution results. A separate reviewer exists only when explicitly enabled. Never fabricate artifacts or test evidence."}
	if cfg.SessionFile != "" {
		args = append(args, "--session", cfg.SessionFile)
	} else {
		args = append(args, "--session-id", cfg.SessionID)
	}
	if cfg.Extension != "" {
		args = append(args, "--extension", cfg.Extension)
	}
	if cfg.Restricted {
		tools := "awf_task,awf_plan,awf_execution,awf_finish"
		if cfg.Role == "reviewer" {
			tools = "awf_task,awf_review"
		}
		args = append(args, "--system-prompt", "You are Pi, the planning and result-reporting assistant for one AWF task. Use the available AWF tools and the current task conversation to help the user clarify scope, propose a concrete plan, and assess actual execution evidence. State uncertainty honestly and do not invent repository knowledge or authorization.", "--no-extensions", "--no-skills", "--no-prompt-templates", "--no-context-files", "--no-approve", "--tools", tools,
			"--append-system-prompt", "This task uses restricted model-only planning. The managed planning directory is not a repository workspace. Repository selection is metadata, not tool access or permission to execute. You cannot inspect repository or arbitrary filesystem contents in this session; use only the task context and evidence returned by explicitly authorized execution. Missing goal or acceptance criteria remain unset until clarified in the proposed plan.")
	}
	cmd := exec.Command(cfg.Binary, args...)
	cmd.Dir = cfg.Directory
	env := []string{}
	for _, value := range os.Environ() {
		key := strings.SplitN(value, "=", 2)[0]
		exclude := strings.HasPrefix(key, "AWF_")
		for _, name := range cfg.ExcludeEnv {
			if key == name {
				exclude = true
			}
		}
		if !exclude {
			env = append(env, value)
		}
	}
	cmd.Env = append(env, "AWF_HOST_URL="+cfg.HostURL, "AWF_EXTENSION_TOKEN="+cfg.Token, "AWF_TASK_ID="+cfg.TaskID, "AWF_ROLE="+cfg.Role, "AWF_LIFECYCLE_REVISION="+strconv.Itoa(cfg.LifecycleRevision))
	in, err := cmd.StdinPipe()
	if err != nil {
		return nil, err
	}
	out, err := cmd.StdoutPipe()
	if err != nil {
		return nil, err
	}
	cmd.Stderr = io.Discard
	c := &Client{cmd: cmd, stdin: in, pending: map[string]chan response{}, ui: map[string]bool{}, done: make(chan struct{}), onEvent: cfg.OnEvent}
	if err = cmd.Start(); err != nil {
		return nil, err
	}
	go c.read(out)
	return c, nil
}
func (c *Client) read(out io.Reader) {
	scanner := bufio.NewScanner(out)
	scanner.Buffer(make([]byte, 65536), 16*1024*1024)
	for scanner.Scan() {
		raw := append(json.RawMessage(nil), scanner.Bytes()...)
		var r response
		if json.Unmarshal(raw, &r) != nil {
			continue
		}
		if r.Type == "response" {
			c.mu.Lock()
			ch := c.pending[r.ID]
			delete(c.pending, r.ID)
			c.mu.Unlock()
			if ch != nil {
				ch <- r
			}
			continue
		}
		if r.Type == "extension_ui_request" && (r.Method == "confirm" || r.Method == "select" || r.Method == "input" || r.Method == "editor") {
			c.mu.Lock()
			c.ui[r.ID] = true
			c.mu.Unlock()
		}
		if c.onEvent != nil {
			c.onEvent(raw)
		}
	}
	err := scanner.Err()
	waitErr := c.cmd.Wait()
	if err == nil {
		err = waitErr
	}
	if err == nil {
		err = io.EOF
	}
	c.mu.Lock()
	c.err = err
	c.mu.Unlock()
	if c.onEvent != nil {
		c.mu.Lock()
		intentional := c.intentional
		c.mu.Unlock()
		typ := "awf_process_exit"
		if intentional {
			typ = "awf_process_closed"
		}
		raw, _ := json.Marshal(map[string]string{"type": typ})
		c.onEvent(raw)
	}
	// Exit is complete only after callbacks can no longer mutate Host state.
	close(c.done)
}
func (c *Client) send(v any) error {
	b, err := json.Marshal(v)
	if err != nil {
		return err
	}
	c.writeMu.Lock()
	defer c.writeMu.Unlock()
	_, err = c.stdin.Write(append(b, '\n'))
	return err
}

// PendingCall separates the ordered JSONL write from waiting for its reply.
// Host dispatch fencing must not hold a lock while compact waits for a model.
type PendingCall struct {
	client   *Client
	id       string
	typ      string
	response chan response
}

func (c *Client) BeginCall(typ string, fields map[string]any) (*PendingCall, error) {
	input := map[string]any{}
	for key, value := range fields {
		input[key] = value
	}
	id := core.ID()
	input["type"] = typ
	input["id"] = id
	pending := &PendingCall{client: c, id: id, typ: typ, response: make(chan response, 1)}
	c.mu.Lock()
	c.pending[id] = pending.response
	c.mu.Unlock()
	if err := c.send(input); err != nil {
		c.mu.Lock()
		delete(c.pending, id)
		c.mu.Unlock()
		return nil, err
	}
	return pending, nil
}
func (p *PendingCall) Wait(ctx context.Context) (json.RawMessage, error) {
	c := p.client
	defer func() { c.mu.Lock(); delete(c.pending, p.id); c.mu.Unlock() }()
	select {
	case r := <-p.response:
		if !r.Success {
			return nil, fmt.Errorf("Pi %s: %s", p.typ, r.Error)
		}
		return r.Data, nil
	case <-ctx.Done():
		return nil, ctx.Err()
	case <-c.done:
		c.mu.Lock()
		err := c.err
		c.mu.Unlock()
		return nil, fmt.Errorf("Pi exited: %w", err)
	}
}
func (c *Client) Call(ctx context.Context, typ string, fields map[string]any) (json.RawMessage, error) {
	pending, err := c.BeginCall(typ, fields)
	if err != nil {
		return nil, err
	}
	return pending.Wait(ctx)
}
func (c *Client) Respond(id string, v map[string]any) error {
	c.mu.Lock()
	if !c.ui[id] {
		c.mu.Unlock()
		return errors.New("unknown or already answered Pi UI request")
	}
	delete(c.ui, id)
	c.mu.Unlock()
	v["type"] = "extension_ui_response"
	v["id"] = id
	return c.send(v)
}
func (c *Client) Stop(ctx context.Context) error {
	data, err := c.Call(ctx, "clear_queue", nil)
	if err != nil {
		return err
	}
	if c.onEvent != nil {
		var event map[string]any
		if json.Unmarshal(data, &event) != nil {
			event = map[string]any{}
		}
		event["type"] = "awf_queue_cleared"
		raw, _ := json.Marshal(event)
		c.onEvent(raw)
	}
	_, err = c.Call(ctx, "abort", nil)
	return err
}
func (c *Client) Alive() bool {
	select {
	case <-c.done:
		return false
	default:
		return true
	}
}
func (c *Client) Close() error {
	c.mu.Lock()
	c.intentional = true
	c.mu.Unlock()
	_ = c.stdin.Close()
	select {
	case <-c.done:
		return nil
	case <-time.After(time.Second):
		if err := c.cmd.Process.Kill(); err != nil && !errors.Is(err, os.ErrProcessDone) {
			return err
		}
		select {
		case <-c.done:
			return nil
		case <-time.After(5 * time.Second):
			return errors.New("Pi exit and final callback were not confirmed")
		}
	}
}

func (c *Client) ForgetUI(id string) { c.mu.Lock(); delete(c.ui, id); c.mu.Unlock() }
