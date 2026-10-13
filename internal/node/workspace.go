package node

// This adapter owns only the machine-local Git/cwd boundary. Pi owns planning,
// native tools and durability; no agent scheduler or automatic push is added.
import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

var workspaceID = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`)
var workspaceRepoID = regexp.MustCompile(`^[1-9][0-9]{0,19}$`)
var gitSHA = regexp.MustCompile(`^[a-f0-9]{40}$`)
var planDigest = regexp.MustCompile(`^[a-f0-9]{64}$`)
var githubName = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}$`)

func managedTaskPath(root, id string) string { return filepath.Join(root, "tasks", id) }
func validateWorkspaceInput(req JobRequest) error {
	w := req.WorkspaceInput
	upper := strings.ToUpper(req.TaskID)
	reserved := upper == "CON" || upper == "PRN" || upper == "AUX" || upper == "NUL" || regexp.MustCompile(`^(COM|LPT)[1-9]$`).MatchString(upper)
	if req.ProjectID != "managed" || w == nil || !workspaceID.MatchString(req.TaskID) || reserved || !workspaceRepoID.MatchString(w.RepositoryID) || !gitSHA.MatchString(w.BaseSHA) || !planDigest.MatchString(w.PlanHash) || !githubName.MatchString(req.Repository) || strings.HasSuffix(req.Repository, "/..") || strings.HasSuffix(req.Repository, "/.") {
		return errors.New("invalid managed repository/task identity or pinned commit")
	}
	digest := sha256.Sum256([]byte(req.Plan))
	if hex.EncodeToString(digest[:]) != w.PlanHash {
		return errors.New("approved plan hash does not match execution content")
	}
	if req.Branch != "awf/"+req.TaskID {
		return errors.New("managed tasks use their deterministic awf/taskId branch")
	}
	return nil
}
func canonicalGithubRemote(remote string) (string, error) {
	remote = strings.TrimSpace(remote)
	if strings.HasPrefix(remote, "git@github.com:") {
		remote = "ssh://git@github.com/" + strings.TrimPrefix(remote, "git@github.com:")
	}
	u, err := url.Parse(remote)
	if err != nil || !strings.EqualFold(u.Hostname(), "github.com") || u.Port() != "" || u.RawQuery != "" || u.Fragment != "" || (u.Scheme != "https" && u.Scheme != "ssh") || u.User != nil && (u.Scheme != "ssh" || u.User.Username() != "git") {
		return "", errors.New("repository remote must be canonical GitHub HTTPS or SSH without embedded credentials")
	}
	if u.User != nil {
		if _, set := u.User.Password(); set {
			return "", errors.New("embedded remote credentials are forbidden")
		}
	}
	name := strings.TrimSuffix(strings.TrimPrefix(u.Path, "/"), ".git")
	if !githubName.MatchString(name) {
		return "", errors.New("invalid GitHub remote repository")
	}
	return strings.ToLower(name), nil
}
func gitCommand(ctx context.Context, dir string, args ...string) (string, error) {
	command := exec.CommandContext(ctx, "git", args...)
	command.Dir = dir
	command.Env = append(os.Environ(), "GIT_TERMINAL_PROMPT=0")
	out, err := command.Output()
	if err != nil {
		return "", fmt.Errorf("Git %s failed; inspect local Git authorization and repository state", args[0])
	}
	if len(out) > 1024*1024 {
		return "", errors.New("Git response exceeds verification limit")
	}
	return strings.TrimSpace(string(out)), nil
}
func safeDirectory(root, dir string) error {
	rel, err := filepath.Rel(root, dir)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return errors.New("managed workspace escapes configured root")
	}
	current := root
	for _, part := range strings.Split(rel, string(filepath.Separator)) {
		if part == "." {
			continue
		}
		current = filepath.Join(current, part)
		info, e := os.Lstat(current)
		if os.IsNotExist(e) {
			continue
		}
		if e != nil || info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
			return errors.New("managed path must contain only owned directories, not links or files")
		}
	}
	return nil
}

type workspaceBinding struct{ TaskID, RepositoryID, Repository, Branch, BaseSHA string }

func (s *Server) prepareWorkspace(ctx context.Context, r *record) error {
	if err := validateWorkspaceInput(r.Request); err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(ctx, 2*time.Minute)
	defer cancel()
	return prepareGitWorkspace(ctx, s.cfg.ManagedRoot, r.Request, "https://github.com/"+r.Request.Repository+".git", r.Job.Workspace)
}

