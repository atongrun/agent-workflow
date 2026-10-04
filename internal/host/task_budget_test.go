package host

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
	"github.com/atongrun/agent-workflow/internal/node"
)

func budgetFixture(t *testing.T, s *Server) *core.Task {
	t.Helper()
	task := createTask(t, s, core.ID())
	if err := s.store.Update(func(st *core.State) error {
		x := st.Tasks[task.ID]
		x.Status = "blocked"
		x.Execution = &core.Execution{RequestID: "prior", Status: "failed", AccountedSeconds: 90, SessionID: "native-prior", Error: "prior failure"}
		x.Budget.TaskSeconds = 120
		x.Budget.Reworks = 1
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	task, _ = s.task(task.ID)
	return task
}

func TestBudgetBlockedPreservesCountersAndReceipts(t *testing.T) {
	s := testServer(t)
	task := budgetFixture(t, s)
	other := createTask(t, s, "other")
	in := budgetInput{RequestID: "tighten", ExpectedBudgetRevision: ptr(0), TaskMinutes: ptr(1), MaxReworks: ptr(0)}
	save := func() *httptest.ResponseRecorder { return call(t, s, "PATCH", "/v1/tasks/"+task.ID+"/budget", in) }
	if w := save(); w.Code != 202 {
		t.Fatal(w.Body.String())
	}
	got, _ := s.task(task.ID)
	if got.BudgetRevision != 1 || got.Settings.TaskMinutes != 1 || got.Settings.MaxReworks != 0 || !reflect.DeepEqual(got.Budget, task.Budget) || !reflect.DeepEqual(got.Execution, task.Execution) || got.Status != task.Status {
		t.Fatalf("unexpected mutation: %+v", got)
	}
	if remainingSeconds(got) >= 0 {
		t.Fatal("spent budget gained time")
	}
	if s.store.Snapshot().Settings != core.Defaults() || s.store.Snapshot().Tasks[other.ID].Settings != other.Settings {
		t.Fatal("affected other task/defaults")
	}
	receipt := s.store.Snapshot().Requests[in.RequestID]
	if receipt.Status != "completed" || len(receipt.Result) == 0 {
		t.Fatal("missing durable audit")
	}
	if err := s.store.Update(func(st *core.State) error { st.Tasks[task.ID].Status = "executing"; return nil }); err != nil {
		t.Fatal(err)
	}
	if w := save(); w.Code != 202 {
		t.Fatal("historical retry must work", w.Body.String())
	}
	if got, _ = s.task(task.ID); got.BudgetRevision != 1 {
		t.Fatal("retry changed revision")
	}
	path := "/v1/tasks/" + task.ID + "/requests/" + in.RequestID
	if w := call(t, s, "POST", path, map[string]any{"requestId": in.RequestID, "operation": "budget", "payload": in}); w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	in.TaskMinutes = ptr(2)
	if w := save(); w.Code != 409 {
		t.Fatal("conflicting retry accepted")
	}
}

func TestBudgetValidationAndInactiveFences(t *testing.T) {
	cases := map[string]struct {
		input  budgetInput
		mutate func(*core.Task, *core.State)
		code   int
	}{
		"missing_revision": {budgetInput{TaskMinutes: ptr(10)}, nil, 409},
		"stale_revision":   {budgetInput{ExpectedBudgetRevision: ptr(1), TaskMinutes: ptr(10)}, nil, 409},
		"empty":            {budgetInput{ExpectedBudgetRevision: ptr(0)}, nil, 400},
		"zero_minutes":     {budgetInput{ExpectedBudgetRevision: ptr(0), TaskMinutes: ptr(0)}, nil, 400},
		"negative_reworks": {budgetInput{ExpectedBudgetRevision: ptr(0), MaxReworks: ptr(-1)}, nil, 400},
		"increase":         {budgetInput{ExpectedBudgetRevision: ptr(0), TaskMinutes: ptr(61), MaxReworks: ptr(1)}, nil, 409},
		"rework_increase":  {budgetInput{ExpectedBudgetRevision: ptr(0), MaxReworks: ptr(3)}, nil, 409},
		"unchanged":        {budgetInput{ExpectedBudgetRevision: ptr(0), TaskMinutes: ptr(60)}, nil, 409},
	}
	fences := map[string]func(*core.Task, *core.State){
		"unknown_task":      func(x *core.Task, _ *core.State) { x.Status = "future_status" },
		"empty_task":        func(x *core.Task, _ *core.State) { x.Status = "" },
		"unknown_execution": func(x *core.Task, _ *core.State) { x.Execution.Status = "future_status" },
		"empty_execution":   func(x *core.Task, _ *core.State) { x.Execution.Status = "" },
		"unknown_receipt": func(x *core.Task, st *core.State) {
			st.Requests["unknown"] = &core.Request{TaskID: x.ID, Status: "future_status"}
		},
		"empty_receipt": func(x *core.Task, st *core.State) { st.Requests["unknown"] = &core.Request{TaskID: x.ID} },
		"native_prompt": func(x *core.Task, st *core.State) {
			st.Requests["unknown"] = &core.Request{TaskID: x.ID, Status: "accepted_native", Operation: "messages"}
		},
		"native_unknown": func(x *core.Task, st *core.State) {
			st.Requests["unknown"] = &core.Request{TaskID: x.ID, Status: "accepted_native", Operation: "future_operation"}
		},
		"sent_unknown": func(x *core.Task, st *core.State) {
			st.Requests["unknown"] = &core.Request{TaskID: x.ID, Status: "sent_native", Operation: "future_operation"}
		},
		"active":       func(x *core.Task, _ *core.State) { x.Execution.Status = "uncertain" },
		"reporting":    func(x *core.Task, _ *core.State) { x.Status = "reporting" },
		"review":       func(x *core.Task, _ *core.State) { x.Status = "review" },
		"verification": func(x *core.Task, _ *core.State) { x.Status = "needs_verification" },
		"queued":       func(x *core.Task, _ *core.State) { x.Status = "queued" },
		"busy":         func(x *core.Task, _ *core.State) { x.Sessions["architect"].Busy = true },
		"pending_ui": func(x *core.Task, _ *core.State) {
			x.Sessions["architect"].PendingUI = []json.RawMessage{json.RawMessage(`{}`)}
		},
		"native_queue": func(x *core.Task, _ *core.State) { x.Sessions["architect"].NativeQueued = 1 },
		"active_since": func(x *core.Task, _ *core.State) { now := time.Now(); x.Budget.ActiveSince = &now },
		"permissions": func(x *core.Task, _ *core.State) {
			x.Execution.PendingPermissions = []json.RawMessage{json.RawMessage(`{}`)}
		},
		"questions": func(x *core.Task, _ *core.State) {
			x.Execution.PendingQuestions = []json.RawMessage{json.RawMessage(`{}`)}
		},
		"receipt": func(x *core.Task, st *core.State) {
			st.Requests["pending"] = &core.Request{TaskID: x.ID, Status: "needs_verification"}
		},
		"deleted": func(x *core.Task, _ *core.State) { now := time.Now(); x.DeletedAt = &now },
	}
	for name, f := range fences {
		cases[name] = struct {
			input  budgetInput
			mutate func(*core.Task, *core.State)
			code   int
		}{budgetInput{ExpectedBudgetRevision: ptr(0), TaskMinutes: ptr(10)}, f, 409}
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			s := testServer(t)
			task := budgetFixture(t, s)
			if c.mutate != nil {
				if err := s.store.Update(func(st *core.State) error { c.mutate(st.Tasks[task.ID], st); return nil }); err != nil {
					t.Fatal(err)
				}
			}
			before := s.store.Snapshot()
			c.input.RequestID = "invalid"
			w := call(t, s, "PATCH", "/v1/tasks/"+task.ID+"/budget", c.input)
			if w.Code != c.code {
				t.Fatalf("%d %s", w.Code, w.Body.String())
			}
			if !reflect.DeepEqual(before, s.store.Snapshot()) {
				t.Fatal("rejected mutation changed state")
			}
		})
	}
}

