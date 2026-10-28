package host

import (
	"context"
	"crypto/subtle"
	"net/http"
	"net/netip"
	"os"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
)

type botCaller struct {
	ID     string
	Token  string
	Policy BotCallerConfig
}

func (c botCaller) autoStart(project string) bool {
	if c.Policy.Projects != nil {
		if projectPolicy, ok := c.Policy.Projects[project]; ok && projectPolicy.AutoStart != nil {
			return *projectPolicy.AutoStart
		}
	}
	if c.Policy.AutoStart != nil {
		return *c.Policy.AutoStart
	}
	return true
}

type botCallerKeyType struct{}

var botCallerKey botCallerKeyType

func botIdentity(cfg Config, hostToken, extensionToken string) ([]botCaller, map[netip.Addr]struct{}, error) {
	if cfg.Bot == nil {
		return nil, nil, nil
	}
	if len(cfg.Bot.Callers) == 0 {
		return nil, nil, errString("bot callers are required when the bot listener is configured")
	}
	allowed := map[netip.Addr]struct{}{}
	for i, value := range cfg.Bot.AllowedSourceIPs {
		addr, err := netip.ParseAddr(value)
		if err != nil || addr.Zone() != "" || !(addr.IsGlobalUnicast() || addr.IsLoopback() || addr.IsLinkLocalUnicast()) {
			return nil, nil, errString("bot allowedSourceIPs[" + strconv.Itoa(i) + "] must be an exact unicast IP address without a zone")
		}
		allowed[addr.Unmap()] = struct{}{}
	}
	listen, err := netip.ParseAddrPort(cfg.Bot.Listen)
	if err != nil || listen.Addr().Zone() != "" {
		return nil, nil, errString("bot listen must be a literal IP address and numeric port")
	}
	if !listen.Addr().Unmap().IsLoopback() && len(allowed) == 0 {
		return nil, nil, errString("non-loopback bot listen requires explicit allowedSourceIPs")
	}
	ids := make([]string, 0, len(cfg.Bot.Callers))
	for id := range cfg.Bot.Callers {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	callers := make([]botCaller, 0, len(ids))
	seen := map[string]string{}
	for _, id := range ids {
		policy := cfg.Bot.Callers[id]
		if !requestPattern.MatchString(id) {
			return nil, nil, errString("bot caller id must be a stable safe identifier")
		}
		token := os.Getenv(policy.TokenEnv)
		if len(token) < 24 || token == hostToken || token == extensionToken {
			return nil, nil, errString("each bot caller needs a distinct token of at least 24 characters")
		}
		if previous, ok := seen[token]; ok {
			return nil, nil, errString("bot callers " + previous + " and " + id + " share a token")
		}
		seen[token] = id
		for project := range policy.Projects {
			if cfg.Projects[project] == "" && project != "managed" {
				return nil, nil, errString("bot project policy must name a configured project")
			}
		}
		callers = append(callers, botCaller{ID: id, Token: token, Policy: policy})
	}
	return callers, allowed, nil
}

func errString(message string) error { return &botConfigError{message} }

type botConfigError struct{ message string }

func (e *botConfigError) Error() string { return e.message }

func (s *Server) BotHandler() http.Handler {
	mux := http.NewServeMux()
	mux.Handle("/bot/", s.botRoutes())
	s.routesMCP(mux)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if len(s.botCallers) == 0 {
			writeError(w, fail("bot_disabled", "bot API is not configured", http.StatusServiceUnavailable))
			return
		}
		if !s.botSourceAllowed(r.RemoteAddr) {
			writeError(w, fail("source_denied", "source address is not allowed", http.StatusForbidden))
			return
		}
		caller, ok := s.matchBotCaller(r.Header.Get("Authorization"))
		if !ok {
			w.Header().Set("WWW-Authenticate", "Bearer")
			writeError(w, fail("unauthorized", "valid bearer token required", http.StatusUnauthorized))
			return
		}
		mux.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), botCallerKey, caller.ID)))
	})
}

func (s *Server) botSourceAllowed(remoteAddr string) bool {
	peer, err := netip.ParseAddrPort(remoteAddr)
	if err != nil || peer.Addr().Zone() != "" {
		return false
	}
	addr := peer.Addr().Unmap()
	if len(s.botSources) == 0 {
		return addr.IsLoopback()
	}
	_, ok := s.botSources[addr]
	return ok
}

func (s *Server) matchBotCaller(header string) (botCaller, bool) {
	const prefix = "Bearer "
	if !strings.HasPrefix(header, prefix) {
		return botCaller{}, false
	}
	got := header[len(prefix):]
	var matched botCaller
	ok := false
	for _, caller := range s.botCallers {
		if subtle.ConstantTimeCompare([]byte(got), []byte(caller.Token)) == 1 {
			matched = caller
			ok = true
		}
	}
	return matched, ok
}

func (s *Server) botCaller(r *http.Request) (botCaller, error) {
	id, _ := r.Context().Value(botCallerKey).(string)
	for _, caller := range s.botCallers {
		if caller.ID == id {
			return caller, nil
		}
	}
	return botCaller{}, fail("unauthorized", "bot caller is not bound to this request", http.StatusUnauthorized)
}

