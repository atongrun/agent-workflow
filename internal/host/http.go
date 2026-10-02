package host

import (
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
)

type apiError struct {
	Code    string
	Message string
	Status  int
}

func (e *apiError) Error() string                 { return e.Message }
func fail(code, message string, status int) error { return &apiError{code, message, status} }
func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
func writeError(w http.ResponseWriter, err error) {
	var e *apiError
	if !errors.As(err, &e) {
		e = &apiError{"internal", err.Error(), 500}
	}
	writeJSON(w, e.Status, map[string]any{"error": map[string]string{"code": e.Code, "message": e.Message}})
}
func decode(w http.ResponseWriter, r *http.Request, v any) error {
	r.Body = http.MaxBytesReader(w, r.Body, 1024*1024)
	d := json.NewDecoder(r.Body)
	d.DisallowUnknownFields()
	if err := d.Decode(v); err != nil {
		return fail("invalid_json", err.Error(), 400)
	}
	if d.Decode(&struct{}{}) != io.EOF {
		return fail("invalid_json", "expected one JSON object", 400)
	}
	return nil
}
func auth(token string, h http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
		if !strings.HasPrefix(r.Header.Get("Authorization"), "Bearer ") || subtle.ConstantTimeCompare([]byte(got), []byte(token)) != 1 {
			writeError(w, fail("unauthorized", "valid bearer token required", 401))
			return
		}
		h.ServeHTTP(w, r)
	})
}
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	public := http.NewServeMux()
	public.HandleFunc("GET /v1/health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]any{"status": "ok", "version": "v1"})
	})
	public.HandleFunc("GET /v1/targets", s.targets)
	public.HandleFunc("PATCH /v1/tasks/{id}/target", s.updateTarget)
	public.HandleFunc("GET /v1/tasks", s.listTasks)
	public.HandleFunc("POST /v1/tasks", s.createTask)
	public.HandleFunc("GET /v1/tasks/{id}", s.getTask)
	public.HandleFunc("POST /v1/tasks/{id}/delete", s.taskLifecycle)
	public.HandleFunc("POST /v1/tasks/{id}/restore", s.taskLifecycle)
	public.HandleFunc("GET /v1/settings", s.settings)
	public.HandleFunc("PATCH /v1/settings", s.settings)
	public.HandleFunc("GET /v1/agents", s.agents)
	public.HandleFunc("GET /v1/overview", s.overview)
	public.HandleFunc("GET /v1/tasks/{id}/messages", s.messages)
	public.HandleFunc("GET /v1/tasks/{id}/events", s.events)
	public.HandleFunc("GET /v1/tasks/{id}/requests/{requestId}", s.piRequest)
	public.HandleFunc("POST /v1/tasks/{id}/requests/{requestId}", s.requestLookup)
	for _, read := range []string{"commands", "stats", "models"} {
		public.HandleFunc("GET /v1/tasks/{id}/pi/"+read, s.piRead)
	}
	for _, control := range []string{"model", "compact", "abort"} {
		public.HandleFunc("POST /v1/tasks/{id}/pi/"+control, s.piControl)
	}
	for _, action := range []string{"messages", "pi/ui-response", "plan/confirm", "start", "execution/cancel", "review", "rework"} {
		public.HandleFunc("POST /v1/tasks/{id}/"+action, s.action)
	}
	mux.Handle("/v1/", auth(s.token, public))
	internal := http.NewServeMux()
	internal.HandleFunc("POST /internal/tasks/{id}/{action}", s.internalAction)
	mux.Handle("/internal/", s.internalAuth(internal))
	return mux
}
func (s *Server) task(id string) (*core.Task, error) {
	t := s.store.Snapshot().Tasks[id]
	if t == nil {
		return nil, fail("not_found", "task not found", 404)
	}
	return t, nil
}
func (s *Server) getTask(w http.ResponseWriter, r *http.Request) {
	t, err := s.task(r.PathValue("id"))
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, 200, map[string]any{"task": t})
}
func sortedTasks(st core.State) []*core.Task {
	items := make([]*core.Task, 0, len(st.Tasks))
	for _, t := range st.Tasks {
		if t.DeletedAt != nil {
			continue
		}
		items = append(items, t)
	}
	sort.Slice(items, func(i, j int) bool { return items[i].CreatedAt.After(items[j].CreatedAt) })
	return items
}
func (s *Server) listTasks(w http.ResponseWriter, r *http.Request) {
	query := r.URL.Query()
	if len(query) > 0 && (len(query) != 1 || len(query["deleted"]) != 1 || (query.Get("deleted") != "true" && query.Get("deleted") != "false")) {
		writeError(w, fail("invalid_query", "deleted must be a single true or false value", 400))
		return
	}
	st := s.store.Snapshot()
	items := sortedTasks(st)
	if query.Get("deleted") == "true" {
		items = []*core.Task{}
		for _, t := range st.Tasks {
			if t.DeletedAt != nil {
				items = append(items, t)
			}
		}
		sort.Slice(items, func(i, j int) bool { return items[i].DeletedAt.After(*items[j].DeletedAt) })
	}
	writeJSON(w, 200, map[string]any{"tasks": items})
}

