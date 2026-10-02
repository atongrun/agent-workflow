package node

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/netip"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/atongrun/agent-workflow/internal/opencode"
)

type project struct {
	id, workspace string
	mu            sync.Mutex
	wake          chan struct{}
	events        *opencode.Events
}
type Server struct {
	cfg          Config
	native       *opencode.Client
	ctx          context.Context
	cancel       context.CancelFunc
	wg           sync.WaitGroup
	mu           sync.Mutex
	projects     map[string]*project
	jobs         map[string]*record
	jobsDir      string
	lock         *os.File
	faultMu      sync.Mutex
	storageError error
	closeOnce    sync.Once

	allowedSources map[netip.Addr]struct{}
}

// JobID lets callers persist the recovery address before sending their POST.
func JobID(requestID string) string {
	sum := sha256.Sum256([]byte(requestID))
	return "job_" + hex.EncodeToString(sum[:])
}
func fingerprint(req JobRequest) string {
	b, _ := json.Marshal(req)
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:])
}
func messageID() (string, error) {
	// Match OpenCode's native sortable timestamp prefix, then cryptographic entropy.
	b := make([]byte, 14)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	const alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
	for i := range b {
		b[i] = alphabet[int(b[i])%len(alphabet)]
	}
	return fmt.Sprintf("msg_%012x%s", (uint64(time.Now().UnixMilli())<<12)&0xffffffffffff, string(b)), nil
}

func New(cfg Config) (http.Handler, error) {
	allowedSources, err := parseAllowedSources(cfg)
	if err != nil {
		return nil, err
	}
	if err := cfg.OpenCodeModel.Validate(); err != nil {
		return nil, err
	}
	if cfg.OpenCodeModel != nil {
		copy := *cfg.OpenCodeModel
		cfg.OpenCodeModel = &copy
	}
	if len(strings.TrimSpace(cfg.Token)) < 24 {
		return nil, errors.New("node bearer token must contain at least 24 characters")
	}
	if cfg.StateDir == "" {
		return nil, errors.New("node stateDir is required")
	}
	if len(cfg.Projects) == 0 {
		return nil, errors.New("at least one explicit project workspace is required")
	}
	if cfg.PollInterval <= 0 {
		cfg.PollInterval = time.Second
	}
	native, err := opencode.New(opencode.Config{URL: cfg.OpenCodeURL, Username: cfg.OpenCodeUsername, Password: cfg.OpenCodePassword, HTTPClient: cfg.HTTPClient})
	if err != nil {
		return nil, err
	}
	s := &Server{cfg: cfg, native: native, projects: map[string]*project{}, jobs: map[string]*record{}, allowedSources: allowedSources}
	for id, path := range cfg.Projects {
		if strings.TrimSpace(id) == "" || !filepath.IsAbs(path) {
			return nil, errors.New("project IDs must be nonempty and workspaces must be absolute existing directories")
		}
		clean, err := filepath.EvalSymlinks(filepath.Clean(path))
		if err != nil {
			return nil, fmt.Errorf("workspace %s: %w", id, err)
		}
		st, err := os.Stat(clean)
		if err != nil {
			return nil, err
		}
		if !st.IsDir() {
			return nil, fmt.Errorf("workspace %s is not a directory", id)
		}
		for _, p := range s.projects {
			if overlaps(clean, p.workspace) {
				return nil, fmt.Errorf("projects %s and %s have overlapping workspaces", id, p.id)
			}
		}
		s.projects[id] = &project{id: id, workspace: clean, wake: make(chan struct{}, 1)}
	}
	state, err := filepath.Abs(cfg.StateDir)
	if err != nil {
		return nil, err
	}
	s.jobsDir = filepath.Join(state, "jobs")
	if err = os.MkdirAll(s.jobsDir, 0700); err != nil {
		return nil, err
	}
	s.lock, err = lockState(filepath.Join(state, "node.lock"))
	if err != nil {
		return nil, err
	}
	if err = s.load(); err != nil {
		s.lock.Close()
		return nil, err
	}
	s.ctx, s.cancel = context.WithCancel(context.Background())
	for _, p := range s.projects {
		s.wg.Add(1)
		go s.run(p)
	}
	return s, nil
}
func overlaps(a, b string) bool {
	rel, err := filepath.Rel(a, b)
	if err == nil && (rel == "." || (rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator)))) {
		return true
	}
	rel, err = filepath.Rel(b, a)
	return err == nil && (rel == "." || (rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator))))
}