func TestBudgetConcurrentRevisionAndStart(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "race")
	planFixture(t, s, task.ID, true)
	var wg sync.WaitGroup
	codes := make(chan int, 2)
	for _, minutes := range []int{10, 5} {
		wg.Add(1)
		go func(minutes int) {
			defer wg.Done()
			codes <- call(t, s, "PATCH", "/v1/tasks/"+task.ID+"/budget", budgetInput{RequestID: core.ID(), ExpectedBudgetRevision: ptr(0), TaskMinutes: ptr(minutes)}).Code
		}(minutes)
	}
	wg.Wait()
	close(codes)
	success := 0
	for code := range codes {
		if code == 202 {
			success++
		} else if code != 409 {
			t.Fatal(code)
		}
	}
	if success != 1 {
		t.Fatal("revision race did not serialize")
	}
	// Starting may follow a reduction, but reducing must never follow a start.
	wg.Add(2)
	var startErr error
	var saveCode int
	go func() {
		defer wg.Done()
		_, startErr = s.reserve("race-start", task.ID, "start", nil, func(st *core.State) error {
			return s.prepareExecution(st, st.Tasks[task.ID], "race-start", 1, false, nil)
		})
	}()
	go func() {
		defer wg.Done()
		saveCode = call(t, s, "PATCH", "/v1/tasks/"+task.ID+"/budget", budgetInput{RequestID: "race-budget", ExpectedBudgetRevision: ptr(1), TaskMinutes: ptr(1)}).Code
	}()
	wg.Wait()
	got, _ := s.task(task.ID)
	if startErr != nil {
		t.Fatal(startErr)
	}
	if saveCode != 202 && saveCode != 409 {
		t.Fatal(saveCode)
	}
	if got.Execution.TimeoutSeconds != remainingSeconds(got) {
		t.Fatal("start used stale budget")
	}
}

