package host

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
)

// MCP is the streamable-HTTP endpoint on the bot listener. It exposes the same
// operations as /bot/v1 and uses that listener's bearer token and source allowlist.
// A separate process would be a second writer or a proxy with no extra boundary.

func (s *Server) routesMCP(mux *http.ServeMux) {
	mux.HandleFunc("/mcp", s.mcp)
}

func (s *Server) mcp(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodPost:
		s.mcpPost(w, r)
	case http.MethodGet:
		s.mcpGet(w, r)
	case http.MethodDelete:
		s.mcpDelete(w, r)
	default:
		writeError(w, fail("method_not_allowed", "MCP supports GET, POST, and DELETE", http.StatusMethodNotAllowed))
	}
}

func (s *Server) mcpPost(w http.ResponseWriter, r *http.Request) {
	caller, err := s.botCaller(r)
	if err != nil {
		writeError(w, err)
		return
	}
	body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 1<<20))
	if err != nil {
		writeRPCError(w, nil, -32700, "invalid JSON")
		return
	}
	if len(body) == 0 || body[0] == '[' {
		writeRPCError(w, nil, -32600, "one JSON-RPC object is required")
		return
	}
	var msg rpcMessage
	dec := json.NewDecoder(bytes.NewReader(body))
	dec.DisallowUnknownFields()
	if err = dec.Decode(&msg); err != nil || dec.Decode(&struct{}{}) != io.EOF {
		writeRPCError(w, nil, -32700, "invalid JSON-RPC message")
		return
	}
	if msg.JSONRPC != "2.0" || msg.Method == "" {
		writeRPCError(w, msg.ID, -32600, "invalid JSON-RPC request")
		return
	}
	if msg.Method == "initialize" {
		s.mcpInitialize(w, r, msg)
		return
	}
	if !s.mcpSession(r) {
		w.WriteHeader(http.StatusNotFound)
		return
	}
	if msg.ID == nil {
		if msg.Method == "notifications/initialized" || strings.HasPrefix(msg.Method, "notifications/") {
			w.WriteHeader(http.StatusAccepted)
			return
		}
		writeRPCError(w, nil, -32600, "notification is not accepted")
		return
	}
	switch msg.Method {
	case "ping":
		writeRPCResult(w, msg.ID, map[string]any{})
	case "tools/list":
		writeRPCResult(w, msg.ID, map[string]any{"tools": mcpTools()})
	case "tools/call":
		s.mcpCall(w, r, caller, msg)
	default:
		writeRPCError(w, msg.ID, -32601, "method not found")
	}
}

func (s *Server) mcpInitialize(w http.ResponseWriter, r *http.Request, msg rpcMessage) {
	if s.mcpSession(r) {
		writeRPCError(w, msg.ID, -32600, "session is already initialized")
		return
	}
	var params struct {
		ProtocolVersion string `json:"protocolVersion"`
	}
	if len(msg.Params) > 0 && json.Unmarshal(msg.Params, &params) != nil {
		writeRPCError(w, msg.ID, -32602, "invalid initialize params")
		return
	}
	id := newSessionID()
	s.mcpMu.Lock()
	s.mcpSessions[id] = struct{}{}
	s.mcpMu.Unlock()
	w.Header().Set("Mcp-Session-Id", id)
	writeRPCResult(w, msg.ID, map[string]any{
		"protocolVersion": "2025-03-26",
		"capabilities":    map[string]any{"tools": map[string]any{"listChanged": false}},
		"serverInfo":      map[string]any{"name": "awf-bot", "version": "v1"},
		"instructions":    "Coding tasks only. Reuse requestId with the same payload. Never replace an uncertain result with a new requestId.",
	})
	_ = params
}

func (s *Server) mcpSession(r *http.Request) bool {
	id := r.Header.Get("Mcp-Session-Id")
	if id == "" {
		return false
	}
	s.mcpMu.Lock()
	defer s.mcpMu.Unlock()
	_, ok := s.mcpSessions[id]
	return ok
}

func (s *Server) mcpDelete(w http.ResponseWriter, r *http.Request) {
	id := r.Header.Get("Mcp-Session-Id")
	s.mcpMu.Lock()
	defer s.mcpMu.Unlock()
	if _, ok := s.mcpSessions[id]; !ok {
		w.WriteHeader(http.StatusNotFound)
		return
	}
	delete(s.mcpSessions, id)
	w.WriteHeader(http.StatusNoContent)
}