func (s *Server) botOwns(w http.ResponseWriter, r *http.Request) (*core.Task, botCaller, bool) {
	caller, err := s.botCaller(r)
	if err != nil {
		writeError(w, err)
		return nil, botCaller{}, false
	}
	task, err := s.task(r.PathValue("id"))
	if err != nil || task.Caller != caller.ID {
		writeError(w, fail("not_found", "task not found", http.StatusNotFound))
		return nil, botCaller{}, false
	}
	return task, caller, true
}

func (s *Server) botProjects(w http.ResponseWriter, r *http.Request) {
	targets, nodes := s.collectTargets(r.Context())
	status := map[string]string{}
	for _, node := range nodes {
		status[node.NodeID] = node.Status
	}
	type targetRef struct {
		NodeID string `json:"nodeId"`
		Ready  bool   `json:"ready"`
		Status string `json:"status"`
	}
	type projectView struct {
		ProjectID string      `json:"projectId"`
		Label     string      `json:"label"`
		Targets   []targetRef `json:"targets"`
	}
	byID := map[string]*projectView{}
	for _, target := range targets {
		view := byID[target.ProjectID]
		if view == nil {
			view = &projectView{ProjectID: target.ProjectID, Label: target.ProjectLabel, Targets: []targetRef{}}
			byID[target.ProjectID] = view
		}
		view.Targets = append(view.Targets, targetRef{target.NodeID, target.Ready, status[target.NodeID]})
	}
	projects := make([]projectView, 0, len(byID))
	for _, view := range byID {
		projects = append(projects, *view)
	}
	sort.Slice(projects, func(i, j int) bool { return projects[i].ProjectID < projects[j].ProjectID })
	writeJSON(w, http.StatusOK, map[string]any{"projects": projects})
}

func (s *Server) botListTasks(w http.ResponseWriter, r *http.Request) {
	caller, err := s.botCaller(r)
	if err != nil {
		writeError(w, err)
		return
	}
	if len(r.URL.Query()) != 0 {
		writeError(w, fail("invalid_query", "bot task list does not accept query parameters", http.StatusBadRequest))
		return
	}
	items := []*core.Task{}
	for _, task := range sortedTasks(s.store.Snapshot()) {
		if task.Caller == caller.ID {
			items = append(items, task)
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"tasks": items})
}

func (s *Server) botGetTask(w http.ResponseWriter, r *http.Request) {
	task, _, ok := s.botOwns(w, r)
	if !ok {
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"task": task})
}

type botCreateInput struct {
	RequestID          string `json:"requestId"`
	Title              string `json:"title"`
	ProjectID          string `json:"projectId,omitempty"`
	NodeID             string `json:"nodeId,omitempty"`
	Repository         string `json:"repository,omitempty"`
	RepositoryID       string `json:"repositoryId,omitempty"`
	Goal               string `json:"goal,omitempty"`
	AcceptanceCriteria string `json:"acceptanceCriteria,omitempty"`
	Plan               string `json:"plan,omitempty"`
}