// sourceURL is derived from authenticated canonical metadata in production. Local
// fixtures use a local Git repository; no source override is exposed over HTTP.
func prepareGitWorkspace(ctx context.Context, root string, req JobRequest, sourceURL, destination string) error {
	if err := validateWorkspaceInput(req); err != nil {
		return err
	}
	if !sameWorkspace(destination, managedTaskPath(root, req.TaskID)) {
		return errors.New("recorded workspace does not match task-owned path")
	}
	cache := filepath.Join(root, "repos", req.WorkspaceInput.RepositoryID)
	for _, dir := range []string{cache, destination, filepath.Join(root, "bindings")} {
		if err := safeDirectory(root, dir); err != nil {
			return err
		}
	}
	for _, dir := range []string{filepath.Dir(cache), filepath.Dir(destination), filepath.Join(root, "bindings")} {
		if err := os.MkdirAll(dir, 0700); err != nil {
			return err
		}
	}
	binding := workspaceBinding{req.TaskID, req.WorkspaceInput.RepositoryID, req.Repository, req.Branch, req.WorkspaceInput.BaseSHA}
	bindingFile := filepath.Join(root, "bindings", req.TaskID+".json")
	encoded, _ := json.Marshal(binding)
	if info, err := os.Lstat(bindingFile); err == nil && (!info.Mode().IsRegular() || info.Size() > 4096) {
		return errors.New("invalid task ownership record")
	}
	if data, err := os.ReadFile(bindingFile); err == nil {
		var old workspaceBinding
		if json.Unmarshal(data, &old) != nil || old != binding {
			return errors.New("task workspace ownership conflicts with original repository or baseline")
		}
	} else if !os.IsNotExist(err) {
		return err
	} else {
		// Refuse to adopt a pre-existing task directory without our ownership fence.
		if _, e := os.Lstat(destination); e == nil || !os.IsNotExist(e) {
			return errors.New("task directory exists without its original ownership record")
		}
		// Create-only ownership fence; never overwrite a prior task binding.
		f, e := os.OpenFile(bindingFile, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if e != nil {
			return e
		}
		_, e = f.Write(encoded)
		if e == nil {
			e = f.Sync()
		}
		closeErr := f.Close()
		if e != nil {
			return e
		}
		if closeErr != nil {
			return closeErr
		}
	}
	if _, err := os.Stat(cache); os.IsNotExist(err) {
		tmp, e := os.MkdirTemp(filepath.Dir(cache), ".clone-")
		if e != nil {
			return e
		}
		defer os.RemoveAll(tmp)
		if _, e = gitCommand(ctx, root, "clone", "--no-checkout", "--", sourceURL, tmp); e != nil {
			return e
		}
		if e = os.Rename(tmp, cache); e != nil {
			return e
		}
	} else if err != nil {
		return err
	}
	if err := safeDirectory(root, filepath.Join(cache, ".git")); err != nil {
		return err
	}
	remote, err := gitCommand(ctx, cache, "remote", "get-url", "origin")
	if err != nil {
		return err
	}
	// Tests may use local repositories; production sourceURL is always canonical.
	if strings.HasPrefix(sourceURL, "https://github.com/") {
		actual, e := canonicalGithubRemote(remote)
		if e != nil || actual != strings.ToLower(req.Repository) {
			return errors.New("cached Git remote does not match approved repository identity")
		}
	} else if remote != sourceURL {
		return errors.New("fixture remote mismatch")
	}
	sha := req.WorkspaceInput.BaseSHA
	if _, err = gitCommand(ctx, cache, "cat-file", "-e", sha+"^{commit}"); err != nil {
		if _, err = gitCommand(ctx, cache, "fetch", "--no-tags", "origin", sha); err != nil {
			return err
		}
	}
	if _, err = os.Stat(destination); os.IsNotExist(err) {
		if _, err = gitCommand(ctx, cache, "show-ref", "--verify", "--quiet", "refs/heads/"+req.Branch); err == nil {
			head, e := gitCommand(ctx, cache, "rev-parse", req.Branch)
			if e != nil || head != sha {
				return errors.New("existing branch conflicts with approved baseline")
			}
			_, err = gitCommand(ctx, cache, "worktree", "add", "--", destination, req.Branch)
		} else {
			_, err = gitCommand(ctx, cache, "worktree", "add", "-b", req.Branch, "--", destination, sha)
		}
		if err != nil {
			return err
		}
	} else if err != nil {
		return err
	}
	if err = safeDirectory(root, destination); err != nil {
		return err
	}
	common, err := gitCommand(ctx, destination, "rev-parse", "--git-common-dir")
	if err != nil {
		return err
	}
	if !filepath.IsAbs(common) {
		common = filepath.Join(destination, common)
	}
	common, err = filepath.EvalSymlinks(common)
	if err != nil {
		return err
	}
	cacheGit, err := filepath.EvalSymlinks(filepath.Join(cache, ".git"))
	if err != nil {
		return err
	}
	if !sameWorkspace(common, cacheGit) {
		return errors.New("worktree is attached to a different repository cache")
	}
	branch, err := gitCommand(ctx, destination, "symbolic-ref", "--short", "HEAD")
	if err != nil || branch != req.Branch {
		return errors.New("worktree branch differs from approved task branch")
	}
	head, err := gitCommand(ctx, destination, "rev-parse", "HEAD")
	if err != nil {
		return err
	}
	if req.SessionID == "" && head != sha {
		return errors.New("first execution worktree moved from approved baseline")
	}
	if req.SessionID != "" {
		if _, err = gitCommand(ctx, destination, "merge-base", "--is-ancestor", sha, "HEAD"); err != nil {
			return errors.New("rework history does not descend from approved baseline")
		}
	}
	if req.SessionID == "" {
		status, e := gitCommand(ctx, destination, "status", "--porcelain")
		if e != nil || status != "" {
			return errors.New("first execution worktree has existing changes; preserve and reconcile them")
		}
	}
	return nil
}
