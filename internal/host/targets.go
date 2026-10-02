package host

import (
	"context"
	"net/http"
	"os"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
)

type targetView struct {
	ProjectID    string `json:"projectId"`
	NodeID       string `json:"nodeId"`
	ProjectLabel string `json:"projectLabel"`
	NodeLabel    string `json:"nodeLabel"`
	Ready        bool   `json:"ready"`
}
type targetNodeView struct {
	NodeID string `json:"nodeId"`
	Label  string `json:"label"`
	Status string `json:"status"`
}
type nodeProjects struct {
	Available *bool `json:"available"`
	Reachable *bool `json:"reachable"`
	Projects  []struct {
		ProjectID string `json:"projectId"`
		Label     string `json:"label"`
		Ready     bool   `json:"ready"`
	} `json:"projects"`
}

// A health project count never establishes a project mapping. A catalog must
// come from the configured node itself, and no paths or remote errors escape.
func (s *Server) targetCatalog(ctx context.Context, nodeID string) ([]targetView, string) {
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	var catalog nodeProjects
	code, err := s.nodeCall(ctx, nodeID, "GET", "/v1/projects", nil, &catalog)
	if code == http.StatusNotFound || (code >= 200 && code < 300 && err != nil) {
		return nil, "unknown"
	}
	if err != nil {
		return nil, "unavailable"
	}
	if catalog.Available == nil || catalog.Reachable == nil || catalog.Projects == nil {
		return nil, "unknown"
	}
	status := "online"
	if !*catalog.Available || !*catalog.Reachable {
		status = "unavailable"
	}
	targets := []targetView{}
	seen := map[string]bool{}
	for _, p := range catalog.Projects {
		dir, ok := s.cfg.Projects[p.ProjectID]
		if !ok || seen[p.ProjectID] {
			continue
		}
		seen[p.ProjectID] = true
		info, err := os.Stat(dir)
		ready := status == "online" && p.Ready && err == nil && info.IsDir()
		// Configuration keys are stable presentation labels until operators provide
		// dedicated labels. Do not expose host or node filesystem locations.
		targets = append(targets, targetView{p.ProjectID, nodeID, p.ProjectID, nodeID, ready})
	}
	return targets, status
}
func (s *Server) targets(w http.ResponseWriter, r *http.Request) {
	targets := []targetView{}
	nodes := []targetNodeView{}
	var mu sync.Mutex
	var wg sync.WaitGroup
	for id := range s.cfg.Nodes {
		wg.Add(1)
		go func(id string) {
			defer wg.Done()
			found, status := s.targetCatalog(r.Context(), id)
			mu.Lock()
			defer mu.Unlock()
			targets = append(targets, found...)
			nodes = append(nodes, targetNodeView{id, id, status})
		}(id)
	}
	wg.Wait()
	sort.Slice(targets, func(i, j int) bool {
		if targets[i].NodeID == targets[j].NodeID {
			return targets[i].ProjectID < targets[j].ProjectID
		}
		return targets[i].NodeID < targets[j].NodeID
	})
	sort.Slice(nodes, func(i, j int) bool { return nodes[i].NodeID < nodes[j].NodeID })
	writeJSON(w, 200, map[string]any{"targets": targets, "nodes": nodes})
}

// Repository identity is metadata provided by the authenticated application.
// The application must resolve GitHub identity/authorization server-side; the
// Host validates the narrow syntax but never clones, creates, or guesses it.
var repositoryPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}$`)
var repositoryIDPattern = regexp.MustCompile(`^[1-9][0-9]{0,19}$`)

func validRepository(repository, repositoryID string) bool {
	if !repositoryPattern.MatchString(repository) {
		return false
	}
	if repositoryID != "" && !repositoryIDPattern.MatchString(repositoryID) {
		return false
	}
	name := strings.SplitN(repository, "/", 2)[1]
	if name == "." || name == ".." {
		return false
	}
	return true
}
func (s *Server) validateTarget(t *core.Task) error {
	if !validRepository(t.Repository, t.RepositoryID) || t.ProjectID == "" || t.NodeID == "" {
		return fail("target_required", "select an explicit repository and configured execution target", 409)
	}
	if _, ok := s.cfg.Projects[t.ProjectID]; !ok {
		return fail("target_unavailable", "selected project is no longer configured", 409)
	}
	if _, ok := s.cfg.Nodes[t.NodeID]; !ok {
		return fail("target_unavailable", "selected node is no longer configured", 409)
	}
	targets, status := s.targetCatalog(context.Background(), t.NodeID)
	if status != "online" {
		return fail("target_unavailable", "selected node's execution catalog is unavailable; verify its connection and version", 409)
	}
	for _, target := range targets {
		if target.ProjectID == t.ProjectID && target.Ready {
			return nil
		}
	}
	return fail("target_unavailable", "selected node does not have a ready configured workspace for this project", 409)
}
func taskPiIdle(t *core.Task) bool {
	for _, ref := range t.Sessions {
		if ref.Busy || ref.Pending || ref.Streaming || ref.Compacting || ref.AwaitingStart || ref.NativeQueued > 0 || len(ref.PendingCommands) > 0 || len(ref.PendingUI) > 0 {
			return false
		}
	}
	return true
}

type targetInput struct {
	RequestID              string `json:"requestId"`
	ExpectedTargetRevision *int   `json:"expectedTargetRevision"`
	Repository             string `json:"repository"`
	RepositoryID           string `json:"repositoryId,omitempty"`
	ProjectID              string `json:"projectId"`
	NodeID                 string `json:"nodeId"`
}

func (s *Server) updateTarget(w http.ResponseWriter, r *http.Request) {
	var in targetInput
	if err := decode(w, r, &in); err != nil {
		writeError(w, err)
		return
	}
	id := r.PathValue("id")
	_, err := s.reserve(in.RequestID, id, "target", in, func(st *core.State) error {
		t := st.Tasks[id]
		if t == nil {
			return fail("not_found", "task not found", 404)
		}
		if in.ExpectedTargetRevision == nil || *in.ExpectedTargetRevision != t.TargetRevision {
			return fail("target_changed", "reload the current execution target before saving", 409)
		}
		if t.Execution != nil || len(t.ExecutionHistory) > 0 || len(t.CompletionHistory) > 0 || len(t.ReviewHistory) > 0 {
			return fail("target_locked", "execution history fixes this task's target", 409)
		}
		if !taskPiIdle(t) {
			return fail("role_busy", "wait for Pi and its pending dialogs to settle before changing the target", 409)
		}
		if t.PlanningProfile == "" && in.ProjectID != t.ProjectID {
			for _, ref := range t.Sessions {
				if ref.ProcessID != "" || ref.File != "" || ref.Available || ref.Persisted {
					return fail("target_locked", "a legacy native planning session cannot change its workspace", 409)
				}
			}
		}
		candidate := *t
		candidate.ProjectID, candidate.NodeID = in.ProjectID, in.NodeID
		candidate.Repository, candidate.RepositoryID = in.Repository, in.RepositoryID
		if err := s.validateTarget(&candidate); err != nil {
			return err
		}
		t.ProjectID, t.NodeID = in.ProjectID, in.NodeID
		t.Repository, t.RepositoryID = in.Repository, in.RepositoryID
		t.TargetRevision++
		if t.Plan != nil {
			t.Plan.ConfirmedAt = nil
			t.Status = "awaiting_confirmation"
		}
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
