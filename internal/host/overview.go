package host

import (
	"context"
	"net/http"
	"sort"
	"time"
)

type agentView struct {
	ID          string     `json:"id"`
	Name        string     `json:"name"`
	Role        string     `json:"role"`
	NodeID      string     `json:"nodeId"`
	Online      bool       `json:"online"`
	CurrentTask string     `json:"currentTask,omitempty"`
	LastSeen    *time.Time `json:"lastSeen,omitempty"`
	Error       string     `json:"error,omitempty"`
}

func (s *Server) agentViews() []agentView {
	items := []agentView{}
	st := s.store.Snapshot()
	roles := []string{"architect"}
	optionalReviewer := st.Settings.Reviewer == "pi"
	for _, task := range st.Tasks {
		if task.DeletedAt != nil {
			continue
		}
		if task.Sessions["reviewer"] != nil {
			optionalReviewer = true
		}
	}
	if optionalReviewer {
		roles = append(roles, "reviewer")
	}
	for _, role := range roles {
		a := agentView{ID: "pi-" + role, Name: "Pi", Role: role, NodeID: "host"}
		s.mu.Lock()
		for _, t := range st.Tasks {
			if t.DeletedAt != nil {
				continue
			}
			if c := s.clients[t.ID+":"+role]; c != nil && c.Alive() {
				a.Online = true
				if ref := t.Sessions[role]; ref != nil && ref.Busy {
					a.CurrentTask = t.ID
				}
			}
		}
		s.mu.Unlock()
		items = append(items, a)
	}
	ids := []string{}
	for id := range s.cfg.Nodes {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	for _, id := range ids {
		a := agentView{ID: "opencode-" + id, Name: "OpenCode", Role: "executor", NodeID: id}
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		var health map[string]any
		_, err := s.nodeCall(ctx, id, "GET", "/v1/health", nil, &health)
		cancel()
		if err == nil {
			a.Online = health["available"] == true && health["reachable"] == true
			if value, ok := health["error"].(string); ok {
				a.Error = value
			}
			now := time.Now().UTC()
			a.LastSeen = &now
		} else {
			a.Error = err.Error()
		}
		for _, t := range st.Tasks {
			if t.DeletedAt != nil {
				continue
			}
			if t.NodeID == id && executionActive(t) {
				a.CurrentTask = t.ID
			}
		}
		items = append(items, a)
	}
	return items
}
func (s *Server) agents(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, 200, map[string]any{"agents": s.agentViews()})
}
func (s *Server) overview(w http.ResponseWriter, r *http.Request) {
	st := s.store.Snapshot()
	writeJSON(w, 200, map[string]any{"tasks": sortedTasks(st), "agents": s.agentViews(), "settings": st.Settings})
}
