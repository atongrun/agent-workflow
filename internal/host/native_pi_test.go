package host

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"testing"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
	"github.com/atongrun/agent-workflow/internal/pi"
)

// TestNativePiHostIntegration is an opt-in, credential-free integration test of
// the real Pi RPC process. It does not mock Pi, submit a model prompt, or claim
// model/remote-execution E2E coverage. AWF_PI_BINARY must point at an installed
// official Pi CLI (tested with @earendil-works/pi-coding-agent 0.99.2 and 1.0.0).
func TestNativePiHostIntegration(t *testing.T) {
	binary := os.Getenv("AWF_PI_BINARY")
	if binary == "" {
		t.Skip("set AWF_PI_BINARY to an installed official Pi CLI to run native integration")
	}
	binary, err := exec.LookPath(binary)
	if err != nil {
		t.Fatal(err)
	}
	binary, err = filepath.Abs(binary)
	if err != nil {
		t.Fatal(err)
	}
	extension, err := filepath.Abs(filepath.Join("..", "..", "extensions", "awf.ts"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(extension); err != nil {
		t.Fatal(err)
	}

	// Prevent provider credentials, saved auth, user extensions, or Node startup
	// hooks from being used. Preserve only process-launch essentials. t.Setenv
	// records restoration before Unsetenv removes the variable entirely.
	for _, value := range os.Environ() {
		name := strings.SplitN(value, "=", 2)[0]
		switch name {
		case "PATH", "SYSTEMROOT", "SystemRoot", "WINDIR", "PATHEXT", "COMSPEC", "TMPDIR", "TEMP", "TMP":
			continue
		}
		t.Setenv(name, "")
		if err := os.Unsetenv(name); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("HOME", t.TempDir())
	t.Setenv("USERPROFILE", os.Getenv("HOME"))
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	agentDir := t.TempDir()
	t.Setenv("PI_CODING_AGENT_DIR", agentDir)
	diagnosticsDir := t.TempDir()
	t.Setenv("NATIVE_PI_DIAGNOSTIC_DIR", diagnosticsDir)
	t.Setenv("AWF_PARENT_SECRET", "synthetic-parent-secret-must-not-leak")
	t.Setenv("AWF_HOST_URL", "http://parent.invalid")
	t.Setenv("AWF_EXTENSION_TOKEN", "synthetic-parent-extension-token")
	t.Setenv("AWF_TASK_ID", "parent-task")
	t.Setenv("AWF_ROLE", "parent-role")
	if err := os.MkdirAll(filepath.Join(agentDir, "extensions"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(agentDir, "extensions", "awf-native-diagnostics.ts"), []byte(nativePiDiagnosticsExtension), 0600); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	version, err := exec.CommandContext(ctx, binary, "--version").Output()
	if err != nil {
		t.Fatalf("official Pi CLI version: %v", err)
	}
	t.Logf("native Pi version: %s", strings.TrimSpace(string(version)))

	newServer := func(t *testing.T) *Server {
		t.Helper()
		s := testServer(t)
		s.cfg.PiBinary = binary
		s.cfg.PiExtension = extension
		return s
	}

	t.Run("restricted_draft_tools_resources_and_binding_resume", func(t *testing.T) {
		s := newServer(t)
		// Observe public extension APIs through an explicitly trusted test wrapper.
		// Ambient extensions remain disabled; the production extension is unchanged.
		wrapper := filepath.Join(t.TempDir(), "restricted-diagnostics.ts")
		importPath, _ := json.Marshal(extension)
		observational := strings.Replace(nativePiDiagnosticsExtension, "export default function (pi) {", "export default function (pi) { awf(pi);", 1)
		if err := os.WriteFile(wrapper, []byte("import awf from "+string(importPath)+";\n"+observational), 0600); err != nil {
			t.Fatal(err)
		}
		s.cfg.PiExtension = wrapper
		canary := `export default function(pi) { pi.registerCommand("discovered-canary", {description:"must not load",handler:async()=>{}}); }`
		if err := os.WriteFile(filepath.Join(agentDir, "extensions", "ambient-canary.ts"), []byte(canary), 0600); err != nil {
			t.Fatal(err)
		}
		for _, file := range []string{"AGENTS.md", "SYSTEM.md", "APPEND_SYSTEM.md", "prompts/ambient-canary.md", "skills/ambient-canary/SKILL.md"} {
			path := filepath.Join(agentDir, file)
			if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(path, []byte("---\nname: ambient-canary\ndescription: ambient-canary-resource-marker\n---\nambient-canary-resource-marker"), 0600); err != nil {
				t.Fatal(err)
			}
		}
		task := draftTask(t, s, "native-restricted-draft")
		directory, err := s.planningDirectory(task)
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(directory, "AGENTS.md"), []byte("local-canary-context-marker"), 0600); err != nil {
			t.Fatal(err)
		}
		client, err := s.client(task.ID, "architect")
		if err != nil {
			t.Fatal(err)
		}
		initial := nativePiState(t, client)
		check := func(s *Server, c *pi.Client) {
			t.Helper()
			data, err := os.ReadFile(filepath.Join(diagnosticsDir, task.ID+"-architect.json"))
			if err != nil {
				t.Fatal(err)
			}
			var diagnostic struct {
				Args, ActiveTools, LeakedControlEnv []string
				Cwd, SystemPrompt                   string
			}
			nativePiDecode(t, data, &diagnostic)
			sort.Strings(diagnostic.ActiveTools)
			want := []string{"awf_execution", "awf_finish", "awf_plan", "awf_task"}
			if !reflect.DeepEqual(diagnostic.ActiveTools, want) {
				t.Fatalf("restricted native active tools: got %v want %v", diagnostic.ActiveTools, want)
			}
			if diagnostic.Cwd != directory || len(diagnostic.LeakedControlEnv) != 0 {
				t.Fatal("restricted cwd/environment mismatch")
			}
			for _, flag := range []string{"--system-prompt", "--no-extensions", "--no-skills", "--no-prompt-templates", "--no-context-files", "--no-approve", "--tools"} {
				found := false
				for _, arg := range diagnostic.Args {
					if arg == flag {
						found = true
					}
				}
				if !found {
					t.Fatalf("missing native restriction %s", flag)
				}
			}
			if strings.Contains(diagnostic.SystemPrompt, "canary-context-marker") || strings.Contains(diagnostic.SystemPrompt, "canary-resource-marker") {
				t.Fatal("ambient native resources loaded")
			}
			var commands struct {
				Commands []struct{ Name string } `json:"commands"`
			}
			nativePiDecode(t, nativePiCall(t, c, "get_commands", nil), &commands)
			if len(commands.Commands) != 1 || commands.Commands[0].Name != "awf-native-diagnostics" {
				t.Fatalf("discovered command escaped restrictions: %+v", commands.Commands)
			}
			// Real credential-free capability projections. No model prompt or compaction.
			for _, kind := range []string{"commands", "models", "stats"} {
				response := call(t, s, "GET", "/v1/tasks/"+task.ID+"/pi/"+kind+"?role=architect", nil)
				if response.Code != 200 {
					t.Fatalf("native Pi %s projection: %d %s", kind, response.Code, response.Body.String())
				}
				for _, forbidden := range []string{"sourceInfo", "sessionFile", "baseUrl", "headers"} {
					if strings.Contains(response.Body.String(), `"`+forbidden+`"`) {
						t.Fatalf("native %s leaked %s", kind, forbidden)
					}
				}
			}
			currentTask, _ := s.task(task.ID)
			binding := currentTask.Sessions["architect"]
			input := piControlInput{RequestID: core.ID(), Role: "architect", ExpectedSessionID: binding.ID, ExpectedProcessID: binding.ProcessID}
			response := call(t, s, "POST", "/v1/tasks/"+task.ID+"/pi/abort", input)
			if response.Code != 202 {
				t.Fatalf("native idle stop: %s", response.Body.String())
			}
			awaitPiRequest(t, s, input.RequestID, "completed")

		}
		check(s, client)
		task = bindTask(t, s, task, "native-bind")
		same, err := s.client(task.ID, "architect")
		if err != nil || same != client {
			t.Fatal("target binding restarted native Pi")
		}
		if after := nativePiState(t, same); after.SessionID != initial.SessionID || after.SessionFile != initial.SessionFile {
			t.Fatal("binding changed native session identity")
		}
		check(s, same)
		// Restricted sessions still obey the native process cap.
		other := draftTask(t, s, "native-restricted-other")
		if err := s.store.Update(func(st *core.State) error { st.Tasks[task.ID].Sessions["architect"].Busy = true; return nil }); err != nil {
			t.Fatal(err)
		}
		if _, err := s.client(other.ID, "architect"); err == nil {
			t.Fatal("restricted drafts bypassed native process cap")
		}
		if err := s.store.Update(func(st *core.State) error { st.Tasks[task.ID].Sessions["architect"].Busy = false; return nil }); err != nil {
			t.Fatal(err)
		}
		// Persist synthetic history only after the native process has closed.
		s.Close()
		writeNativePiHistoryFixture(t, initial.SessionFile, initial.SessionID, directory)
		reopened, err := New(s.cfg)
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(reopened.Close)
		if err := reopened.store.Update(func(st *core.State) error { st.Tasks[task.ID].Sessions["architect"].Persisted = true; return nil }); err != nil {
			t.Fatal(err)
		}
		resumed, err := reopened.client(task.ID, "architect")
		if err != nil {
			t.Fatal(err)
		}
		state := nativePiState(t, resumed)
		if state.SessionID != initial.SessionID || state.SessionFile != initial.SessionFile || state.MessageCount != 1 {
			t.Fatalf("restricted resume lost native history: %+v", state)
		}
		check(reopened, resumed)
		current, _ := reopened.task(task.ID)
		if current.Execution != nil || current.PlanningProfile != core.RestrictedPlanning || current.TargetRevision != 1 {
			t.Fatal("binding/restart caused execution or profile migration")
		}
	})

	t.Run("role_tools_arguments_and_control_environment", func(t *testing.T) {
		s := newServer(t)
		task := createTask(t, s, "native-role-contract")
		if err := s.store.Update(func(st *core.State) error {
			st.Tasks[task.ID].Sessions["reviewer"] = &core.Session{ID: core.ID()}
			return nil
		}); err != nil {
			t.Fatal(err)
		}
		for _, role := range []string{"architect", "reviewer"} {
			t.Run(role, func(t *testing.T) {
				before, _ := s.task(task.ID)
				expectedID := before.Sessions[role].ID
				client, err := s.client(task.ID, role)
				if err != nil {
					t.Fatalf("start real Pi through Host: %v", err)
				}
				same, err := s.client(task.ID, role)
				if err != nil || same != client {
					t.Fatalf("Host did not reuse live native client: %v", err)
				}
				state := nativePiState(t, client)
				if state.SessionID != expectedID || state.SessionFile == "" || state.IsStreaming || state.PendingMessageCount != 0 || state.MessageCount != 0 {
					t.Fatalf("unexpected new native state: %+v", state)
				}
				if filepath.Dir(state.SessionFile) != filepath.Join(s.cfg.DataDir, "sessions", task.ID, role) {
					t.Fatal("native session escaped the configured per-role session directory")
				}
				stored, _ := s.task(task.ID)
				if stored.Sessions[role].File != state.SessionFile || stored.Sessions[role].ID != state.SessionID || !stored.Sessions[role].Available {
					t.Fatal("Host did not persist the native session reference")
				}
				nativePiCheckDiagnostics(t, s, diagnosticsDir, task.ID, role, expectedID, "")

				var commands struct {
					Commands []struct{ Name, Source string } `json:"commands"`
				}
				nativePiDecode(t, nativePiCall(t, client, "get_commands", nil), &commands)
				found := false
				for _, command := range commands.Commands {
					if command.Name == "awf-native-diagnostics" && command.Source == "extension" {
						found = true
					}
				}
				if !found {
					t.Fatal("native get_commands did not discover the isolated diagnostic extension")
				}
				var messages struct {
					Messages []json.RawMessage `json:"messages"`
				}
				nativePiDecode(t, nativePiCall(t, client, "get_messages", nil), &messages)
				if len(messages.Messages) != 0 {
					t.Fatal("new native role session unexpectedly contains messages")
				}
				var entries struct {
					Entries []struct{ Type string } `json:"entries"`
				}
				nativePiDecode(t, nativePiCall(t, client, "get_entries", nil), &entries)
				for _, entry := range entries.Entries {
					if entry.Type == "message" {
						t.Fatal("new native role session unexpectedly contains message history")
					}
				}
				var queue struct {
					Steering []string `json:"steering"`
					FollowUp []string `json:"followUp"`
				}
				nativePiDecode(t, nativePiCall(t, client, "clear_queue", nil), &queue)
				if queue.Steering == nil || queue.FollowUp == nil || len(queue.Steering)+len(queue.FollowUp) != 0 {
					t.Fatal("native clear_queue did not return empty steering/follow-up arrays")
				}
				nativePiCall(t, client, "abort", nil)
				ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
				defer cancel()
				if err := client.Stop(ctx); err != nil {
					t.Fatalf("Host transport Stop (clear_queue then abort): %v", err)
				}
				if !client.Alive() {
					t.Fatal("aborting an idle native session terminated the process")
				}
				w := call(t, s, "GET", "/v1/tasks/"+task.ID+"/messages?role="+role, nil)
				if w.Code != 200 {
					t.Fatalf("Host native history route: %d %s", w.Code, w.Body.String())
				}
			})
		}
		after, _ := s.task(task.ID)
		if after.Sessions["architect"].ID == after.Sessions["reviewer"].ID || after.Sessions["architect"].File == after.Sessions["reviewer"].File {
			t.Fatal("architect and reviewer native contexts are not isolated")
		}
	})

	t.Run("synthetic_native_history_eviction_and_host_restart", func(t *testing.T) {
		s := newServer(t)
		s.cfg.MaxPiProcesses = 1
		task := createTask(t, s, "native-persistence-contract")
		id := task.Sessions["architect"].ID
		file := filepath.Join(s.cfg.DataDir, "sessions", task.ID, "architect", "synthetic-native-fixture.jsonl")
		writeNativePiHistoryFixture(t, file, id, s.cfg.Projects["p"])
		if err := s.store.Update(func(st *core.State) error {
			st.Tasks[task.ID].Sessions["architect"].File = file
			st.Tasks[task.ID].Sessions["architect"].Persisted = true
			return nil
		}); err != nil {
			t.Fatal(err)
		}
		check := func(s *Server) *pi.Client {
			t.Helper()
			// Require a fresh observation from this process, never a stale file.
			diagnosticFile := filepath.Join(diagnosticsDir, task.ID+"-architect.json")
			if err := os.Remove(diagnosticFile); err != nil && !os.IsNotExist(err) {
				t.Fatal(err)
			}
			client, err := s.client(task.ID, "architect")
			if err != nil {
				t.Fatalf("resume synthetic history with real Pi: %v", err)
			}
			state := nativePiState(t, client)
			if state.SessionID != id || state.SessionFile != file || state.MessageCount != 1 {
				t.Fatalf("native persisted session identity/history changed: %+v", state)
			}
			nativePiCheckDiagnostics(t, s, diagnosticsDir, task.ID, "architect", id, file)
			w := call(t, s, "GET", "/v1/tasks/"+task.ID+"/messages?role=architect", nil)
			if w.Code != 200 {
				t.Fatalf("Host persisted native history: %d %s", w.Code, w.Body.String())
			}
			var result struct {
				Messages []struct {
					Role    string                        `json:"role"`
					Content []struct{ Type, Text string } `json:"content"`
				} `json:"messages"`
				History struct {
					Entries []struct {
						ID, Type, CustomType string
					} `json:"entries"`
					LeafID string `json:"leafId"`
				} `json:"history"`
				Session core.Session `json:"session"`
			}
			nativePiDecode(t, w.Body.Bytes(), &result)
			if len(result.Messages) != 1 || result.Messages[0].Role != "user" || len(result.Messages[0].Content) != 1 || result.Messages[0].Content[0].Text != nativePiSyntheticMessage {
				t.Fatal("Host did not preserve native synthetic message content")
			}
			found := false
			for _, entry := range result.History.Entries {
				if entry.ID == "custom01" && entry.Type == "custom" && entry.CustomType == "awf-native-synthetic-fixture" {
					found = true
				}
			}
			if !found || result.History.LeafID == "" || result.Session.ID != id || !result.Session.Persisted {
				t.Fatal("Host did not preserve native entries, leaf, and persisted session metadata")
			}
			return client
		}
		original := check(s)
		beforeEviction, _ := s.task(task.ID)
		originalProcessID := beforeEviction.Sessions["architect"].ProcessID
		other := createTask(t, s, "native-eviction-other-task")
		otherClient, err := s.client(other.ID, "architect")
		if err != nil {
			t.Fatalf("read another task with one native process slot: %v", err)
		}
		if original.Alive() || !otherClient.Alive() {
			t.Fatal("single-process capacity did not close the idle original native process")
		}
		evicted, _ := s.task(task.ID)
		if evicted.Sessions["architect"].Available || evicted.LastError != "" {
			t.Fatal("intentional idle eviction was recorded as availability or a process failure")
		}
		if state := nativePiState(t, otherClient); state.SessionID != other.Sessions["architect"].ID || state.MessageCount != 0 {
			t.Fatal("the replacement task inherited the original task history")
		}
		replacement := check(s)
		if replacement == original || !replacement.Alive() || otherClient.Alive() {
			t.Fatal("reopening persisted history did not rotate the single native process slot")
		}
		resumed, _ := s.task(task.ID)
		if resumed.Sessions["architect"].ProcessID == originalProcessID || !resumed.Sessions["architect"].Available || resumed.LastError != "" {
			t.Fatal("new native process identity/availability was not retained after idle eviction")
		}
		s.Close()
		reopened, err := New(s.cfg)
		if err != nil {
			t.Fatalf("reopen Host store: %v", err)
		}
		t.Cleanup(reopened.Close)
		live := check(reopened)
		originalBytes, err := os.ReadFile(file)
		if err != nil {
			t.Fatal(err)
		}
		w := lifecycleCall(t, reopened, task.ID, "delete", "native-delete")
		if w.Code != 202 || live.Alive() {
			t.Fatalf("native delete did not close idle Pi: %d %s", w.Code, w.Body)
		}
		if _, err := reopened.client(task.ID, "architect"); err == nil {
			t.Fatal("deleted task restarted Pi")
		}
		if b, err := os.ReadFile(file); err != nil || string(b) != string(originalBytes) {
			t.Fatal("deletion changed native history")
		}
		reopened.Close()
		archived, err := New(s.cfg)
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(archived.Close)
		if archived.store.Snapshot().Tasks[task.ID].DeletedAt == nil {
			t.Fatal("native task lost Trash state on restart")
		}
		if w = lifecycleCall(t, archived, task.ID, "restore", "native-restore"); w.Code != 202 {
			t.Fatal(w.Body)
		}
		if len(archived.clients) != 0 {
			t.Fatal("restore automatically started native Pi")
		}
		check(archived)
	})
}

type nativePiSessionState struct {
	SessionID, SessionFile            string
	IsStreaming                       bool
	MessageCount, PendingMessageCount int
}

func nativePiState(t *testing.T, client *pi.Client) nativePiSessionState {
	t.Helper()
	var state nativePiSessionState
	nativePiDecode(t, nativePiCall(t, client, "get_state", nil), &state)
	return state
}

func nativePiCall(t *testing.T, client *pi.Client, command string, fields map[string]any) json.RawMessage {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	data, err := client.Call(ctx, command, fields)
	if err != nil {
		t.Fatalf("native %s: %v", command, err)
	}
	return data
}

func nativePiDecode(t *testing.T, data []byte, into any) {
	t.Helper()
	if err := json.Unmarshal(data, into); err != nil {
		t.Fatalf("decode native response: %v", err)
	}
}

func nativePiCheckDiagnostics(t *testing.T, s *Server, dir, taskID, role, sessionID, sessionFile string) {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(dir, taskID+"-"+role+".json"))
	if err != nil {
		t.Fatalf("native diagnostic extension was not loaded: %v", err)
	}
	var diagnostic struct {
		Args                                          []string
		Cwd, HostURL, TaskID, Role, ScopedTokenSHA256 string
		AWFEnvNames, Tools, LeakedControlEnv          []string
		LifecycleRevision                             int
	}
	nativePiDecode(t, data, &diagnostic)
	wantArgs := []string{"--mode", "rpc", "--session-dir", filepath.Join(s.cfg.DataDir, "sessions", taskID, role), "--append-system-prompt", "You are participating in one AWF task. Call awf_task to read the task goal, acceptance criteria, current plan and role before planning or reviewing. Architecture uses awf_plan for a structured plan proposal. Only an explicit user Confirm Plan and Start Execution action authorizes remote execution; ordinary conversation does not. Preserve user work. All Git operations belong to agents. The default task uses one Pi for planning and execution results. A separate reviewer exists only when explicitly enabled. Never fabricate artifacts or test evidence."}
	if sessionFile == "" {
		wantArgs = append(wantArgs, "--session-id", sessionID)
	} else {
		wantArgs = append(wantArgs, "--session", sessionFile)
	}
	wantArgs = append(wantArgs, "--extension", s.cfg.PiExtension)
	if !reflect.DeepEqual(diagnostic.Args, wantArgs) {
		t.Fatalf("native argv mismatch:\ngot  %q\nwant %q", diagnostic.Args, wantArgs)
	}
	if diagnostic.Cwd != s.cfg.Projects["p"] || diagnostic.HostURL != s.cfg.InternalURL || diagnostic.TaskID != taskID || diagnostic.Role != role {
		t.Fatal("native process did not receive the configured project/task/role/Host context")
	}
	wantEnv := []string{"AWF_EXTENSION_TOKEN", "AWF_HOST_URL", "AWF_LIFECYCLE_REVISION", "AWF_ROLE", "AWF_TASK_ID"}
	if !reflect.DeepEqual(diagnostic.AWFEnvNames, wantEnv) || len(diagnostic.LeakedControlEnv) != 0 {
		t.Fatal("parent AWF or configured Host/extension/Node control environment leaked into Pi")
	}
	if diagnostic.LifecycleRevision != s.store.Snapshot().Tasks[taskID].LifecycleRevision {
		t.Fatal("native Pi did not receive the immutable task lifecycle generation")
	}
	digest := sha256.Sum256([]byte(s.scopedToken(taskID, role)))
	if diagnostic.ScopedTokenSHA256 != hex.EncodeToString(digest[:]) {
		t.Fatal("native Pi did not receive the exact task-and-role scoped extension token")
	}
	wantTools := []string{"awf_execution", "awf_finish", "awf_plan", "awf_task"}
	if role == "reviewer" {
		wantTools = []string{"awf_review", "awf_task"}
	}
	sort.Strings(diagnostic.Tools)
	if !reflect.DeepEqual(diagnostic.Tools, wantTools) {
		t.Fatalf("real bundled AWF extension tools: got %v, want %v", diagnostic.Tools, wantTools)
	}
}

const nativePiSyntheticMessage = "Synthetic persistence fixture only; this is not model-generated evidence."

func writeNativePiHistoryFixture(t *testing.T, path, sessionID, cwd string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	file, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	// Pi v3 JSONL fixture with a genuine user-message shape and custom entry.
	// Reading/reopening it is performed by the official native SessionManager.
	entries := []any{
		map[string]any{"type": "session", "version": 3, "id": sessionID, "timestamp": "2026-01-01T00:00:00.000Z", "cwd": cwd},
		map[string]any{"type": "message", "id": "user0001", "parentId": nil, "timestamp": "2026-01-01T00:00:01.000Z", "message": map[string]any{"role": "user", "content": []any{map[string]any{"type": "text", "text": nativePiSyntheticMessage}}, "timestamp": 1767225601000}},
		map[string]any{"type": "custom", "id": "custom01", "parentId": "user0001", "timestamp": "2026-01-01T00:00:02.000Z", "customType": "awf-native-synthetic-fixture", "data": map[string]any{"synthetic": true}},
	}
	for _, entry := range entries {
		if err := json.NewEncoder(file).Encode(entry); err != nil {
			t.Fatal(fmt.Errorf("write synthetic Pi history fixture: %w", err))
		}
	}
}

// This observational fixture lives only in t.TempDir. Pi 0.99.2 has no RPC
// get_available_tools command, so its public ExtensionAPI.getAllTools exposes
// the actual loaded tools. No credentials or arbitrary environment values are
// written: only names of leaked synthetic controls and a scoped-token digest.
const nativePiDiagnosticsExtension = `
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { createHash } from "node:crypto";
export default function (pi) {
  pi.registerCommand("awf-native-diagnostics", {
    description: "Credential-free native integration diagnostic fixture",
    handler: async () => {},
  });
  pi.on("session_start", async (_event, ctx) => {
    const taskID = process.env.AWF_TASK_ID;
    const role = process.env.AWF_ROLE;
    const record = {
      args: process.argv.slice(2),
      activeTools: pi.getActiveTools(),
      systemPrompt: ctx.getSystemPrompt(),
      cwd: process.cwd(),
      hostURL: process.env.AWF_HOST_URL,
      taskID, role,
      lifecycleRevision: Number(process.env.AWF_LIFECYCLE_REVISION || "0"),
      scopedTokenSHA256: createHash("sha256").update(process.env.AWF_EXTENSION_TOKEN || "").digest("hex"),
      awfEnvNames: Object.keys(process.env).filter(k => k.startsWith("AWF_")).sort(),
      leakedControlEnv: ["TEST_HOST_TOKEN", "TEST_EXTENSION_TOKEN", "TEST_NODE_TOKEN"].filter(k => k in process.env),
      tools: pi.getAllTools().map(t => t.name).filter(n => n.startsWith("awf_")).sort(),
    };
    writeFileSync(join(process.env.NATIVE_PI_DIAGNOSTIC_DIR, taskID + "-" + role + ".json"), JSON.stringify(record), { mode: 0o600 });
  });
}
`