var requestPattern = regexp.MustCompile(`^[A-Za-z0-9._:-]{1,128}$`)

func (s *Server) reserve(id, taskID, op string, payload any, fn func(*core.State) error) (bool, error) {
	return s.reserveRequest(id, taskID, op, payload, func(st *core.State, _ *core.Request) error { return fn(st) })
}
func (s *Server) reserveRequest(id, taskID, op string, payload any, fn func(*core.State, *core.Request) error) (bool, error) {
	if !requestPattern.MatchString(id) {
		return false, fail("invalid_request_id", "requestId must be 1–128 safe characters", 400)
	}
	b, _ := json.Marshal(payload)
	h := sha256.Sum256(b)
	hash := hex.EncodeToString(h[:])
	duplicate := false
	err := s.store.Update(func(st *core.State) error {
		if old := st.Requests[id]; old != nil {
			if old.TaskID != taskID || old.Operation != op || old.Hash != hash {
				return fail("idempotency_conflict", "requestId was already used with different operation or payload", 409)
			}
			duplicate = true
			return nil
		}
		// Historical exact retries are receipts only. Every newly reserved task
		// mutation, including extension tools and automatic dispatch, is fenced.
		if task := st.Tasks[taskID]; task != nil && task.DeletedAt != nil && op != "delete" && op != "restore" {
			return fail("task_deleted", "restore this task before making changes", 409)
		}
		request := &core.Request{ID: id, TaskID: taskID, Operation: op, Hash: hash, Status: "accepted", CreatedAt: time.Now().UTC()}
		if err := fn(st, request); err != nil {
			return err
		}
		st.Requests[id] = request
		return nil
	})
	return duplicate, err
}
func (s *Server) response(w http.ResponseWriter, id string) {
	st := s.store.Snapshot()
	req := st.Requests[id]
	writeJSON(w, 202, map[string]any{"task": st.Tasks[req.TaskID], "request": req})
}
func (s *Server) requestDone(id, status string, err error) {
	_ = s.store.Update(func(st *core.State) error {
		if r := st.Requests[id]; r != nil {
			r.Status = status
			if err != nil {
				r.Error = err.Error()
				if t := st.Tasks[r.TaskID]; t != nil {
					t.LastError = err.Error()
					core.Changed(st, t)
				}
			}
		}
		return nil
	})
}

type createInput struct {
	PlanID             string `json:"planId,omitempty"`
	RequestID          string `json:"requestId"`
	Title              string `json:"title"`
	ProjectID          string `json:"projectId"`
	Repository         string `json:"repository"`
	Goal               string `json:"goal"`
	AcceptanceCriteria string `json:"acceptanceCriteria"`
	NodeID             string `json:"nodeId"`
}

