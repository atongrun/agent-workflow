package host

import (
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"path"
	"reflect"
	"regexp"
	"sort"
	"strings"
	"unicode/utf8"

	"github.com/atongrun/agent-workflow/internal/core"
)

var sensitiveSourcePath = regexp.MustCompile(`(?i)(^|/)\.env(/|\.|$)|secret|credential|auth\.json`)
var sourceSHA = regexp.MustCompile(`^[a-f0-9]{40}$`)

func validateRepositorySource(source *core.RepositorySource) error {
	if source == nil || !sourceSHA.MatchString(source.BaseSHA) || strings.TrimSpace(source.BaseRef) == "" || len(source.BaseRef) > 256 || strings.ContainsAny(source.BaseRef, "\x00\r\n") || len(source.Files) > 128 {
		return fail("invalid_source", "a bounded fixed-SHA repository source is required", 400)
	}
	total := 0
	for name, content := range source.Files {
		if sensitiveSourcePath.MatchString(name) || name == "" || len(name) > 512 || path.Clean(name) != name || strings.HasPrefix(name, "/") || name == ".." || strings.HasPrefix(name, "../") || strings.ContainsAny(name, "\\\x00") || len(content) > 65536 || !utf8.ValidString(content) || strings.Contains(content, "\x00") {
			return fail("invalid_source", "source paths and text must be bounded repository files", 400)
		}
		total += len(name) + len(content)
	}
	if total > 512*1024 {
		return fail("invalid_source", "repository source exceeds the bounded planning limit", 400)
	}
	return nil
}
func approveInput(t *core.Task) (*core.ApprovedInput, error) {
	if t.RepositorySource == nil {
		if t.ProjectID == "managed" {
			return nil, fail("source_required", "load the repository baseline before confirmation", 409)
		}
		return nil, nil
	}
	if err := validateRepositorySource(t.RepositorySource); err != nil {
		return nil, err
	}
	if t.RepositoryID == "" || t.NodeID == "" || t.ProjectID == "" {
		return nil, fail("target_required", "bind the source to an execution target before confirmation", 409)
	}
	digest := sha256.Sum256([]byte(t.Plan.Content))
	return &core.ApprovedInput{PlanRevision: t.Plan.Revision, PlanContent: t.Plan.Content, PlanHash: hex.EncodeToString(digest[:]), TargetRevision: t.TargetRevision, RepositoryID: t.RepositoryID, Repository: t.Repository, NodeID: t.NodeID, ProjectID: t.ProjectID, Branch: t.Branch, BaseRef: t.RepositorySource.BaseRef, BaseSHA: t.RepositorySource.BaseSHA}, nil
}
func verifyApproval(t *core.Task) error {
	expected, err := approveInput(t)
	if err != nil {
		return err
	}
	if t.Plan.Approved != nil {
		expected.RepositoryReadVerified = t.Plan.Approved.RepositoryReadVerified
	}
	if t.RepositorySource.Truncated && (t.Plan.Approved == nil || !t.Plan.Approved.RepositoryReadVerified) {
		return fail("repository_source_incomplete", "on-demand source access must be verified before confirming a truncated source", 409)
	}
	if t.Plan.Approved == nil || !reflect.DeepEqual(expected, t.Plan.Approved) {
		return fail("approval_changed", "confirm the current plan, repository baseline and target before execution", 409)
	}
	return nil
}

// Uses native Pi tool dispatch; no extra model loop, scheduler or filesystem access.
func (s *Server) readRepositorySource(w http.ResponseWriter, r *http.Request, in extensionInput) {
	t, err := s.task(r.PathValue("id"))
	if err != nil {
		writeError(w, err)
		return
	}
	if r.Header.Get("X-AWF-Role") != "architect" || in.LifecycleRevision != t.LifecycleRevision || t.DeletedAt != nil {
		writeError(w, fail("stale_task_lifecycle", "repository read must belong to this active planning task", 409))
		return
	}
	source := t.RepositorySource
	if source == nil {
		writeError(w, fail("source_unavailable", "bind a fixed repository source before inspecting files", 409))
		return
	}
	operation := in.RepositoryOperation
	if operation == "" {
		if in.Path == "" {
			operation = "list"
		} else {
			operation = "read"
		}
	}
	if operation != "read" && operation != "list" {
		writeError(w, fail("invalid_repository_read", "read or list operation required", 400))
		return
	}
	if source.Truncated || in.Cursor > 0 {
		result, e := s.repositoryBridgeRead(r.Context(), t, operation, in.Path, in.Cursor)
		if e != nil {
			writeError(w, e)
			return
		}
		writeJSON(w, 200, result)
		return
	}
	paths := make([]string, 0, len(source.Files))
	for name := range source.Files {
		paths = append(paths, name)
	}
	sort.Strings(paths)
	result := map[string]any{"repositoryId": t.RepositoryID, "repository": t.Repository, "baseSha": source.BaseSHA, "baseRef": source.BaseRef, "truncated": source.Truncated, "paths": paths, "untrustedSource": true}
	if in.Path != "" {
		content, ok := source.Files[in.Path]
		if !ok {
			writeError(w, fail("file_unavailable", "file is absent from the bounded source bundle; do not infer its contents", 404))
			return
		}
		result["path"], result["content"] = in.Path, content
	}
	writeJSON(w, 200, result)
}

// Checked again inside the confirmation transaction: a delete/restore between
// the outside-lock network probe and admission must invalidate that probe.
func sourcePreflightMatches(t *core.Task, sha string, targetRevision, lifecycleRevision int) bool {
	return t.DeletedAt == nil && t.RepositorySource != nil && sha == t.RepositorySource.BaseSHA && targetRevision == t.TargetRevision && lifecycleRevision == t.LifecycleRevision
}