func TestBudgetDispatchRechecksAndFailsClosed(t *testing.T) {
	for name, tc := range map[string]struct {
		taskUsed, planUsed        int64
		exhausted                 bool
		invalidTimeout, attempted bool
	}{
		"task_remaining": {taskUsed: 590}, "task_exhausted": {taskUsed: 600, exhausted: true},
		"plan_remaining": {planUsed: 10790}, "plan_exhausted": {planUsed: 10800, exhausted: true},
		"invalid_timeout":   {invalidTimeout: true, exhausted: true},
		"already_attempted": {taskUsed: 590, attempted: true, exhausted: true},
	} {
		t.Run(name, func(t *testing.T) {
			s := testServer(t)
			task := createTask(t, s, "dispatch")
			planFixture(t, s, task.ID, true)
			if w := call(t, s, "PATCH", "/v1/tasks/"+task.ID+"/budget", budgetInput{RequestID: "limit", ExpectedBudgetRevision: ptr(0), TaskMinutes: ptr(10)}); w.Code != 202 {
				t.Fatal(w.Body.String())
			}
			if _, err := s.reserve("dispatch-start", task.ID, "start", nil, func(st *core.State) error {
				return s.prepareExecution(st, st.Tasks[task.ID], "dispatch-start", 1, false, nil)
			}); err != nil {
				t.Fatal(err)
			}
			if err := s.store.Update(func(st *core.State) error {
				st.Tasks[task.ID].Budget.TaskSeconds = tc.taskUsed
				if tc.invalidTimeout {
					st.Tasks[task.ID].Execution.TimeoutSeconds = 0
				}
				st.Tasks[task.ID].Execution.DispatchAttempted = tc.attempted
				if tc.planUsed > 0 {
					st.Tasks["sibling"] = &core.Task{ID: "sibling", PlanID: task.PlanID, Budget: core.Budget{TaskSeconds: tc.planUsed}}
				}
				return nil
			}); err != nil {
				t.Fatal(err)
			}
			beforeDispatch, _ := s.task(task.ID)
			fingerprint := s.jobRequest(beforeDispatch)
			var posts atomic.Int32
			done := make(chan int, 1)
			fixture := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if serveTestCatalog(w, r) {
					return
				}
				if r.Method == "POST" && r.URL.Path == "/v1/jobs" {
					var in node.JobRequest
					_ = json.NewDecoder(r.Body).Decode(&in)
					posts.Add(1)
					done <- in.TimeoutSeconds
					writeJSON(w, 200, node.Job{ID: node.JobID(in.RequestID), TaskID: in.TaskID, RequestID: in.RequestID, Status: "failed"})
					return
				}
				http.NotFound(w, r)
			}))
			defer fixture.Close()
			cfg := s.cfg.Nodes["n"]
			cfg.URL = fixture.URL
			s.cfg.Nodes["n"] = cfg
			s.monitor(task.ID)
			deadline := time.Now().Add(3 * time.Second)
			for time.Now().Before(deadline) {
				got, _ := s.task(task.ID)
				if got.Status == "needs_verification" || got.Execution.Status == "failed" {
					break
				}
				time.Sleep(10 * time.Millisecond)
			}
			got, _ := s.task(task.ID)
			if tc.exhausted {
				if posts.Load() != 0 || got.Execution.DispatchAttempted != tc.attempted || got.Status != "needs_verification" {
					t.Fatalf("exhausted dispatch: %+v", got.Execution)
				}
				if !reflect.DeepEqual(fingerprint, s.jobRequest(got)) {
					t.Fatal("rejected/attempted dispatch changed fingerprint")
				}
			} else {
				select {
				case timeout := <-done:
					if timeout != 10 {
						t.Fatal(timeout)
					}
				default:
					t.Fatal("no bounded dispatch")
				}
			}
		})
	}
}

