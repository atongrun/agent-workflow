package workbuddy

import (
	"bufio"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"time"

	"github.com/atongrun/agent-workflow/internal/executor"
	"github.com/atongrun/agent-workflow/internal/opencode"
)

// Config is the node-facing WorkBuddy executor.
type OpenConfig struct {
	URL            string
	Password       string
	PermissionMode string
	StateDir       string
	HTTPClient     *http.Client
}

// Open returns the executor plugin. StateDir holds correlation notes so a
// restarted node can reconcile a daemon job without sending the prompt again.
func Open(cfg OpenConfig) (*Driver, error) {
	client, err := New(Config{URL: cfg.URL, Password: cfg.Password, PermissionMode: cfg.PermissionMode, HTTPClient: cfg.HTTPClient})
	if err != nil {
		return nil, err
	}
	if strings.TrimSpace(cfg.StateDir) == "" {
		return nil, errors.New("WorkBuddy stateDir is required")
	}
	dir := filepath.Join(cfg.StateDir, "workbuddy")
	if err := os.MkdirAll(dir, 0700); err != nil {
		return nil, err
	}
	return &Driver{client: client, dir: dir}, nil
}

// Driver maps one AWF session onto one WorkBuddy background job.
// PromptAsync is the only dispatch. A later call, a lost response, or a restart
// reads the note and the daemon; it does not POST /jobs again.
type Driver struct {
	client *Client
	dir    string
	mu     sync.Mutex
}

func (d *Driver) Kind() string { return "workbuddy" }

func (d *Driver) Health(ctx context.Context) (opencode.Health, error) {
	ok, version, err := d.client.Health(ctx)
	if err != nil {
		return opencode.Health{}, err
	}
	return opencode.Health{Healthy: ok, Version: version}, nil
}

func (d *Driver) CreateSession(_ context.Context, directory, title string) (opencode.Session, error) {
	if strings.TrimSpace(directory) == "" || strings.TrimSpace(title) == "" {
		return opencode.Session{}, errors.New("WorkBuddy session requires a workspace and title")
	}
	return opencode.Session{ID: localID(directory, title), Title: title, Directory: directory}, nil
}

func (d *Driver) Sessions(ctx context.Context, directory string) ([]opencode.Session, error) {
	jobs, err := d.client.List(ctx, directory)
	if err != nil {
		return nil, err
	}
	out := []opencode.Session{}
	for _, job := range jobs {
		if job.Name == "" || !samePath(job.CWD, directory) {
			continue
		}
		out = append(out, opencode.Session{ID: job.Name, Title: job.Name, Directory: job.CWD})
	}
	return out, nil
}

func (d *Driver) Session(ctx context.Context, directory, id string) (opencode.Session, error) {
	if !localSessionID(id) {
		return opencode.Session{}, errors.New("invalid WorkBuddy session id")
	}
	job, found, err := d.lookup(ctx, directory, id)
	if err != nil {
		return opencode.Session{}, err
	}
	if found {
		if !samePath(job.CWD, directory) {
			return opencode.Session{}, errors.New("WorkBuddy job workspace does not match")
		}
		return opencode.Session{ID: id, Title: job.Name, Directory: job.CWD}, nil
	}
	return opencode.Session{ID: id, Directory: directory}, nil
}

func (d *Driver) PromptAsync(ctx context.Context, directory, id, messageID, prompt string, selection ...*opencode.ModelSelection) error {
	if len(selection) > 0 && selection[0] != nil {
		return errors.New("WorkBuddy does not accept an OpenCode model selection")
	}
	if !localSessionID(id) || strings.TrimSpace(messageID) == "" || strings.TrimSpace(prompt) == "" {
		return errors.New("WorkBuddy prompt is missing session, message, or text")
	}
	note, err := d.load(id)
	if err != nil {
		return err
	}
	if note != nil && note.Dispatched {
		return errors.New("WorkBuddy prompt already submitted; not retrying")
	}
	note = &correlation{MessageID: messageID, Dispatched: true}
	if err := d.store(id, note); err != nil {
		return err
	}
	job, err := d.client.Dispatch(ctx, Dispatch{Prompt: prompt, CWD: directory, Name: id})
	if err != nil {
		return fmt.Errorf("WorkBuddy dispatch outcome is unknown; not retrying: %w", err)
	}
	note.RemoteID = job.ID
	if err := d.store(id, note); err != nil {
		return err
	}
	if job.CWD != "" && !samePath(job.CWD, directory) {
		return errors.New("WorkBuddy accepted a different workspace; not retrying")
	}
	return nil
}