func (s *Server) mcpGet(w http.ResponseWriter, r *http.Request) {
	if !s.mcpSession(r) {
		w.WriteHeader(http.StatusNotFound)
		return
	}
	if !strings.Contains(r.Header.Get("Accept"), "text/event-stream") {
		writeError(w, fail("not_acceptable", "GET /mcp requires text/event-stream", http.StatusNotAcceptable))
		return
	}
	flusher, ok := w.(http.Flusher)
	if !ok {
		writeError(w, fail("streaming_unavailable", "streaming unavailable", http.StatusInternalServerError))
		return
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache, no-transform")
	fmt.Fprintf(w, "event: message\ndata: %s\n\n", mustJSON(map[string]any{"jsonrpc": "2.0", "method": "notifications/initialized", "params": map[string]any{}}))
	flusher.Flush()
	ticker := time.NewTicker(15 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-r.Context().Done():
			return
		case <-s.stop:
			return
		case <-ticker.C:
			fmt.Fprint(w, ": keepalive\n\n")
			flusher.Flush()
		}
	}
}

func (s *Server) mcpCall(w http.ResponseWriter, r *http.Request, caller botCaller, msg rpcMessage) {
	var params struct {
		Name      string          `json:"name"`
		Arguments json.RawMessage `json:"arguments"`
	}
	if json.Unmarshal(msg.Params, &params) != nil || params.Name == "" {
		writeRPCError(w, msg.ID, -32602, "tools/call requires a name")
		return
	}
	if len(params.Arguments) == 0 {
		params.Arguments = json.RawMessage(`{}`)
	}
	if params.Name == "stream_events" && strings.Contains(r.Header.Get("Accept"), "text/event-stream") {
		s.mcpStreamEvents(w, r, caller, msg.ID, params.Arguments)
		return
	}
	status, payload, err := s.mcpTool(r.Context(), caller, params.Name, params.Arguments)
	if err != nil {
		writeRPCResult(w, msg.ID, mcpText(err.Error(), true))
		return
	}
	text := payload
	if status >= 400 {
		writeRPCResult(w, msg.ID, mcpText(text, true))
		return
	}
	writeRPCResult(w, msg.ID, mcpText(text, false))
}

func (s *Server) mcpTool(ctx context.Context, caller botCaller, name string, args json.RawMessage) (int, string, error) {
	var fields map[string]any
	if json.Unmarshal(args, &fields) != nil {
		return 0, "", errString("tool arguments must be an object")
	}
	switch name {
	case "list_targets":
		return s.mcpForward(ctx, caller, http.MethodGet, "/bot/v1/targets", nil)
	case "list_projects":
		return s.mcpForward(ctx, caller, http.MethodGet, "/bot/v1/projects", nil)
	case "list_tasks":
		return s.mcpForward(ctx, caller, http.MethodGet, "/bot/v1/tasks", nil)
	case "get_task":
		id, err := mcpID(fields["taskId"])
		if err != nil {
			return 0, "", err
		}
		return s.mcpForward(ctx, caller, http.MethodGet, "/bot/v1/tasks/"+id, nil)
	case "create_task":
		return s.mcpForward(ctx, caller, http.MethodPost, "/bot/v1/tasks", args)
	case "get_events", "stream_events":
		id, err := mcpID(fields["taskId"])
		if err != nil {
			return 0, "", err
		}
		after := int64(0)
		switch v := fields["after"].(type) {
		case float64:
			if v < 0 {
				return 0, "", errString("after must be a nonnegative integer")
			}
			after = int64(v)
		}
		return s.mcpForward(ctx, caller, http.MethodGet, "/bot/v1/tasks/"+id+"/events?view=snapshot&after="+strconv.FormatInt(after, 10), nil)
	case "reply_question":
		id, err := mcpID(fields["taskId"])
		if err != nil {
			return 0, "", err
		}
		qid, err := mcpID(fields["questionId"])
		if err != nil {
			return 0, "", err
		}
		delete(fields, "taskId")
		delete(fields, "questionId")
		body, _ := json.Marshal(fields)
		return s.mcpForward(ctx, caller, http.MethodPost, "/bot/v1/tasks/"+id+"/questions/"+qid+"/reply", body)
	case "cancel_task":
		id, err := mcpID(fields["taskId"])
		if err != nil {
			return 0, "", err
		}
		delete(fields, "taskId")
		body, _ := json.Marshal(fields)
		return s.mcpForward(ctx, caller, http.MethodPost, "/bot/v1/tasks/"+id+"/cancel", body)
	default:
		return 0, "", errString("unknown tool")
	}
}