func (s *Server) botCreateTask(w http.ResponseWriter, r *http.Request) {
	caller, err := s.botCaller(r)
	if err != nil {
		writeError(w, err)
		return
	}
	var in botCreateInput
	if err = decode(w, r, &in); err != nil {
		writeError(w, err)
		return
	}
	if strings.TrimSpace(in.Title) == "" {
		writeError(w, fail("invalid_task", "title is required", http.StatusBadRequest))
		return
	}
	auto := caller.autoStart(in.ProjectID)
	if auto {
		if in.ProjectID == "" || in.NodeID == "" || !validRepository(in.Repository, in.RepositoryID) {
			writeError(w, fail("target_required", "auto-start requires a configured project, node, and canonical repository", http.StatusBadRequest))
			return
		}
		if strings.TrimSpace(in.Plan) == "" && strings.TrimSpace(in.Goal) == "" {
			writeError(w, fail("plan_required", "auto-start requires a plan or a goal", http.StatusBadRequest))
			return
		}
	}
	taskID := taskIDFromRequest(in.RequestID)
	snapshot := s.store.Snapshot()
	if prev := snapshot.Requests[in.RequestID]; prev != nil {
		taskID = prev.TaskID
	}
	var checked *targetPreflight
	if auto && snapshot.Requests[in.RequestID] == nil {
		phantom := &core.Task{ID: taskID, ProjectID: in.ProjectID, NodeID: in.NodeID, Repository: in.Repository, RepositoryID: in.RepositoryID}
		checked = s.preflightTarget(r.Context(), phantom, phantom)
	}
	duplicate, err := s.reserveRequest(in.RequestID, taskID, "bot/create", in, func(st *core.State, req *core.Request) error {
		if strings.TrimSpace(in.Title) == "" {
			return fail("invalid_task", "title is required", http.StatusBadRequest)
		}
		if in.ProjectID != "" && s.cfg.Projects[in.ProjectID] == "" && in.ProjectID != "managed" {
			return fail("unknown_project", "projectId is not configured", http.StatusBadRequest)
		}
		if in.NodeID != "" {
			if _, ok := s.cfg.Nodes[in.NodeID]; !ok {
				return fail("unknown_node", "nodeId is not configured", http.StatusBadRequest)
			}
		}
		now := timeNow()
		t := &core.Task{PlanningProfile: core.RestrictedPlanning, PlanID: taskID, ID: taskID, Title: in.Title, ProjectID: in.ProjectID, Repository: in.Repository, RepositoryID: in.RepositoryID, Goal: in.Goal, AcceptanceCriteria: in.AcceptanceCriteria, NodeID: in.NodeID, Branch: st.Settings.BranchPrefix + taskID, Status: "created", Phase: "architecture", CreatedAt: now, UpdatedAt: now, Settings: st.Settings, ReviewHistory: []core.Review{}, Sessions: map[string]*core.Session{"architect": {ID: core.ID()}}, Budget: core.Budget{}, Caller: caller.ID, Dispatch: "manual"}
		if auto {
			if err := checked.validate(t, t); err != nil {
				return err
			}
			t.Dispatch = "auto"
			t.TargetRevision = 1
			content := strings.TrimSpace(in.Plan)
			if content == "" {
				content = strings.TrimSpace(in.Goal)
			}
			confirmed := timeNow()
			t.Plan = &core.Plan{Revision: 1, Content: content, Source: "bot", ConfirmedAt: &confirmed}
			approved, err := approveInput(t)
			if err != nil {
				return err
			}
			t.Plan.Approved = approved
			expected := 1
			if err := s.prepareExecution(st, t, in.RequestID, 1, false, &expected); err != nil {
				return err
			}
		}
		st.Tasks[t.ID] = t
		req.Status = "completed"
		core.Changed(st, t)
		return nil
	})
	if err != nil {
		writeError(w, err)
		return
	}
	task := s.store.Snapshot().Tasks[taskID]
	if task == nil || task.Caller != caller.ID {
		writeError(w, fail("idempotency_conflict", "requestId belongs to another caller", http.StatusConflict))
		return
	}
	if task.Execution != nil && executionActive(task) {
		s.monitor(task.ID)
	}
	if duplicate {
		s.response(w, in.RequestID)
		return
	}
	s.response(w, in.RequestID)
}

func timeNow() time.Time { return time.Now().UTC() }

func (s *Server) botEvents(w http.ResponseWriter, r *http.Request) {
	if _, _, ok := s.botOwns(w, r); !ok {
		return
	}
	query := r.URL.Query()
	for key := range query {
		if key != "after" && key != "view" {
			writeError(w, fail("invalid_query", "events accept only after and view", http.StatusBadRequest))
			return
		}
	}
	view := query.Get("view")
	if view == "" && r.Header.Get("Accept") == "application/json" {
		view = "snapshot"
	}
	switch view {
	case "", "stream":
		s.events(w, r)
	case "snapshot":
		s.botEventSnapshot(w, r)
	default:
		writeError(w, fail("invalid_query", "view must be stream or snapshot", http.StatusBadRequest))
	}
}

func (s *Server) botEventSnapshot(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	after := int64(0)
	if cursor := r.URL.Query().Get("after"); cursor != "" {
		n, err := strconv.ParseInt(cursor, 10, 64)
		if err != nil || n < 0 {
			writeError(w, fail("invalid_cursor", "after must be a nonnegative integer", http.StatusBadRequest))
			return
		}
		after = n
	}
	replay := s.store.ReplayAfter(id, after)
	reset := after > replay.Sequence || (replay.First > 0 && after > 0 && after < replay.First-1)
	events := replay.Events
	if reset {
		events = []core.Event{{ID: replay.Sequence, Type: "replay.reset", TaskID: id, Time: timeNow(), Data: mustJSON(map[string]any{"reason": "cursor_expired", "reloadNativeMessages": true})}}
		if task := s.store.Snapshot().Tasks[id]; task != nil {
			events = append(events, core.Event{ID: replay.Sequence, Type: "task.updated", TaskID: id, Time: timeNow(), Data: mustJSON(task)})
		}
	}
	if events == nil {
		events = []core.Event{}
	}
	writeJSON(w, http.StatusOK, map[string]any{"events": events, "sequence": replay.Sequence, "reset": reset})
}

func (s *Server) botQuestionReply(w http.ResponseWriter, r *http.Request) {
	if _, _, ok := s.botOwns(w, r); !ok {
		return
	}
	s.executionQuestionReply(w, r)
}

func (s *Server) botCancel(w http.ResponseWriter, r *http.Request) {
	if _, _, ok := s.botOwns(w, r); !ok {
		return
	}
	id := r.PathValue("id")
	cloned := r.Clone(r.Context())
	cloned.URL.Path = "/v1/tasks/" + id + "/execution/cancel"
	cloned.SetPathValue("id", id)
	s.action(w, cloned)
}