func (d *Driver) Statuses(ctx context.Context, directory string) (map[string]opencode.Status, error) {
	jobs, err := d.client.List(ctx, directory)
	if err != nil {
		return nil, err
	}
	out := map[string]opencode.Status{}
	for _, job := range jobs {
		if job.Name == "" || !samePath(job.CWD, directory) {
			continue
		}
		kind, err := statusKind(job)
		if err != nil {
			return nil, err
		}
		out[job.Name] = opencode.Status{Type: kind}
	}
	return out, nil
}

func (d *Driver) Messages(ctx context.Context, directory, id string) ([]opencode.Message, error) {
	note, err := d.load(id)
	if err != nil {
		return nil, err
	}
	if note == nil || note.MessageID == "" {
		return []opencode.Message{}, nil
	}
	job, found, err := d.lookup(ctx, directory, id)
	if err != nil {
		return nil, err
	}
	user := opencode.Message{Info: opencode.MessageInfo{ID: note.MessageID, SessionID: id, Role: "user"}}
	if !found {
		return []opencode.Message{user}, nil
	}
	assistant, terminal, err := assistantMessage(id, note.MessageID, job)
	if err != nil {
		return nil, err
	}
	if !terminal {
		return []opencode.Message{user, assistant}, nil
	}
	return []opencode.Message{user, assistant}, nil
}

func (d *Driver) PendingPermissions(context.Context, string) ([]json.RawMessage, error) {
	return []json.RawMessage{}, nil
}

func (d *Driver) PendingQuestions(ctx context.Context, directory string) ([]json.RawMessage, error) {
	jobs, err := d.client.List(ctx, directory)
	if err != nil {
		return nil, err
	}
	out := []json.RawMessage{}
	for _, job := range jobs {
		if job.Name == "" || !samePath(job.CWD, directory) || !waiting(job) {
			continue
		}
		raw, err := json.Marshal(questionFor(job.Name, assistantID(job), job.Question))
		if err != nil {
			return nil, err
		}
		out = append(out, raw)
	}
	return out, nil
}

func (d *Driver) Abort(ctx context.Context, directory, id string) (bool, error) {
	job, found, err := d.lookup(ctx, directory, id)
	if err != nil {
		return false, err
	}
	if !found {
		return false, errors.New("WorkBuddy job is not on the daemon")
	}
	if err := d.client.Stop(ctx, job.ID); err != nil {
		return false, err
	}
	return true, nil
}

func (d *Driver) ReplyQuestion(ctx context.Context, directory, qid string, answers [][]string) error {
	if !opencode.ValidQuestionID(qid) {
		return errors.New("invalid WorkBuddy question id")
	}
	job, err := d.jobForQuestion(ctx, directory, qid)
	if err != nil {
		return err
	}
	text := flatten(answers)
	if text == "" {
		return errors.New("WorkBuddy reply text is required")
	}
	return d.client.Reply(ctx, job.ID, text)
}

func (d *Driver) RejectQuestion(ctx context.Context, directory, qid string) error {
	if !opencode.ValidQuestionID(qid) {
		return errors.New("invalid WorkBuddy question id")
	}
	job, err := d.jobForQuestion(ctx, directory, qid)
	if err != nil {
		return err
	}
	return d.client.Stop(ctx, job.ID)
}

func (d *Driver) OpenEvents(ctx context.Context, directory string) (executor.EventReader, error) {
	return openEvents(ctx, d.client, directory)
}

func (d *Driver) lookup(ctx context.Context, directory, local string) (Job, bool, error) {
	note, err := d.load(local)
	if err != nil {
		return Job{}, false, err
	}
	if note != nil && note.RemoteID != "" {
		job, err := d.client.Get(ctx, note.RemoteID)
		if err == nil {
			if job.Name == "" {
				job.Name = local
			}
			return job, true, nil
		}
		var httpErr *HTTPError
		if !errors.As(err, &httpErr) || httpErr.StatusCode != http.StatusNotFound {
			return Job{}, false, err
		}
	}
	jobs, err := d.client.List(ctx, directory)
	if err != nil {
		return Job{}, false, err
	}
	var found *Job
	for i := range jobs {
		if jobs[i].Name == local && samePath(jobs[i].CWD, directory) {
			if found != nil {
				return Job{}, false, errors.New("multiple WorkBuddy jobs match this session")
			}
			copy := jobs[i]
			found = &copy
		}
	}
	if found == nil {
		return Job{}, false, nil
	}
	if note != nil && note.RemoteID == "" {
		note.RemoteID = found.ID
		_ = d.store(local, note)
	}
	return *found, true, nil
}