func TestBudgetSpentLimitsPreventFurtherWork(t *testing.T) {
	for _, reworks := range []int{0, 2} {
		t.Run(core.ID(), func(t *testing.T) {
			s := testServer(t)
			task := budgetFixture(t, s)
			planFixture(t, s, task.ID, true)
			if err := s.store.Update(func(st *core.State) error {
				x := st.Tasks[task.ID]
				x.Execution.Status = "completed"
				x.Execution.Error = ""
				x.Completion = &core.Completion{Verdict: "needs_changes", ExecutionRequestID: "prior"}
				return nil
			}); err != nil {
				t.Fatal(err)
			}
			minutes := 1
			if reworks == 0 {
				minutes = 10
			}
			if w := call(t, s, "PATCH", "/v1/tasks/"+task.ID+"/budget", budgetInput{RequestID: "spent", ExpectedBudgetRevision: ptr(0), TaskMinutes: ptr(minutes), MaxReworks: ptr(reworks)}); w.Code != 202 {
				t.Fatal(w.Body.String())
			}
			before := s.store.Snapshot()
			_, err := s.reserve("spent-rework", task.ID, "rework", nil, func(st *core.State) error {
				return s.prepareExecution(st, st.Tasks[task.ID], "spent-rework", 1, true, nil)
			})
			want := "budget_exhausted"
			if reworks == 0 {
				want = "rework_limit"
			}
			api, ok := err.(*apiError)
			if !ok || api.Code != want || !reflect.DeepEqual(before, s.store.Snapshot()) {
				t.Fatalf("spent limit did not fail for %s or reset state: %v", want, err)
			}
		})
	}
}