func (s *Server) mcpForward(ctx context.Context, caller botCaller, method, path string, body []byte) (int, string, error) {
	var reader io.Reader
	if body != nil {
		reader = bytes.NewReader(body)
	}
	req, err := http.NewRequestWithContext(context.WithValue(ctx, botCallerKey, caller.ID), method, path, reader)
	if err != nil {
		return 0, "", err
	}
	req.Header.Set("Accept", "application/json")
	req.RemoteAddr = "127.0.0.1:1"
	rec := &captureResponse{header: http.Header{}}
	s.botRoutes().ServeHTTP(rec, req)
	if rec.code == 0 {
		rec.code = http.StatusOK
	}
	return rec.code, rec.buf.String(), nil
}

func (s *Server) botRoutes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /bot/v1/targets", s.targets)
	mux.HandleFunc("GET /bot/v1/projects", s.botProjects)
	mux.HandleFunc("GET /bot/v1/tasks", s.botListTasks)
	mux.HandleFunc("POST /bot/v1/tasks", s.botCreateTask)
	mux.HandleFunc("GET /bot/v1/tasks/{id}", s.botGetTask)
	mux.HandleFunc("GET /bot/v1/tasks/{id}/events", s.botEvents)
	mux.HandleFunc("POST /bot/v1/tasks/{id}/questions/{questionId}/reply", s.botQuestionReply)
	mux.HandleFunc("POST /bot/v1/tasks/{id}/cancel", s.botCancel)
	return mux
}

func (s *Server) mcpStreamEvents(w http.ResponseWriter, r *http.Request, caller botCaller, id json.RawMessage, args json.RawMessage) {
	var fields struct {
		TaskID string `json:"taskId"`
		After  int64  `json:"after"`
	}
	if json.Unmarshal(args, &fields) != nil || fields.TaskID == "" {
		writeRPCError(w, id, -32602, "stream_events requires taskId")
		return
	}
	task, err := s.task(fields.TaskID)
	if err != nil || task.Caller != caller.ID {
		writeRPCResult(w, id, mcpText(`{"error":{"code":"not_found","message":"task not found"}}`, true))
		return
	}
	flusher, ok := w.(http.Flusher)
	if !ok {
		writeRPCError(w, id, -32603, "streaming unavailable")
		return
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache, no-transform")
	after := fields.After
	page, sequence := s.eventPage(fields.TaskID, after)
	writeMCPEvent(w, map[string]any{"jsonrpc": "2.0", "id": json.RawMessage(id), "result": mcpText(page, false)})
	flusher.Flush()
	// The initial result already contains events through sequence.
	after = sequence
	ticker := time.NewTicker(300 * time.Millisecond)
	defer ticker.Stop()
	heartbeat := time.NewTicker(15 * time.Second)
	defer heartbeat.Stop()
	for {
		replay := s.store.ReplayAfter(fields.TaskID, after)
		if after > replay.Sequence || (replay.First > 0 && after > 0 && after < replay.First-1) {
			writeMCPEvent(w, map[string]any{"jsonrpc": "2.0", "method": "notifications/awf/event", "params": map[string]any{"type": "replay.reset", "sequence": replay.Sequence}})
			after = replay.Sequence
		}
		for _, event := range replay.Events {
			if event.ID > after && event.TaskID == fields.TaskID {
				after = event.ID
				writeMCPEvent(w, map[string]any{"jsonrpc": "2.0", "method": "notifications/awf/event", "params": event})
			}
		}
		flusher.Flush()
		select {
		case <-r.Context().Done():
			return
		case <-s.stop:
			return
		case <-ticker.C:
		case <-heartbeat.C:
			fmt.Fprint(w, ": keepalive\n\n")
			flusher.Flush()
		}
	}
}

func (s *Server) eventPage(id string, after int64) (string, int64) {
	replay := s.store.ReplayAfter(id, after)
	reset := after > replay.Sequence || (replay.First > 0 && after > 0 && after < replay.First-1)
	events := replay.Events
	if events == nil {
		events = []core.Event{}
	}
	b, _ := json.Marshal(map[string]any{"events": events, "sequence": replay.Sequence, "reset": reset})
	return string(b), replay.Sequence
}

type rpcMessage struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      json.RawMessage `json:"id,omitempty"`
	Method  string          `json:"method,omitempty"`
	Params  json.RawMessage `json:"params,omitempty"`
}

type captureResponse struct {
	header http.Header
	code   int
	buf    bytes.Buffer
}

func (c *captureResponse) Header() http.Header { return c.header }
func (c *captureResponse) WriteHeader(status int) {
	if c.code == 0 {
		c.code = status
	}
}
func (c *captureResponse) Write(b []byte) (int, error) {
	if c.code == 0 {
		c.code = http.StatusOK
	}
	return c.buf.Write(b)
}

