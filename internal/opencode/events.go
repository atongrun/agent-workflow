package opencode

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

type Event struct {
	Type       string          `json:"type"`
	Properties json.RawMessage `json:"properties"`
}
type Events struct {
	body    io.ReadCloser
	scanner *bufio.Scanner
	cancel  context.CancelFunc
}

func (e *Events) Close() error { e.cancel(); return e.body.Close() }

// Next decodes data fields, including legal multi-line SSE payloads.
func (e *Events) Next() (Event, error) {
	var lines []string
	size := 0
	for e.scanner.Scan() {
		line := e.scanner.Text()
		if line == "" {
			if len(lines) == 0 {
				continue
			}
			var event Event
			err := json.Unmarshal([]byte(strings.Join(lines, "\n")), &event)
			return event, err
		}
		if strings.HasPrefix(line, "data:") {
			size += len(line) + 1
			if size > 2<<20 {
				return Event{}, errors.New("native SSE frame exceeds 2 MiB")
			}
			lines = append(lines, strings.TrimPrefix(strings.TrimPrefix(line, "data:"), " "))
		}
	}
	if err := e.scanner.Err(); err != nil {
		return Event{}, err
	}
	return Event{}, io.EOF
}

// OpenEvents consumes the connected handshake before returning, so a subsequent
// prompt cannot outrun listener setup. Reconnection never replays prompts.
func (c *Client) OpenEvents(ctx context.Context, directory string) (*Events, error) {
	ctx, cancel := context.WithCancel(ctx)
	timer := time.AfterFunc(15*time.Second, cancel)
	u := *c.base
	u.Path = "/event"
	q := url.Values{}
	q.Set("directory", directory)
	u.RawQuery = q.Encode()
	req, err := http.NewRequestWithContext(ctx, "GET", u.String(), nil)
	if err != nil {
		timer.Stop()
		cancel()
		return nil, err
	}
	req.Header.Set("Accept", "text/event-stream")
	if c.password != "" {
		req.SetBasicAuth(c.username, c.password)
	}
	hc := *c.http
	hc.Timeout = 0
	res, err := hc.Do(req)
	if err != nil {
		timer.Stop()
		cancel()
		return nil, err
	}
	if res.StatusCode != 200 {
		res.Body.Close()
		timer.Stop()
		cancel()
		return nil, &HTTPError{StatusCode: res.StatusCode, Body: "event stream unavailable"}
	}
	e := &Events{body: res.Body, scanner: bufio.NewScanner(res.Body), cancel: cancel}
	e.scanner.Buffer(make([]byte, 4096), 2<<20)
	event, err := e.Next()
	timer.Stop()
	if err != nil {
		e.Close()
		return nil, err
	}
	if event.Type != "server.connected" {
		e.Close()
		return nil, errors.New("native event stream did not begin with server.connected")
	}
	return e, nil
}