func TestBudgetPersistenceAndRestart(t *testing.T) {
	s := testServer(t)
	task := budgetFixture(t, s)
	in := budgetInput{RequestID: "durable-budget", ExpectedBudgetRevision: ptr(0), TaskMinutes: ptr(10)}
	if w := call(t, s, "PATCH", "/v1/tasks/"+task.ID+"/budget", in); w.Code != 202 {
		t.Fatal(w.Body.String())
	}
	before := s.store.Snapshot()
	if err := s.store.Close(); err != nil {
		t.Fatal(err)
	}
	reopened, err := core.Open(s.cfg.DataDir)
	if err != nil {
		t.Fatal(err)
	}
	s.store = reopened
	if w := call(t, s, "PATCH", "/v1/tasks/"+task.ID+"/budget", in); w.Code != 202 {
		t.Fatal(w.Body.String())
	}
	if !reflect.DeepEqual(before, s.store.Snapshot()) {
		t.Fatal("restart/retry changed limits or audit")
	}
	// Block the atomic state-file replacement without moving DataDir or its
	// open host.lock handle, which Windows does not permit. Preserve the JSON.
	statePath := filepath.Join(s.cfg.DataDir, "state.json")
	moved := statePath + "-saved"
	if err := os.Rename(statePath, moved); err != nil {
		t.Fatal(err)
	}
	defer func() {
		if err := os.Remove(statePath); err != nil && !os.IsNotExist(err) {
			t.Error(err)
		}
		if err := os.Rename(moved, statePath); err != nil {
			t.Error(err)
		}
	}()
	if err := os.Mkdir(statePath, 0700); err != nil {
		t.Fatal(err)
	}
	in.RequestID = "failed-budget"
	in.ExpectedBudgetRevision = ptr(1)
	in.TaskMinutes = ptr(5)
	if w := call(t, s, "PATCH", "/v1/tasks/"+task.ID+"/budget", in); w.Code != 500 {
		t.Fatal(w.Code, w.Body.String())
	}
	if !reflect.DeepEqual(before, s.store.Snapshot()) {
		t.Fatal("failed persistence leaked mutation or receipt")
	}
	if _, err := s.reserve("fail-closed-start", task.ID, "start", nil, func(st *core.State) error { t.Error("faulted store accepted mutation"); return nil }); err == nil {
		t.Fatal("faulted store allowed work")
	}
}

func TestBudgetStrictHTTPInput(t *testing.T) {
	s := testServer(t)
	task := createTask(t, s, "strict")
	for _, payload := range []map[string]any{
		{"requestId": "strict", "expectedBudgetRevision": 0, "taskMinutes": 1.5},
		{"requestId": "strict", "expectedBudgetRevision": 0, "taskMinutes": 10, "planMinutes": 100},
		{"requestId": "strict", "expectedBudgetRevision": 0, "taskMinutes": 10, "budget": map[string]any{"reworks": 0}},
		{"requestId": "unsafe id", "expectedBudgetRevision": 0, "taskMinutes": 10},
	} {
		if w := call(t, s, "PATCH", "/v1/tasks/"+task.ID+"/budget", payload); w.Code != 400 {
			t.Fatal(w.Code, w.Body.String())
		}
	}
	in := budgetInput{RequestID: "strict-budget", ExpectedBudgetRevision: ptr(0), TaskMinutes: ptr(10)}
	if w := call(t, s, "PATCH", "/v1/tasks/"+task.ID+"/budget?reset=true", in); w.Code != 400 {
		t.Fatal(w.Code)
	}
	if w := call(t, s, "PATCH", "/v1/tasks/missing/budget", in); w.Code != 404 {
		t.Fatal(w.Code)
	}
}

func TestBudgetKnownSettledReceipts(t *testing.T) {
	for _, receipt := range []core.Request{
		{Status: "completed"}, {Status: "failed"}, {Status: "cancelled"}, {Status: "settled"},
		{Status: "accepted_native", Operation: "execution/cancel"},
		{Status: "accepted_native", Operation: "pi/abort"},
		{Status: "sent_native", Operation: "pi/ui-response"},
	} {
		t.Run(receipt.Status+receipt.Operation, func(t *testing.T) {
			s := testServer(t)
			task := budgetFixture(t, s)
			if err := s.store.Update(func(st *core.State) error {
				receipt.TaskID = task.ID
				st.Requests["old-receipt"] = &receipt
				return nil
			}); err != nil {
				t.Fatal(err)
			}
			if w := call(t, s, "PATCH", "/v1/tasks/"+task.ID+"/budget", budgetInput{RequestID: "reduce", ExpectedBudgetRevision: ptr(0), TaskMinutes: ptr(10)}); w.Code != 202 {
				t.Fatal(w.Code, w.Body.String())
			}
		})
	}
}

