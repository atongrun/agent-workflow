package host

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
)

// A subprocess transport fixture, not a mock of any model-backed result. The
// separate opt-in integration test uses the installed official Pi executable.
func TestPiControlHelper(t *testing.T) {
	if os.Getenv("PI_CONTROL_TEST_HELPER") != "1" {
		return
	}
	sessionID := "helper-session"
	for i, a := range os.Args {
		if a == "--session-id" && i+1 < len(os.Args) {
			sessionID = os.Args[i+1]
		}
	}
	var mu sync.Mutex
	model := piModel{"test", "one", "One"}
	for i, a := range os.Args {
		if i+1 >= len(os.Args) {
			continue
		}
		if a == "--model" {
			model.ID = os.Args[i+1]
		}
		if a == "--session" {
			var history struct {
				SessionID string  `json:"sessionId"`
				ID        string  `json:"id"`
				Model     piModel `json:"model"`
			}
			if b, err := os.ReadFile(os.Args[i+1]); err == nil && json.Unmarshal(b, &history) == nil {
				if history.SessionID == "" {
					history.SessionID = history.ID
				}
				sessionID, model = history.SessionID, history.Model
			}
		}
	}
	compacting := false
	var compactID string
	output := func(value any) { b, _ := json.Marshal(value); fmt.Println(string(b)) }
	response := func(id, typ string, data any) {
		output(map[string]any{"id": id, "type": "response", "command": typ, "success": true, "data": data})
	}
	logPath := os.Getenv("PI_CONTROL_TEST_LOG")
	release := os.Getenv("PI_CONTROL_TEST_RELEASE")
	mode := os.Getenv("PI_CONTROL_TEST_MODE")
	if f, err := os.OpenFile(logPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600); err == nil {
		encoded, _ := json.Marshal(map[string]any{"args": os.Args, "agentDir": os.Getenv("PI_CODING_AGENT_DIR")})
		fmt.Fprintln(f, string(encoded))
		f.Close()
	}
	scanner := bufio.NewScanner(os.Stdin)
	for scanner.Scan() {
		var in map[string]any
		if json.Unmarshal(scanner.Bytes(), &in) != nil {
			continue
		}
		id, _ := in["id"].(string)
		typ, _ := in["type"].(string)
		f, _ := os.OpenFile(logPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
		if f != nil {
			fmt.Fprintln(f, typ)
			f.Close()
		}
		mu.Lock()
		switch typ {
		case "get_state":
			if mode == "hold_state" {
				for {
					if _, err := os.Stat(release); err == nil {
						break
					}
					time.Sleep(5 * time.Millisecond)
				}
			}
			response(id, typ, map[string]any{"sessionId": sessionID, "sessionFile": "/private/native.jsonl", "model": map[string]any{"provider": model.Provider, "id": model.ID, "name": model.Name, "headers": map[string]string{"Authorization": "hidden-model-secret"}, "baseUrl": "https://private.invalid"}, "isStreaming": false, "isCompacting": compacting, "pendingMessageCount": 0})
		case "get_commands":
			if mode == "no_commands" {
				response(id, typ, map[string]any{"commands": []any{}})
				break
			}
			response(id, typ, map[string]any{"commands": []any{map[string]any{"name": "hello", "description": "A native command", "source": "extension", "sourceInfo": map[string]string{"path": "hidden-source-path"}}, map[string]any{"name": "skill:check", "source": "skill"}, map[string]any{"name": "draft", "source": "prompt"}, map[string]any{"name": "settings", "source": "tui"}, map[string]any{"name": "bad\nname", "source": "extension"}}})
		case "get_available_models":
			response(id, typ, map[string]any{"models": []any{map[string]any{"provider": "test", "id": "one", "name": "One", "headers": map[string]string{"Authorization": "hidden-model-secret"}, "baseUrl": "https://private.invalid"}, map[string]any{"provider": "test", "id": "two", "name": "Two"}}})
		case "get_session_stats":
			response(id, typ, map[string]any{"sessionId": sessionID, "sessionFile": "hidden-stats-path", "userMessages": 2, "assistantMessages": 2, "tokens": map[string]int{"input": 12, "output": 8, "total": 20}, "cost": 0.02, "contextUsage": map[string]any{"tokens": nil, "percent": nil, "contextWindow": 200000}})
		case "set_model":
			if mode == "crash_model" {
				os.Exit(0)
			}
			if in["provider"] != "test" || (in["modelId"] != "one" && in["modelId"] != "two") {
				output(map[string]any{"id": id, "type": "response", "success": false, "error": "hidden-provider-error"})
				break
			}
			if mode == "wrong_model_response" {
				response(id, typ, model)
				break
			}
			if mode == "wrong_model_state" {
				response(id, typ, piModel{"test", in["modelId"].(string), "Selected"})
				break
			}
			if mode == "hold_model" {
				next := in["modelId"].(string)
				go func(id, next string) {
					for {
						if _, e := os.Stat(release); e == nil {
							break
						}
						time.Sleep(5 * time.Millisecond)
					}
					mu.Lock()
					defer mu.Unlock()
					model = piModel{"test", next, "Selected"}
					response(id, "set_model", model)
				}(id, next)
			} else {
				model = piModel{"test", in["modelId"].(string), "Selected"}
				response(id, typ, model)
			}
		case "compact":
			compacting = true
			compactID = id
			output(map[string]any{"type": "compaction_start", "reason": "manual"})
		case "clear_queue":
			response(id, typ, map[string]any{"steering": []string{}, "followUp": []string{"native queued text"}})
		case "abort":
			if compacting {
				compacting = false
				output(map[string]any{"type": "compaction_end", "reason": "manual", "aborted": true})
				output(map[string]any{"id": compactID, "type": "response", "success": false, "error": "Compaction cancelled"})
			}
			response(id, typ, nil)
		case "prompt":
			response(id, typ, map[string]string{"disposition": "handled"})
		case "get_messages":
			response(id, typ, map[string]any{"messages": []any{}})
		case "get_entries":
			response(id, typ, map[string]any{"entries": []any{}, "leafId": nil})
		default:
			output(map[string]any{"id": id, "type": "response", "success": false, "error": "unsupported fixture method"})
		}
		mu.Unlock()
	}
	os.Exit(0)
}
func piControlFixture(t *testing.T, mode string) (*Server, *core.Task, piControlInput, string, string) {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("subprocess fixture uses a POSIX launcher")
	}
	s := testServer(t)
	s.cfg.PiProvider = "test"
	writeModelCatalog(t, s, "test", []string{"one", "two", "missing"})
	if err := s.store.Update(func(st *core.State) error {
		st.Settings.PiDefaultModel = core.PiModel{Provider: "test", ID: "one"}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	task := createTask(t, s, "pi-control-task")
	dir := t.TempDir()
	log := filepath.Join(dir, "rpc.log")
	release := filepath.Join(dir, "release")
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	script := fmt.Sprintf("#!/bin/sh\nexport PI_CONTROL_TEST_HELPER=1\nexport PI_CONTROL_TEST_LOG='%s'\nexport PI_CONTROL_TEST_RELEASE='%s'\nexport PI_CONTROL_TEST_MODE='%s'\nexec '%s' -test.run=TestPiControlHelper -- \"$@\"\n", log, release, mode, executable)
	launcher := filepath.Join(dir, "pi")
	if err = os.WriteFile(launcher, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	s.cfg.PiBinary = launcher
	if _, err = s.client(task.ID, "architect"); err != nil {
		t.Fatal(err)
	}
	task, _ = s.task(task.ID)
	ref := task.Sessions["architect"]
	return s, task, piControlInput{RequestID: "control", Role: "architect", ExpectedSessionID: ref.ID, ExpectedProcessID: ref.ProcessID}, log, release
}
func piMethods(t *testing.T, path string) []string {
	t.Helper()
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return strings.Fields(string(b))
}
func methodCount(t *testing.T, path, method string) int {
	count := 0
	for _, m := range piMethods(t, path) {
		if m == method {
			count++
		}
	}
	return count
}
func awaitPiRequest(t *testing.T, s *Server, id string, statuses ...string) *core.Request {
	t.Helper()
	until := time.Now().Add(5 * time.Second)
	for time.Now().Before(until) {
		if req := s.store.Snapshot().Requests[id]; req != nil {
			for _, want := range statuses {
				if req.Status == want {
					return req
				}
			}
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatalf("request %s did not reach %v: %+v", id, statuses, s.store.Snapshot().Requests[id])
	return nil
}
func TestPiReadsProjectOnlyExplicitCapabilities(t *testing.T) {
	s, task, _, log, _ := piControlFixture(t, "")
	for _, kind := range []string{"commands", "models", "stats"} {
		w := call(t, s, "GET", "/v1/tasks/"+task.ID+"/pi/"+kind+"?role=architect", nil)
		if w.Code != 200 {
			t.Fatalf("%s: %d %s", kind, w.Code, w.Body.String())
		}
		for _, secret := range []string{"hidden-", "private.invalid", "sourceInfo", "sessionFile", "baseUrl", "headers", "settings", "bad\\nname"} {
			if strings.Contains(w.Body.String(), secret) {
				t.Fatalf("%s leaked %s: %s", kind, secret, w.Body.String())
			}
		}
		if kind == "commands" && !strings.Contains(w.Body.String(), `"skill:check"`) {
			t.Fatal("native skill name changed")
		}
		if kind == "stats" && !strings.Contains(w.Body.String(), `"tokens":null`) {
			t.Fatal("unknown context tokens became zero")
		}
	}
	for _, query := range []string{"", "?role=other", "?role=architect&role=reviewer", "?role=architect&rpc=bash"} {
		if w := call(t, s, "GET", "/v1/tasks/"+task.ID+"/pi/commands"+query, nil); w.Code != 400 {
			t.Fatalf("query accepted: %s", query)
		}
	}
	for _, method := range []string{"prompt", "set_model", "compact", "abort"} {
		if methodCount(t, log, method) != 0 {
			t.Fatalf("read dispatched %s", method)
		}
	}
	s.Close()
	if w := call(t, s, "GET", "/v1/tasks/"+task.ID+"/pi/commands?role=architect", nil); w.Code != 409 {
		t.Fatalf("read started dead process: %d %s", w.Code, w.Body.String())
	}
}
func TestPiModelDurableReceiptBindingAndReplay(t *testing.T) {
	s, task, in, log, _ := piControlFixture(t, "")
	in.Provider = "test"
	in.ModelID = "two"
	path := "/v1/tasks/" + task.ID + "/pi/model"
	var wg sync.WaitGroup
	for range 8 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if w := call(t, s, "POST", path, in); w.Code != 202 {
				t.Errorf("model: %d %s", w.Code, w.Body.String())
			}
		}()
	}
	wg.Wait()
	req := awaitPiRequest(t, s, in.RequestID, "completed")
	if !req.Dispatched || req.ProcessID != in.ExpectedProcessID || !strings.Contains(string(req.Result), `"two"`) {
		t.Fatalf("receipt missing binding/result: %+v", req)
	}
	if methodCount(t, log, "set_model") != 1 {
		t.Fatal("duplicate model mutation")
	}
	_ = s.store.Update(func(st *core.State) error {
		st.Tasks[task.ID].Sessions["architect"].ProcessID = "replacement"
		return nil
	})
	if w := call(t, s, "POST", path, in); w.Code != 202 {
		t.Fatal("original receipt lost after process change")
	}
	in.RequestID = "new-request"
	if w := call(t, s, "POST", path, in); w.Code != 409 {
		t.Fatal("stale control dispatched")
	}
	in.RequestID = "control"
	in.ModelID = "one"
	if w := call(t, s, "POST", path, in); w.Code != 409 || !strings.Contains(w.Body.String(), "idempotency_conflict") {
		t.Fatal("changed duplicate did not conflict first")
	}
	if w := call(t, s, "GET", "/v1/tasks/"+task.ID+"/requests/control", nil); w.Code != 200 {
		t.Fatal("receipt unavailable")
	}
	if w := call(t, s, "GET", "/v1/tasks/other/requests/control", nil); w.Code != 404 {
		t.Fatal("receipt escaped task scope")
	}
}
func TestPiControlRejectsBusyAndMalformedRequests(t *testing.T) {
	s, task, in, log, _ := piControlFixture(t, "")
	path := "/v1/tasks/" + task.ID + "/pi/compact"
	for _, change := range []func(*core.Session){func(r *core.Session) { r.Busy = true }, func(r *core.Session) { r.Pending = true }, func(r *core.Session) { r.NativeQueued = 1 }, func(r *core.Session) { r.PendingUI = []json.RawMessage{json.RawMessage(`{"id":"dialog"}`)} }} {
		_ = s.store.Update(func(st *core.State) error {
			r := st.Tasks[task.ID].Sessions["architect"]
			r.Busy = false
			r.Pending = false
			r.NativeQueued = 0
			r.PendingUI = nil
			change(r)
			return nil
		})
		if w := call(t, s, "POST", path, in); w.Code != 409 {
			t.Fatalf("busy compact accepted: %s", w.Body.String())
		}
	}
	_ = s.store.Update(func(st *core.State) error {
		r := st.Tasks[task.ID].Sessions["architect"]
		r.PendingUI = nil
		return nil
	})
	bad := in
	bad.ExpectedProcessID = ""
	if w := call(t, s, "POST", path, bad); w.Code != 409 {
		t.Fatal("missing binding accepted")
	}
	if w := call(t, s, "POST", path, map[string]any{"requestId": "bad", "type": "bash"}); w.Code != 400 {
		t.Fatal("arbitrary RPC accepted")
	}
	if methodCount(t, log, "compact") != 0 {
		t.Fatal("rejected compact dispatched")
	}
}
func TestPiStopFencesUndispatchedPromptAndPreservesDraft(t *testing.T) {
	s, task, in, log, _ := piControlFixture(t, "")
	_, err := s.reserveRequest("unsent", task.ID, "messages", map[string]string{"text": "keep this"}, func(st *core.State, req *core.Request) error {
		req.Role = "architect"
		r := st.Tasks[task.ID].Sessions["architect"]
		r.PendingCommands = append(r.PendingCommands, "unsent")
		refreshPending(r)
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if w := call(t, s, "POST", "/v1/tasks/"+task.ID+"/pi/abort", in); w.Code != 202 {
		t.Fatal(w.Body.String())
	}
	awaitPiRequest(t, s, in.RequestID, "completed")
	s.prompt("unsent", task.ID, "architect", "keep this")
	if methodCount(t, log, "prompt") != 0 || methodCount(t, log, "clear_queue") != 1 || methodCount(t, log, "abort") != 1 {
		t.Fatalf("stop dispatch race: %v", piMethods(t, log))
	}
	if s.store.Snapshot().Requests["unsent"].Status != "cancelled" {
		t.Fatal("undispatched prompt not cancelled")
	}
	found := false
	for _, event := range s.store.Snapshot().Events {
		if strings.Contains(string(event.Data), "keep this") {
			found = true
		}
	}
	if !found {
		t.Fatal("cancelled unsent text was not offered as draft")
	}
	if task, _ = s.task(task.ID); task.Execution != nil {
		t.Fatal("Pi stop created/changed remote execution")
	}
}
func TestPiStopInterruptsCompactionWithoutDispatchDeadlock(t *testing.T) {
	s, task, in, log, _ := piControlFixture(t, "")
	if w := call(t, s, "POST", "/v1/tasks/"+task.ID+"/pi/compact", in); w.Code != 202 {
		t.Fatal(w.Body.String())
	}
	until := time.Now().Add(time.Second)
	for methodCount(t, log, "compact") == 0 && time.Now().Before(until) {
		time.Sleep(5 * time.Millisecond)
	}
	in.RequestID = "stop"
	if w := call(t, s, "POST", "/v1/tasks/"+task.ID+"/pi/abort", in); w.Code != 202 {
		t.Fatal(w.Body.String())
	}
	awaitPiRequest(t, s, "stop", "completed")
	awaitPiRequest(t, s, "control", "cancelled")
	if methodCount(t, log, "compact") != 1 || methodCount(t, log, "abort") != 1 {
		t.Fatal("incorrect compaction/stop dispatch")
	}
}
func TestPiUnknownControlNeverReplaysAfterRestart(t *testing.T) {
	s, task, in, log, _ := piControlFixture(t, "crash_model")
	in.Provider = "test"
	in.ModelID = "two"
	path := "/v1/tasks/" + task.ID + "/pi/model"
	if w := call(t, s, "POST", path, in); w.Code != 202 {
		t.Fatal(w.Body.String())
	}
	awaitPiRequest(t, s, in.RequestID, "needs_verification")
	s.Close()
	reopened, err := New(s.cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	if w := call(t, reopened, "POST", path, in); w.Code != 202 || !strings.Contains(w.Body.String(), "needs_verification") {
		t.Fatalf("lost uncertain receipt: %s", w.Body.String())
	}
	if methodCount(t, log, "set_model") != 1 {
		t.Fatal("uncertain mutation replayed")
	}
}
func TestPiLateControlCannotOverwriteReplacement(t *testing.T) {
	s, task, in, log, release := piControlFixture(t, "hold_model")
	in.Provider = "test"
	in.ModelID = "two"
	if w := call(t, s, "POST", "/v1/tasks/"+task.ID+"/pi/model", in); w.Code != 202 {
		t.Fatal(w.Body.String())
	}
	until := time.Now().Add(time.Second)
	for methodCount(t, log, "set_model") == 0 && time.Now().Before(until) {
		time.Sleep(5 * time.Millisecond)
	}
	_ = s.store.Update(func(st *core.State) error {
		r := st.Tasks[task.ID].Sessions["architect"]
		r.ProcessID = "replacement"
		r.Busy = true
		return nil
	})
	if err := os.WriteFile(release, nil, 0600); err != nil {
		t.Fatal(err)
	}
	awaitPiRequest(t, s, in.RequestID, "needs_verification")
	now, _ := s.task(task.ID)
	if now.Sessions["architect"].ProcessID != "replacement" || !now.Sessions["architect"].Busy {
		t.Fatal("late control overwrote replacement")
	}
}

func TestPiEmptyDiscoveryDoesNotInventBuiltins(t *testing.T) {
	s, task, _, _, _ := piControlFixture(t, "no_commands")
	w := call(t, s, "GET", "/v1/tasks/"+task.ID+"/pi/commands?role=architect", nil)
	if w.Code != 200 || !strings.Contains(w.Body.String(), `"commands":[]`) {
		t.Fatalf("empty discovery: %s", w.Body.String())
	}
	for _, forbidden := range []string{"settings", "hotkeys", "new_session", "fork", "bash", "login"} {
		if strings.Contains(w.Body.String(), forbidden) {
			t.Fatalf("invented capability %s", forbidden)
		}
	}
}
func TestPiUnavailableModelFailsBeforeMutation(t *testing.T) {
	s, task, in, log, _ := piControlFixture(t, "")
	in.Provider = "test"
	in.ModelID = "missing"
	w := call(t, s, "POST", "/v1/tasks/"+task.ID+"/pi/model", in)
	if w.Code != 202 {
		t.Fatal(w.Body.String())
	}
	req := awaitPiRequest(t, s, in.RequestID, "failed")
	if req.Dispatched || methodCount(t, log, "set_model") != 0 {
		t.Fatal("unavailable model dispatched")
	}
	current, _ := s.task(task.ID)
	if current.Sessions["architect"].Pending {
		t.Fatal("preflight failure left control gate")
	}
}
func TestPiNewPromptBlockedWhileControlIsUncertain(t *testing.T) {
	s, task, in, log, release := piControlFixture(t, "hold_model")
	in.Provider = "test"
	in.ModelID = "two"
	if w := call(t, s, "POST", "/v1/tasks/"+task.ID+"/pi/model", in); w.Code != 202 {
		t.Fatal(w.Body.String())
	}
	if w := call(t, s, "POST", "/v1/tasks/"+task.ID+"/messages", actionInput{RequestID: "blocked-message", Text: "do not queue"}); w.Code != 409 {
		t.Fatal("message bypassed control gate")
	}
	if methodCount(t, log, "prompt") != 0 {
		t.Fatal("blocked prompt reached Pi")
	}
	if err := os.WriteFile(release, nil, 0600); err != nil {
		t.Fatal(err)
	}
	awaitPiRequest(t, s, in.RequestID, "completed")
}

func TestPiControlsRespectOtherRoleAccounting(t *testing.T) {
	s, task, in, _, _ := piControlFixture(t, "")
	activeSince := time.Now().Add(-4 * time.Second)
	_ = s.store.Update(func(st *core.State) error {
		current := st.Tasks[task.ID]
		current.Sessions["reviewer"] = &core.Session{ID: "reviewer", Available: true, Busy: true}
		current.Budget.ActiveSince = &activeSince
		return nil
	})
	if w := call(t, s, "POST", "/v1/tasks/"+task.ID+"/pi/compact", in); w.Code != 409 {
		t.Fatal("compaction admitted while another task role was active")
	}
	if w := call(t, s, "POST", "/v1/tasks/"+task.ID+"/pi/abort", in); w.Code != 202 {
		t.Fatal(w.Body.String())
	}
	awaitPiRequest(t, s, in.RequestID, "completed")
	current, _ := s.task(task.ID)
	if current.Budget.ActiveSince == nil || !current.Sessions["reviewer"].Busy {
		t.Fatal("idle-role stop cleared the working role's budget/activity")
	}
}

func TestPiModelMustMatchRequestedResponseAndFinalState(t *testing.T) {
	for _, mode := range []string{"wrong_model_response", "wrong_model_state"} {
		t.Run(mode, func(t *testing.T) {
			s, task, in, log, _ := piControlFixture(t, mode)
			in.Provider = "test"
			in.ModelID = "two"
			path := "/v1/tasks/" + task.ID + "/pi/model"
			if w := call(t, s, "POST", path, in); w.Code != 202 {
				t.Fatal(w.Body.String())
			}
			awaitPiRequest(t, s, in.RequestID, "needs_verification")
			if w := call(t, s, "POST", path, in); w.Code != 202 || !strings.Contains(w.Body.String(), "needs_verification") {
				t.Fatal("model mismatch lost uncertain receipt")
			}
			if methodCount(t, log, "set_model") != 1 {
				t.Fatal("mismatched model mutation replayed")
			}
		})
	}
}