func (d *Driver) jobForQuestion(ctx context.Context, directory, qid string) (Job, error) {
	jobs, err := d.client.List(ctx, directory)
	if err != nil {
		return Job{}, err
	}
	for _, job := range jobs {
		if job.Name != "" && questionID(job.Name) == qid && samePath(job.CWD, directory) {
			return job, nil
		}
	}
	return Job{}, errors.New("WorkBuddy question is not pending")
}

type correlation struct {
	MessageID  string `json:"messageId"`
	RemoteID   string `json:"remoteId,omitempty"`
	Dispatched bool   `json:"dispatched"`
}

func (d *Driver) path(id string) (string, error) {
	if !localSessionID(id) {
		return "", errors.New("invalid WorkBuddy session id")
	}
	return filepath.Join(d.dir, id+".json"), nil
}

func (d *Driver) load(id string) (*correlation, error) {
	path, err := d.path(id)
	if err != nil {
		return nil, err
	}
	b, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var note correlation
	if err := json.Unmarshal(b, &note); err != nil {
		return nil, err
	}
	return &note, nil
}

func (d *Driver) store(id string, note *correlation) error {
	d.mu.Lock()
	defer d.mu.Unlock()
	path, err := d.path(id)
	if err != nil {
		return err
	}
	b, err := json.Marshal(note)
	if err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, b, 0600); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

func localID(directory, title string) string {
	sum := sha256.Sum256([]byte(directory + "\n" + title))
	return "wb" + hex.EncodeToString(sum[:16])
}

func localSessionID(id string) bool {
	if len(id) != 34 || !strings.HasPrefix(id, "wb") {
		return false
	}
	for _, c := range id[2:] {
		if !(c >= '0' && c <= '9' || c >= 'a' && c <= 'f') {
			return false
		}
	}
	return true
}

func assistantID(job Job) string { return "wbmsg_" + job.ID }

func questionID(local string) string {
	sum := sha256.Sum256([]byte("workbuddy-question:" + local))
	return "que_" + hex.EncodeToString(sum[:8])
}

func questionFor(local, messageID, text string) opencode.Question {
	if strings.TrimSpace(text) == "" {
		text = "WorkBuddy is waiting for input"
	}
	custom := true
	return opencode.Question{
		ID:        questionID(local),
		SessionID: local,
		Questions: []opencode.QuestionInfo{{Question: text, Header: "WorkBuddy", Custom: &custom}},
		Tool:      &opencode.QuestionTool{MessageID: messageID, CallID: "call_" + questionID(local)},
	}
}

func waiting(job Job) bool {
	return job.State == "blocked" || job.Status == "waiting"
}

func statusKind(job Job) (string, error) {
	switch {
	case job.State == "working" || job.Status == "busy":
		return "busy", nil
	case waiting(job):
		return "waiting", nil
	case job.State == "done" || job.State == "failed" || job.State == "stopped" || job.Status == "stopped" || job.Status == "idle":
		return "idle", nil
	default:
		return "", errors.New("WorkBuddy job state is not recognized")
	}
}

func assistantMessage(local, parent string, job Job) (opencode.Message, bool, error) {
	now := time.Now().UnixMilli()
	msg := opencode.Message{Info: opencode.MessageInfo{ID: assistantID(job), SessionID: local, ParentID: parent, Role: "assistant"}}
	msg.Info.Time.Created = now - 1000
	switch job.State {
	case "done":
		msg.Info.Finish = "stop"
		msg.Info.Time.Completed = now
		text := job.Summary
		if text == "" {
			text = "WorkBuddy reported the job done"
		}
		executed := json.RawMessage(`{"providerExecuted":true}`)
		msg.Parts = []opencode.Part{
			{ID: "wbtxt_" + job.ID, SessionID: local, MessageID: msg.Info.ID, Type: "text", Text: text},
			{ID: "wbtool_" + job.ID, SessionID: local, MessageID: msg.Info.ID, Type: "tool", Tool: "workbuddy", CallID: "call_wb_" + job.ID, Metadata: executed, State: opencode.ToolState{Status: "completed", Output: clip(text), Metadata: executed}},
		}
		return msg, true, nil
	case "failed":
		reason := job.Error
		if reason == "" {
			reason = "WorkBuddy reported the job failed"
		}
		raw, _ := json.Marshal(reason)
		msg.Info.Finish = "error"
		msg.Info.Error = raw
		msg.Info.Time.Completed = now
		msg.Parts = []opencode.Part{{ID: "wbtxt_" + job.ID, SessionID: local, MessageID: msg.Info.ID, Type: "text", Text: reason}}
		return msg, true, nil
	case "stopped":
		raw, _ := json.Marshal("WorkBuddy stopped the job")
		msg.Info.Finish = "error"
		msg.Info.Error = raw
		msg.Info.Time.Completed = now
		msg.Parts = []opencode.Part{{ID: "wbtxt_" + job.ID, SessionID: local, MessageID: msg.Info.ID, Type: "text", Text: "WorkBuddy stopped the job"}}
		return msg, true, nil
	case "working", "blocked":
		if waiting(job) {
			q := questionFor(local, msg.Info.ID, job.Question)
			msg.Parts = []opencode.Part{{
				ID: "wbq_" + job.ID, SessionID: local, MessageID: msg.Info.ID, Type: "tool", Tool: "question", CallID: q.Tool.CallID,
				State: opencode.ToolState{Status: "running", Input: json.RawMessage(`{"question":true}`)},
			}}
		}
		return msg, false, nil
	default:
		if job.Status == "busy" || job.Status == "waiting" || job.Status == "idle" || job.Status == "stopped" {
			return msg, false, nil
		}
		return opencode.Message{}, false, errors.New("WorkBuddy job state is not recognized")
	}
}

