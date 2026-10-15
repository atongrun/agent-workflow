package node

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// Runtime and offline inspection share exactly the same canonical workspace
// identities, including the reserved managed project. No I/O creates a workspace.
func (s *Server) configureProjects() error {
	for id, path := range s.cfg.Projects {
		if strings.TrimSpace(id) == "" || !filepath.IsAbs(path) {
			return errors.New("project IDs must be nonempty and workspaces must be absolute existing directories")
		}
		clean, err := filepath.EvalSymlinks(filepath.Clean(path))
		if err != nil {
			return fmt.Errorf("workspace %s: %w", id, err)
		}
		st, err := os.Stat(clean)
		if err != nil {
			return err
		}
		if !st.IsDir() {
			return fmt.Errorf("workspace %s is not a directory", id)
		}
		for _, p := range s.projects {
			if overlaps(clean, p.workspace) {
				return fmt.Errorf("projects %s and %s have overlapping workspaces", id, p.id)
			}
		}
		s.projects[id] = &project{id: id, workspace: clean, wake: make(chan struct{}, 1)}
	}
	if s.cfg.ManagedRoot != "" {
		if !filepath.IsAbs(s.cfg.ManagedRoot) {
			return errors.New("managedRoot must be absolute")
		}
		root, err := filepath.EvalSymlinks(s.cfg.ManagedRoot)
		if err != nil {
			return errors.New("managedRoot must be an existing directory")
		}
		info, err := os.Stat(root)
		if err != nil || !info.IsDir() {
			return errors.New("managedRoot must be a directory")
		}
		for _, p := range s.projects {
			if overlaps(root, p.workspace) {
				return errors.New("managedRoot must not overlap configured workspaces")
			}
		}
		if s.projects["managed"] != nil {
			return errors.New("managed is a reserved project ID")
		}
		s.cfg.ManagedRoot = root
		s.projects["managed"] = &project{id: "managed", workspace: root, managed: true, wake: make(chan struct{}, 1)}
	}
	return nil
}