// Close stops polling without aborting native sessions; restarting reconciles them.
func (s *Server) Close() error {
	var err error
	s.closeOnce.Do(func() { s.cancel(); s.wg.Wait(); err = s.lock.Close() })
	return err
}
func (s *Server) fault() error { s.faultMu.Lock(); defer s.faultMu.Unlock(); return s.storageError }
func (s *Server) wake(p *project) {
	select {
	case p.wake <- struct{}{}:
	default:
	}
}
func (s *Server) run(p *project) {
	defer s.wg.Done()
	ticker := time.NewTicker(s.cfg.PollInterval)
	defer ticker.Stop()
	s.wake(p)
	for {
		select {
		case <-s.ctx.Done():
			return
		case <-p.wake:
		case <-ticker.C:
		}
		if s.ctx.Err() != nil {
			return
		}
		p.mu.Lock()
		if s.fault() == nil {
			if r := s.next(p); r != nil {
				s.advance(s.ctx, p, r)
			}
		}
		p.mu.Unlock()
	}
}
func (s *Server) next(p *project) *record {
	s.mu.Lock()
	defer s.mu.Unlock()
	var candidates []*record
	for _, r := range s.jobs {
		if r.Job.ProjectID == p.id && !terminal(r.Job.Status) {
			candidates = append(candidates, r)
		}
	}
	sort.Slice(candidates, func(i, j int) bool {
		if candidates[i].Job.CreatedAt.Equal(candidates[j].Job.CreatedAt) {
			return candidates[i].Job.ID < candidates[j].Job.ID
		}
		return candidates[i].Job.CreatedAt.Before(candidates[j].Job.CreatedAt)
	})
	if len(candidates) > 0 {
		return candidates[0]
	}
	return nil
}
func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if !s.sourceAllowed(r.RemoteAddr) {
		writeError(w, http.StatusForbidden, "source_denied", "source address is not allowed")
		return
	}
	if subtle.ConstantTimeCompare([]byte(r.Header.Get("Authorization")), []byte("Bearer "+s.cfg.Token)) != 1 {
		w.Header().Set("WWW-Authenticate", "Bearer")
		writeError(w, 401, "unauthorized", "valid bearer authorization is required")
		return
	}
	if r.URL.Path == "/v1/health" && r.Method == "GET" {
		s.health(w, r)
		return
	}
	if r.URL.Path == "/v1/projects" && r.Method == "GET" {
		s.projectCatalog(w, r)
		return
	}
	if r.URL.Path == "/v1/jobs" && r.Method == "POST" {
		s.submit(w, r)
		return
	}
	if strings.HasPrefix(r.URL.Path, "/v1/jobs/") {
		bits := strings.Split(strings.TrimPrefix(r.URL.Path, "/v1/jobs/"), "/")
		if len(bits) == 1 && r.Method == "GET" {
			s.get(w, r, bits[0])
			return
		}
		if len(bits) == 2 && bits[1] == "cancel" && r.Method == "POST" {
			s.cancelJob(w, r, bits[0])
			return
		}
	}
	writeError(w, 404, "not_found", "route not found")
}
func decode(w http.ResponseWriter, r *http.Request, v any) bool {
	r.Body = http.MaxBytesReader(w, r.Body, 2<<20)
	d := json.NewDecoder(r.Body)
	d.DisallowUnknownFields()
	if err := d.Decode(v); err != nil {
		writeError(w, 400, "invalid_json", err.Error())
		return false
	}
	if err := d.Decode(new(any)); err != io.EOF {
		writeError(w, 400, "invalid_json", "expected exactly one JSON object")
		return false
	}
	return true
}
func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
func writeError(w http.ResponseWriter, status int, code, msg string) {
	writeJSON(w, status, map[string]any{"error": map[string]string{"code": code, "message": msg}})
}
func (s *Server) health(w http.ResponseWriter, r *http.Request) {
	h, err := s.native.Health(r.Context())
	out := map[string]any{"available": s.fault() == nil, "reachable": err == nil && h.Healthy, "version": h.Version, "projects": len(s.projects)}
	if err != nil {
		out["error"] = err.Error()
	}
	if e := s.fault(); e != nil {
		out["error"] = e.Error()
	}
	writeJSON(w, 200, out)
}
func (s *Server) lookup(id string) (*record, *project) {
	s.mu.Lock()
	defer s.mu.Unlock()
	j := s.jobs[id]
	if j == nil {
		return nil, nil
	}
	return j, s.projects[j.Job.ProjectID]
}
func (s *Server) submit(w http.ResponseWriter, r *http.Request) {
	var req JobRequest
	if !decode(w, r, &req) {
		return
	}
	if strings.TrimSpace(req.RequestID) == "" || len(req.RequestID) > 256 || strings.TrimSpace(req.TaskID) == "" || strings.TrimSpace(req.ProjectID) == "" || strings.TrimSpace(req.Prompt) == "" {
		writeError(w, 400, "invalid_request", "requestId (at most 256 characters), taskId, projectId and prompt are required")
		return
	}
	if req.TimeoutSeconds == 0 {
		req.TimeoutSeconds = 3600
	}
	if req.TimeoutSeconds < 1 || req.TimeoutSeconds > 3600 {
		writeError(w, 400, "invalid_timeout", "timeoutSeconds must be between 1 and 3600")
		return
	}
	p := s.projects[req.ProjectID]
	if p == nil {
		writeError(w, 403, "workspace_denied", "project has no configured workspace")
		return
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	id := JobID(req.RequestID)
	s.mu.Lock()
	existing := s.jobs[id]
	s.mu.Unlock()
	if existing != nil {
		if existing.Fingerprint != fingerprint(req) {
			writeError(w, 409, "request_conflict", "requestId was already used with different content")
			return
		}
		writeJSON(w, 200, existing.Job)
		return
	}
	if err := s.fault(); err != nil {
		writeError(w, 503, "storage_unavailable", err.Error())
		return
	}

	owned, existingSession, identityConflict := false, false, false
	s.mu.Lock()
	for _, old := range s.jobs {
		if old.Job.ProjectID != req.ProjectID || old.Job.TaskID != req.TaskID {
			continue
		}
		if old.Job.SessionID != "" || !terminal(old.Job.Status) {
			existingSession = true
		}
		if req.SessionID != "" && old.Job.SessionID == req.SessionID {
			owned = true
			if old.Job.Repository != req.Repository || old.Job.Branch != req.Branch {
				identityConflict = true
			}
		}
	}
	s.mu.Unlock()
	if req.SessionID == "" && existingSession {
		writeError(w, 409, "session_required", "this task already has execution history; reconcile and explicitly reuse its original native session")
		return
	}
	if req.SessionID != "" && !owned {
		writeError(w, 409, "session_not_owned", "sessionId must belong to this task and project in durable node history")
		return
	}
	if identityConflict {
		writeError(w, 409, "session_identity_conflict", "rework must preserve the task repository and branch")
		return
	}

	mid, err := messageID()
	if err != nil {
		writeError(w, 500, "identity_error", err.Error())
		return
	}
	var model *opencode.ModelSelection
	if s.cfg.OpenCodeModel != nil {
		copy := *s.cfg.OpenCodeModel
		model = &copy
	}
	now := time.Now().UTC()
	rec := &record{Version: 1, Request: req, Fingerprint: fingerprint(req), SessionTitle: "AWF " + id, Job: Job{Model: model, ID: id, RequestID: req.RequestID, TaskID: req.TaskID, ProjectID: req.ProjectID, Repository: req.Repository, Branch: req.Branch, Workspace: p.workspace, SessionID: req.SessionID, MessageID: mid, Status: "queued", SubmissionState: "queued", CreatedAt: now, UpdatedAt: now, TimeoutSeconds: req.TimeoutSeconds, Evidence: []Evidence{}}}
	s.mu.Lock()
	if old := s.jobs[id]; old != nil {
		s.mu.Unlock()
		writeError(w, 409, "request_conflict", "requestId was concurrently used for another project")
		return
	}
	s.jobs[id] = rec
	s.mu.Unlock()
	if err = s.persist(rec); err != nil {
		writeError(w, 503, "storage_unavailable", err.Error())
		return
	}
	writeJSON(w, 202, rec.Job)
	s.wake(p)
}
func (s *Server) get(w http.ResponseWriter, r *http.Request, id string) {
	rec, p := s.lookup(id)
	if rec == nil {
		writeError(w, 404, "job_not_found", "job not found")
		return
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	if !terminal(rec.Job.Status) && rec.Job.SubmissionState != "queued" && s.fault() == nil {
		s.reconcile(r.Context(), p, rec)
	}
	writeJSON(w, 200, rec.Job)
	s.wake(p)
}
func (s *Server) cancelJob(w http.ResponseWriter, r *http.Request, id string) {
	var req struct {
		RequestID string `json:"requestId"`
	}
	if !decode(w, r, &req) {
		return
	}
	if strings.TrimSpace(req.RequestID) == "" || len(req.RequestID) > 256 {
		writeError(w, 400, "invalid_request", "requestId is required and must be at most 256 characters")
		return
	}
	rec, p := s.lookup(id)
	if rec == nil {
		writeError(w, 404, "job_not_found", "job not found")
		return
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	if terminal(rec.Job.Status) {
		writeJSON(w, 200, rec.Job)
		return
	}
	if err := s.fault(); err != nil {
		writeError(w, 503, "storage_unavailable", err.Error())
		return
	}
	rec.CancelRequestID = req.RequestID
	rec.Job.CancelRequested = true
	if rec.CancelPhase == "" {
		rec.CancelPhase = "pending"
	}
	rec.Job.Status = "cancelling"
	if err := s.persist(rec); err != nil {
		writeError(w, 503, "storage_unavailable", err.Error())
		return
	}
	// Cancelling a queued job never touches another job's shared native session.
	if rec.Job.SubmissionState == "queued" || rec.Job.SubmissionState == "creating" || rec.Job.SubmissionState == "ready" {
		s.finish(rec, "cancelled")
		_ = s.persist(rec)
	} else {
		s.reconcile(r.Context(), p, rec)
		if !terminal(rec.Job.Status) {
			s.abort(r.Context(), p, rec)
		}
	}
	writeJSON(w, 200, rec.Job)
	s.wake(p)
}

// Only configured identities are advertised; workspaces and native credentials
// remain local to the node. Source and bearer guards apply before this handler.
func (s *Server) projectCatalog(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	h, err := s.native.Health(ctx)
	available := s.fault() == nil
	reachable := err == nil && h.Healthy
	type projectView struct {
		ProjectID string `json:"projectId"`
		Label     string `json:"label"`
		Ready     bool   `json:"ready"`
	}
	projects := []projectView{}
	for id, p := range s.projects {
		info, err := os.Stat(p.workspace)
		projects = append(projects, projectView{id, id, available && reachable && err == nil && info.IsDir()})
	}
	sort.Slice(projects, func(i, j int) bool { return projects[i].ProjectID < projects[j].ProjectID })
	writeJSON(w, 200, map[string]any{"available": available, "reachable": reachable, "projects": projects})
}