func (s *Server) createTask(w http.ResponseWriter, r *http.Request) {
	var in createInput
	if err := decode(w, r, &in); err != nil {
		writeError(w, err)
		return
	}
	sum := sha256.Sum256([]byte("awf-task:" + in.RequestID))
	rawID := hex.EncodeToString(sum[:16])
	taskID := rawID[:8] + "-" + rawID[8:12] + "-" + rawID[12:16] + "-" + rawID[16:20] + "-" + rawID[20:]
	if prev := s.store.Snapshot().Requests[in.RequestID]; prev != nil {
		taskID = prev.TaskID
	}
	_, err := s.reserve(in.RequestID, taskID, "create", in, func(st *core.State) error {
		// Keep validation inside the reservation: exact historical retries must
		// remain readable even after mutable configuration is removed.
		if strings.TrimSpace(in.Title) == "" {
			return fail("invalid_task", "title is required", 400)
		}
		if in.ProjectID != "" && s.cfg.Projects[in.ProjectID] == "" {
			return fail("unknown_project", "projectId is not configured", 400)
		}
		if in.NodeID != "" {
			if _, ok := s.cfg.Nodes[in.NodeID]; !ok {
				return fail("unknown_node", "nodeId is not configured", 400)
			}
		}
		now := time.Now().UTC()
		planID := in.PlanID
		if planID == "" {
			planID = taskID
		}
		if !requestPattern.MatchString(planID) {
			return fail("invalid_plan_id", "planId must be a stable safe identifier", 400)
		}
		t := &core.Task{PlanningProfile: core.RestrictedPlanning, PlanID: planID, ID: taskID, Title: in.Title, ProjectID: in.ProjectID, Repository: in.Repository, Goal: in.Goal, AcceptanceCriteria: in.AcceptanceCriteria, NodeID: in.NodeID, Branch: st.Settings.BranchPrefix + taskID, Status: "created", Phase: "architecture", CreatedAt: now, UpdatedAt: now, Settings: st.Settings, ReviewHistory: []core.Review{}, Sessions: map[string]*core.Session{"architect": {ID: core.ID()}}, Budget: core.Budget{}}
		st.Tasks[t.ID] = t
		core.Changed(st, t)
		return nil
	})
	if err != nil {
		writeError(w, err)
		return
	}
	s.requestDone(in.RequestID, "completed", nil)
	s.response(w, in.RequestID)
}
func (s *Server) settings(w http.ResponseWriter, r *http.Request) {
	if r.Method == "GET" {
		writeJSON(w, 200, map[string]any{"settings": s.store.Snapshot().Settings})
		return
	}
	var in struct {
		RequestID     string `json:"requestId"`
		DefaultBranch string `json:"defaultBranch"`
		BranchPrefix  string `json:"branchPrefix"`
	}
	if err := decode(w, r, &in); err != nil {
		writeError(w, err)
		return
	}
	if in.DefaultBranch == "" || in.BranchPrefix == "" || strings.ContainsAny(in.DefaultBranch+in.BranchPrefix, "\r\n\x00") {
		writeError(w, fail("invalid_settings", "nonempty branch defaults are required", 400))
		return
	}
	_, err := s.reserve(in.RequestID, "", "settings", in, func(st *core.State) error {
		st.Settings.DefaultBranch = in.DefaultBranch
		st.Settings.BranchPrefix = in.BranchPrefix
		return nil
	})
	if err != nil {
		writeError(w, err)
		return
	}
	s.requestDone(in.RequestID, "completed", nil)
	writeJSON(w, 200, map[string]any{"settings": s.store.Snapshot().Settings})
}
func (s *Server) events(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if _, err := s.task(id); err != nil {
		writeError(w, err)
		return
	}
	cursor := r.URL.Query().Get("after")
	if v := r.Header.Get("Last-Event-ID"); v != "" {
		cursor = v
	}
	after := int64(0)
	if cursor != "" {
		n, err := strconv.ParseInt(cursor, 10, 64)
		if err != nil || n < 0 {
			writeError(w, fail("invalid_cursor", "after must be a nonnegative integer", 400))
			return
		}
		after = n
	}
	flusher, ok := w.(http.Flusher)
	if !ok {
		writeError(w, errors.New("streaming unavailable"))
		return
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache, no-transform")
	w.Header().Set("X-Accel-Buffering", "no")
	ticker := time.NewTicker(300 * time.Millisecond)
	defer ticker.Stop()
	heartbeat := time.NewTicker(15 * time.Second)
	defer heartbeat.Stop()
	for {
		replay := s.store.ReplayAfter(id, after)
		if after > replay.Sequence || (replay.First > 0 && after > 0 && after < replay.First-1) {
			b, _ := json.Marshal(core.Event{ID: replay.Sequence, Type: "replay.reset", TaskID: id, Time: time.Now().UTC(), Data: json.RawMessage(`{"reason":"cursor_expired","reloadNativeMessages":true}`)})
			fmt.Fprintf(w, "id: %d\nevent: awf\ndata: %s\n\n", replay.Sequence, b)
			b, _ = json.Marshal(core.Event{ID: replay.Sequence, Type: "task.updated", TaskID: id, Time: time.Now().UTC(), Data: mustJSON(s.store.Snapshot().Tasks[id])})
			fmt.Fprintf(w, "event: awf\ndata: %s\n\n", b)
			after = replay.Sequence
		}
		for _, e := range replay.Events {
			if e.ID > after {
				after = e.ID
				if e.TaskID == id {
					b, _ := json.Marshal(e)
					fmt.Fprintf(w, "id: %d\nevent: awf\ndata: %s\n\n", e.ID, b)
				}
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
func mustJSON(v any) json.RawMessage { b, _ := json.Marshal(v); return b }