func flatten(answers [][]string) string {
	var parts []string
	for _, group := range answers {
		for _, item := range group {
			item = strings.TrimSpace(item)
			if item != "" {
				parts = append(parts, item)
			}
		}
	}
	return strings.Join(parts, "\n")
}

func clip(s string) string {
	if len(s) > 4096 {
		return s[:4096]
	}
	return s
}

func samePath(a, b string) bool {
	a = filepath.Clean(a)
	b = filepath.Clean(b)
	if runtime.GOOS == "windows" {
		return strings.EqualFold(a, b)
	}
	return a == b
}

type eventStream struct {
	body   io.ReadCloser
	scan   *bufio.Scanner
	cancel context.CancelFunc
}

func (e *eventStream) Close() error { e.cancel(); return e.body.Close() }

func (e *eventStream) Next() (opencode.Event, error) {
	var data []string
	for e.scan.Scan() {
		line := e.scan.Text()
		if line == "" {
			if len(data) == 0 {
				continue
			}
			return decodeEvent(strings.Join(data, "\n"))
		}
		if strings.HasPrefix(line, "data:") {
			data = append(data, strings.TrimSpace(strings.TrimPrefix(line, "data:")))
		}
	}
	if err := e.scan.Err(); err != nil {
		return opencode.Event{}, err
	}
	return opencode.Event{}, io.EOF
}

func decodeEvent(payload string) (opencode.Event, error) {
	var raw map[string]any
	if err := json.Unmarshal([]byte(payload), &raw); err != nil {
		return opencode.Event{}, err
	}
	kind, _ := raw["type"].(string)
	if kind == "" {
		kind, _ = raw["event"].(string)
	}
	if kind == "" {
		kind = "workbuddy.event"
	}
	properties, _ := json.Marshal(raw)
	return opencode.Event{Type: kind, Properties: properties}, nil
}

func openEvents(ctx context.Context, client *Client, directory string) (executor.EventReader, error) {
	ctx, cancel := context.WithCancel(ctx)
	timer := time.AfterFunc(15*time.Second, cancel)
	u := *client.base
	u.Path = "/api/v1/jobs/events"
	q := u.Query()
	if directory != "" {
		q.Set("cwd", directory)
	}
	u.RawQuery = q.Encode()
	req, err := http.NewRequestWithContext(ctx, "GET", u.String(), nil)
	if err != nil {
		timer.Stop()
		cancel()
		return nil, err
	}
	req.Header.Set("Accept", "text/event-stream")
	req.Header.Set(headerName, "1")
	req.Header.Set("Authorization", "Bearer "+client.password)
	hc := *client.http
	hc.Timeout = 0
	res, err := hc.Do(req)
	if err != nil {
		timer.Stop()
		cancel()
		return nil, err
	}
	if res.StatusCode != http.StatusOK {
		res.Body.Close()
		timer.Stop()
		cancel()
		return nil, &HTTPError{StatusCode: res.StatusCode, Body: "event stream unavailable"}
	}
	stream := &eventStream{body: res.Body, scan: bufio.NewScanner(res.Body), cancel: cancel}
	stream.scan.Buffer(make([]byte, 4096), 2<<20)
	if _, err := stream.Next(); err != nil {
		stream.Close()
		timer.Stop()
		return nil, err
	}
	timer.Stop()
	return stream, nil
}