func TestBudgetLegacyStateWithoutRevision(t *testing.T) {
	s := testServer(t)
	task := budgetFixture(t, s)
	encoded, _ := json.Marshal(s.store.Snapshot())
	var legacy map[string]json.RawMessage
	if err := json.Unmarshal(encoded, &legacy); err != nil {
		t.Fatal(err)
	}
	var tasks map[string]map[string]json.RawMessage
	if err := json.Unmarshal(legacy["tasks"], &tasks); err != nil {
		t.Fatal(err)
	}
	delete(tasks[task.ID], "budgetRevision")
	legacy["tasks"], _ = json.Marshal(tasks)
	encoded, _ = json.Marshal(legacy)
	if err := s.store.Close(); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(s.cfg.DataDir, "state.json"), encoded, 0600); err != nil {
		t.Fatal(err)
	}
	reopened, err := core.Open(s.cfg.DataDir)
	if err != nil {
		t.Fatal(err)
	}
	s.store = reopened
	got, _ := s.task(task.ID)
	if got.BudgetRevision != 0 || !reflect.DeepEqual(task.Budget, got.Budget) || !reflect.DeepEqual(task.Execution, got.Execution) {
		t.Fatal("legacy state changed")
	}
	if w := call(t, s, "PATCH", "/v1/tasks/"+task.ID+"/budget", budgetInput{RequestID: "legacy-reduce", ExpectedBudgetRevision: ptr(0), TaskMinutes: ptr(10)}); w.Code != 202 {
		t.Fatal(w.Code, w.Body.String())
	}
}

func TestBudgetConcurrentExactRetries(t *testing.T) {
	s := testServer(t)
	task := budgetFixture(t, s)
	in := budgetInput{RequestID: "same-budget", ExpectedBudgetRevision: ptr(0), TaskMinutes: ptr(10)}
	var wg sync.WaitGroup
	for range 20 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if w := call(t, s, "PATCH", "/v1/tasks/"+task.ID+"/budget", in); w.Code != 202 {
				t.Errorf("%d %s", w.Code, w.Body.String())
			}
		}()
	}
	wg.Wait()
	st := s.store.Snapshot()
	count := 0
	for _, event := range st.Events {
		if event.Type == "budget.tightened" {
			count++
		}
	}
	if count != 1 || st.Tasks[task.ID].BudgetRevision != 1 || st.Requests[in.RequestID].Status != "completed" {
		t.Fatal("duplicate audit/revision/effect")
	}
}

func TestBudgetFailedTaskReplanDoesNotAuthorizeRetry(t *testing.T) {
	s := testServer(t)
	task := budgetFixture(t, s)
	if w := call(t, s, "PATCH", "/v1/tasks/"+task.ID+"/budget", budgetInput{RequestID: "failed-reduce", ExpectedBudgetRevision: ptr(0), TaskMinutes: ptr(10)}); w.Code != 202 {
		t.Fatal(w.Body.String())
	}
	req := httptest.NewRequest("POST", "/internal/tasks/"+task.ID+"/plan", strings.NewReader(`{"requestId":"replan-failed","content":"Revised scope"}`))
	req.Header.Set("Authorization", "Bearer "+s.scopedToken(task.ID, "architect"))
	req.Header.Set("X-AWF-Role", "architect")
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, req)
	if w.Code != 202 {
		t.Fatal(w.Code, w.Body.String())
	}
	if w := call(t, s, "POST", "/v1/tasks/"+task.ID+"/plan/confirm", actionInput{RequestID: "confirm-failed", Revision: 1}); w.Code != 202 {
		t.Fatal(w.Code, w.Body.String())
	}
	before := s.store.Snapshot()
	for op, code := range map[string]string{"start": "use_rework", "rework": "rework_unavailable"} {
		w := call(t, s, "POST", "/v1/tasks/"+task.ID+"/"+op, actionInput{RequestID: "reject-" + op, Revision: 1, ExecutionRequestID: "prior"})
		if w.Code != 409 || !strings.Contains(w.Body.String(), code) {
			t.Fatal(w.Code, w.Body.String())
		}
	}
	if !reflect.DeepEqual(before, s.store.Snapshot()) {
		t.Fatal("failed task gained execution authority")
	}
}
