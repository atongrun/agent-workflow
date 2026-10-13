package node

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func gitFixture(t *testing.T) (string, string) {
	t.Helper()
	repo := t.TempDir()
	ctx := context.Background()
	for _, args := range [][]string{{"init"}, {"config", "user.email", "fixture@example.invalid"}, {"config", "user.name", "Fixture"}} {
		if _, err := gitCommand(ctx, repo, args...); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(filepath.Join(repo, "README.md"), []byte("baseline\n"), 0600); err != nil {
		t.Fatal(err)
	}
	for _, args := range [][]string{{"add", "README.md"}, {"commit", "-m", "Fixture baseline"}} {
		if _, err := gitCommand(ctx, repo, args...); err != nil {
			t.Fatal(err)
		}
	}
	sha, err := gitCommand(ctx, repo, "rev-parse", "HEAD")
	if err != nil {
		t.Fatal(err)
	}
	return repo, sha
}
func managedRequest(sha string) JobRequest {
	r := req("managed-one")
	r.TaskID = "task-managed-1"
	r.ProjectID = "managed"
	r.Branch = "awf/" + r.TaskID
	h := sha256.Sum256([]byte(r.Plan))
	r.WorkspaceInput = &WorkspaceInput{RepositoryID: "123", BaseSHA: sha, PlanHash: hex.EncodeToString(h[:])}
	return r
}
func TestManagedWorkspaceRealGitIdempotencyAndPreservesDirtyTree(t *testing.T) {
	repo, sha := gitFixture(t)
	root := t.TempDir()
	r := managedRequest(sha)
	destination := managedTaskPath(root, r.TaskID)
	ctx := context.Background()
	if err := prepareGitWorkspace(ctx, root, r, repo, destination); err != nil {
		t.Fatal(err)
	}
	if err := prepareGitWorkspace(ctx, root, r, repo, destination); err != nil {
		t.Fatalf("exact retry: %v", err)
	}
	if err := os.WriteFile(filepath.Join(destination, "README.md"), []byte("existing user edit\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := prepareGitWorkspace(ctx, root, r, repo, destination); err == nil {
		t.Fatal("dirty first execution accepted")
	}
	data, _ := os.ReadFile(filepath.Join(destination, "README.md"))
	if string(data) != "existing user edit\n" {
		t.Fatal("user changes were modified")
	}
	r.SessionID = "original-session"
	if err := prepareGitWorkspace(ctx, root, r, repo, destination); err != nil {
		t.Fatalf("rework must preserve its existing changes: %v", err)
	}
	r.Repository = "example/other"
	if err := prepareGitWorkspace(ctx, root, r, repo, destination); err == nil {
		t.Fatal("ownership mismatch accepted")
	}
}
func TestManagedRemoteAndCrossPlatformIdentityValidation(t *testing.T) {
	for _, remote := range []string{"https://github.com/Example/Repo.git", "git@github.com:Example/Repo.git", "ssh://git@github.com/Example/Repo"} {
		actual, err := canonicalGithubRemote(remote)
		if err != nil || actual != "example/repo" {
			t.Fatalf("%s: %s %v", remote, actual, err)
		}
	}
	for _, remote := range []string{"https://token@github.com/example/repo", "https://github.com:443/example/repo", "file:///tmp/repo", "https://evil.invalid/example/repo", "ssh://git:password@github.com/example/repo"} {
		if _, err := canonicalGithubRemote(remote); err == nil {
			t.Fatalf("unsafe remote accepted: %s", remote)
		}
	}
	for _, id := range []string{"../escape", "C:\\escape", "CON", "nul", "COM1", "LPT9", "task/other"} {
		r := managedRequest(strings.Repeat("a", 40))
		r.TaskID = id
		r.Branch = "awf/" + id
		if validateWorkspaceInput(r) == nil {
			t.Fatalf("unsafe cross-OS identity accepted: %s", id)
		}
	}
	r := managedRequest(strings.Repeat("a", 40))
	r.Plan = "changed"
	if validateWorkspaceInput(r) == nil {
		t.Fatal("plan digest mismatch accepted")
	}
}
func TestManagedRootRejectsSymlinkAndForeignWorktree(t *testing.T) {
	repo, sha := gitFixture(t)
	root := t.TempDir()
	outside := t.TempDir()
	if err := os.Symlink(outside, filepath.Join(root, "tasks")); err != nil {
		t.Fatal(err)
	}
	r := managedRequest(sha)
	if err := prepareGitWorkspace(context.Background(), root, r, repo, managedTaskPath(root, r.TaskID)); err == nil {
		t.Fatal("symlink root child accepted")
	}
	entries, _ := os.ReadDir(outside)
	if len(entries) != 0 {
		t.Fatal("escaped into external directory")
	}
}
func TestManagedNativeCwdReceiptReplayCancelAndRestart(t *testing.T) {
	repo, sha := gitFixture(t)
	root := t.TempDir()
	r := managedRequest(sha)
	cwd := managedTaskPath(root, r.TaskID)
	if err := prepareGitWorkspace(context.Background(), root, r, repo, cwd); err != nil {
		t.Fatal(err)
	}
	cache := filepath.Join(root, "repos", r.WorkspaceInput.RepositoryID)
	if _, err := gitCommand(context.Background(), cache, "remote", "set-url", "origin", "https://github.com/"+r.Repository+".git"); err != nil {
		t.Fatal(err)
	}
	native := newNative(t, cwd)
	cfg := configFor(t, native)
	cfg.Projects = nil
	cfg.ManagedRoot = root
	s := startNode(t, cfg)
	code, job := call(t, s, "POST", "/v1/jobs", r)
	if code != 202 || job.Workspace != cwd {
		t.Fatalf("managed admission %d %+v", code, job)
	}
	job = waitJob(t, s, job.ID, func(j Job) bool { return j.NativeStatus == "busy" })
	if code, again := call(t, s, "POST", "/v1/jobs", r); code != 200 || again.SessionID != job.SessionID {
		t.Fatal("receipt replay changed session")
	}
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	restored := startNode(t, cfg)
	time.Sleep(30 * time.Millisecond)
	if code, _ := call(t, restored, "POST", "/v1/jobs/"+job.ID+"/cancel", map[string]string{"requestId": "cancel-managed"}); code >= 300 {
		t.Fatalf("cancel %d", code)
	}
	cancelled := waitJob(t, restored, job.ID, func(j Job) bool { return j.Status == "cancelled" })
	if cancelled.Workspace != cwd || cancelled.SessionID != job.SessionID {
		t.Fatal("restart/cancel changed native scope")
	}
	creates, prompts, aborts := native.counts()
	if creates != 1 || prompts != 1 || aborts != 1 {
		t.Fatalf("native calls %d %d %d", creates, prompts, aborts)
	}
}