func mcpTools() []map[string]any {
	empty := map[string]any{"type": "object", "properties": map[string]any{}}
	task := map[string]any{"type": "object", "properties": map[string]any{"taskId": map[string]any{"type": "string"}}, "required": []string{"taskId"}}
	return []map[string]any{
		{"name": "list_targets", "description": "List execution targets and nodes. No workspace paths or credentials.", "inputSchema": empty},
		{"name": "list_projects", "description": "List configured projects and the nodes that can run them.", "inputSchema": empty},
		{"name": "list_tasks", "description": "List tasks created by this bot caller.", "inputSchema": empty},
		{"name": "get_task", "description": "Read one task owned by this caller, including execution status.", "inputSchema": task},
		{"name": "create_task", "description": "Create a coding task. Auto-start follows the caller and project policy and defaults to on. Reuse requestId only with the same payload. Do not invent a new requestId after an uncertain result.", "inputSchema": map[string]any{"type": "object", "properties": map[string]any{"requestId": map[string]any{"type": "string"}, "title": map[string]any{"type": "string"}, "projectId": map[string]any{"type": "string"}, "nodeId": map[string]any{"type": "string"}, "repository": map[string]any{"type": "string"}, "repositoryId": map[string]any{"type": "string"}, "goal": map[string]any{"type": "string"}, "acceptanceCriteria": map[string]any{"type": "string"}, "plan": map[string]any{"type": "string"}}, "required": []string{"requestId", "title"}}},
		{"name": "get_events", "description": "Read task events after a cursor. reset means the cursor expired; reload the task.", "inputSchema": map[string]any{"type": "object", "properties": map[string]any{"taskId": map[string]any{"type": "string"}, "after": map[string]any{"type": "integer"}}, "required": []string{"taskId"}}},
		{"name": "stream_events", "description": "Stream task events. With Accept text/event-stream this stays open; otherwise it returns the same page as get_events.", "inputSchema": map[string]any{"type": "object", "properties": map[string]any{"taskId": map[string]any{"type": "string"}, "after": map[string]any{"type": "integer"}}, "required": []string{"taskId"}}},
		{"name": "reply_question", "description": "Answer one bound executor question. Keep the original requestId if the outcome is uncertain.", "inputSchema": map[string]any{"type": "object", "properties": map[string]any{"taskId": map[string]any{"type": "string"}, "questionId": map[string]any{"type": "string"}, "requestId": map[string]any{"type": "string"}, "executionRequestId": map[string]any{"type": "string"}, "jobId": map[string]any{"type": "string"}, "sessionId": map[string]any{"type": "string"}, "answers": map[string]any{"type": "array"}}, "required": []string{"taskId", "questionId", "requestId", "executionRequestId", "jobId", "sessionId", "answers"}}},
		{"name": "cancel_task", "description": "Cancel the current execution. Retry the same requestId. There is no task removal tool.", "inputSchema": map[string]any{"type": "object", "properties": map[string]any{"taskId": map[string]any{"type": "string"}, "requestId": map[string]any{"type": "string"}, "executionRequestId": map[string]any{"type": "string"}}, "required": []string{"taskId", "requestId", "executionRequestId"}}},
	}
}

func mcpText(text string, isError bool) map[string]any {
	return map[string]any{"content": []map[string]any{{"type": "text", "text": text}}, "isError": isError}
}

func writeRPCResult(w http.ResponseWriter, id json.RawMessage, result any) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{"jsonrpc": "2.0", "id": json.RawMessage(id), "result": result})
}

func writeRPCError(w http.ResponseWriter, id json.RawMessage, code int, message string) {
	w.Header().Set("Content-Type", "application/json")
	payload := map[string]any{"jsonrpc": "2.0", "error": map[string]any{"code": code, "message": message}}
	if id != nil {
		payload["id"] = json.RawMessage(id)
	} else {
		payload["id"] = nil
	}
	_ = json.NewEncoder(w).Encode(payload)
}

func writeMCPEvent(w http.ResponseWriter, payload any) {
	b, _ := json.Marshal(payload)
	fmt.Fprintf(w, "event: message\ndata: %s\n\n", b)
}

func mcpID(value any) (string, error) {
	id, _ := value.(string)
	if id == "" || strings.ContainsAny(id, "/?#\\") || id == "." || id == ".." {
		return "", errString("task and question ids must be a single path segment")
	}
	return id, nil
}

func newSessionID() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return hex.EncodeToString([]byte(time.Now().UTC().Format(time.RFC3339Nano)))
	}
	return hex.EncodeToString(b[:])
}
