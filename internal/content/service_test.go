package content

import (
	"context"
	"errors"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// ledgerFixture tests service ordering/failure behavior only. Real SQLite
// transactions and recovery are tested separately with sqliteintegration.
type ledgerFixture struct {
	mu           sync.Mutex
	job          Job
	owner        string
	ex           Execute
	claimed      bool
	claimError   error
	enqueueError error
	finishError  error
	claimEntered chan struct{}
	claimRelease chan struct{}
	finished     chan Outcome
}

func newLedgerFixture() *ledgerFixture {
	return &ledgerFixture{job: Job{JobID: fixtureID, Status: Queued}, owner: "fixture-owner", ex: fixtureExecute(), finished: make(chan Outcome, 2)}
}
func (l *ledgerFixture) Enqueue(_ context.Context, owner string, in Input, _ string, _ Profile, _ int) (Job, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.enqueueError != nil {
		return Job{}, l.enqueueError
	}
	l.owner = owner
	l.job.RequestID = in.RequestID
	return l.job, nil
}
func (l *ledgerFixture) Get(_ context.Context, owner, id string) (Job, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	if owner != l.owner || id != l.job.JobID {
		return Job{}, ErrNotFound
	}
	return l.job, nil
}
func (l *ledgerFixture) List(_ context.Context, owner, _ string, _ int) (Page, error) {
	j, e := l.Get(context.Background(), owner, l.job.JobID)
	if e != nil {
		return Page{Jobs: []Job{}}, nil
	}
	j.Result = nil
	return Page{Jobs: []Job{j}}, nil
}
func (l *ledgerFixture) Cancel(_ context.Context, owner, id string) (Job, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	if owner != l.owner || id != l.job.JobID {
		return Job{}, ErrNotFound
	}
	if !l.job.Status.Terminal() {
		l.job.CancelRequested = true
		if l.job.Status == Queued {
			l.job.Status = Cancelled
		} else {
			l.job.Status = Cancelling
		}
	}
	return l.job, nil
}
func (l *ledgerFixture) Claim(ctx context.Context, _ string) (*Execute, error) {
	l.mu.Lock()
	if l.claimError != nil {
		err := l.claimError
		l.mu.Unlock()
		return nil, err
	}
	if l.claimed || l.job.Status != Queued {
		l.mu.Unlock()
		return nil, nil
	}
	l.claimed = true
	l.job.Status = Running
	ex := l.ex
	l.mu.Unlock()
	if l.claimEntered != nil {
		close(l.claimEntered)
		select {
		case <-l.claimRelease:
		case <-ctx.Done():
			return nil, ctx.Err()
		}
	}
	return &ex, nil
}
func (l *ledgerFixture) Finish(_ context.Context, _ Execute, r Outcome) error {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.finishError != nil {
		l.finished <- r
		return l.finishError
	}
	l.job.Status, l.job.ErrorCode = terminalOutcome(l.job.CancelRequested, r)
	if l.job.Status == Succeeded {
		l.job.Result = r.Artifact
	}
	l.finished <- r
	return nil
}
func (l *ledgerFixture) CancelRequested(context.Context, Execute) (bool, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.job.CancelRequested, nil
}
func (l *ledgerFixture) Halted(context.Context) (bool, error)                         { return false, nil }
func (l *ledgerFixture) RecordBinding(context.Context, Execute, ProcessBinding) error { return nil }

type runnerFunc func(context.Context, Execute, <-chan struct{}) Outcome

func (f runnerFunc) Run(ctx context.Context, e Execute, c <-chan struct{}) Outcome {
	return f(ctx, e, c)
}

type disconnectLedgerFixture struct {
	*ledgerFixture
	entered chan struct{}
	release chan struct{}
}

func (l *disconnectLedgerFixture) Enqueue(ctx context.Context, owner string, in Input, hash string, p Profile, limit int) (Job, error) {
	close(l.entered)
	<-l.release
	if err := ctx.Err(); err != nil {
		return Job{}, err
	}
	return l.ledgerFixture.Enqueue(ctx, owner, in, hash, p, limit)
}

func TestStartedMutationSurvivesCallerDisconnectFixture(t *testing.T) {
	l := &disconnectLedgerFixture{ledgerFixture: newLedgerFixture(), entered: make(chan struct{}), release: make(chan struct{})}
	s, err := NewService(l, runnerFunc(func(context.Context, Execute, <-chan struct{}) Outcome {
		t.Error("unexpected process")
		return Outcome{}
	}), fixtureProfile(), 2)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { _, err := s.Enqueue(ctx, l.owner, Input{}, "fixture"); done <- err }()
	<-l.entered
	cancel()
	close(l.release)
	if err := <-done; err != nil {
		t.Fatalf("started transaction inherited client disconnect: %v", err)
	}
	if s.fault.Load() {
		t.Fatal("caller disconnect faulted executor")
	}
}
func fixtureProfile() Profile {
	return Profile{ModelRef: "fixture", ResourceVersions: map[string]string{"shortpost": "fixture"}, TimeoutSeconds: 10}
}
func fixtureSuccess() Outcome {
	raw := []byte(`{"example":"fixture"}`)
	a := artifactFor(raw)
	return Outcome{SessionRef: "fixture-session", StopReason: "completed", Artifact: &a, RawArtifact: raw, CleanExit: true, Quiescent: true}
}
func awaitOutcome(t *testing.T, l *ledgerFixture) Outcome {
	t.Helper()
	select {
	case r := <-l.finished:
		return r
	case <-time.After(3 * time.Second):
		t.Fatal("executor did not finish")
		return Outcome{}
	}
}

func TestExecutorFixtureCancelsBeforeProcessStarts(t *testing.T) {
	l := newLedgerFixture()
	l.claimEntered = make(chan struct{})
	l.claimRelease = make(chan struct{})
	var calls atomic.Int32
	s, err := NewService(l, runnerFunc(func(context.Context, Execute, <-chan struct{}) Outcome { calls.Add(1); return fixtureSuccess() }), fixtureProfile(), 2)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	s.Start()
	<-l.claimEntered
	if _, err := s.Cancel(context.Background(), l.owner, l.job.JobID); err != nil {
		t.Fatal(err)
	}
	close(l.claimRelease)
	r := awaitOutcome(t, l)
	if calls.Load() != 0 || !r.NotStarted {
		t.Fatal("cancel raced registration and started process")
	}
	j, err := l.Get(context.Background(), l.owner, l.job.JobID)
	if err != nil || j.Status != Cancelled || j.Result != nil {
		t.Fatalf("cancel: %+v %v", j, err)
	}
}

func TestExecutorFixtureCancellationIsIndependent(t *testing.T) {
	l := newLedgerFixture()
	entered := make(chan struct{})
	s, err := NewService(l, runnerFunc(func(_ context.Context, _ Execute, c <-chan struct{}) Outcome {
		close(entered)
		<-c
		return Outcome{StopReason: "aborted", CleanExit: true, Quiescent: true}
	}), fixtureProfile(), 2)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	s.Start()
	<-entered
	if _, err := s.Cancel(context.Background(), "other-owner", fixtureID); !errors.Is(err, ErrNotFound) {
		t.Fatal("cross-owner cancel admitted")
	}
	if _, err := s.Cancel(context.Background(), l.owner, fixtureID); err != nil {
		t.Fatal(err)
	}
	awaitOutcome(t, l)
}

func TestExecutorFixtureFailsClosedAroundEffects(t *testing.T) {
	for _, mode := range []string{"claim", "enqueue", "finish"} {
		t.Run(mode, func(t *testing.T) {
			l := newLedgerFixture()
			injected := errors.New("fixture storage fault")
			switch mode {
			case "claim":
				l.claimError = injected
			case "enqueue":
				l.enqueueError = injected
			case "finish":
				l.finishError = injected
			}
			var calls atomic.Int32
			s, err := NewService(l, runnerFunc(func(context.Context, Execute, <-chan struct{}) Outcome { calls.Add(1); return fixtureSuccess() }), fixtureProfile(), 2)
			if err != nil {
				t.Fatal(err)
			}
			defer s.Close()
			if mode == "enqueue" {
				if _, err := s.Enqueue(context.Background(), l.owner, Input{}, "fixture"); !errors.Is(err, ErrUnavailable) {
					t.Fatal(err)
				}
			}
			s.Start()
			if mode == "finish" {
				awaitOutcome(t, l)
			}
			deadline := time.Now().Add(time.Second)
			for !s.fault.Load() && time.Now().Before(deadline) {
				time.Sleep(time.Millisecond)
			}
			if !s.fault.Load() {
				t.Fatal("storage fault did not latch")
			}
			want := int32(0)
			if mode == "finish" {
				want = 1
			}
			if calls.Load() != want {
				t.Fatalf("process calls %d, want %d", calls.Load(), want)
			}
			if _, err := s.Enqueue(context.Background(), l.owner, Input{}, "fixture"); !errors.Is(err, ErrUnavailable) {
				t.Fatal("mutations still admitted")
			}
			j, err := l.Get(context.Background(), l.owner, fixtureID)
			if err != nil || j.Status == Succeeded {
				t.Fatal("failed finish published success")
			}
		})
	}
}

func TestServiceStartCloseRaceFixture(t *testing.T) {
	for i := 0; i < 25; i++ {
		l := newLedgerFixture()
		s, err := NewService(l, runnerFunc(func(context.Context, Execute, <-chan struct{}) Outcome { return fixtureSuccess() }), fixtureProfile(), 2)
		if err != nil {
			t.Fatal(err)
		}
		var wg sync.WaitGroup
		for j := 0; j < 8; j++ {
			wg.Add(1)
			go func(n int) {
				defer wg.Done()
				if n%2 == 0 {
					s.Start()
				} else {
					s.Close()
				}
			}(j)
		}
		wg.Wait()
		s.Close()
	}
}

func TestDisconnectedMutationDoesNotAbortAnotherOwnerFixture(t *testing.T) {
	l := newLedgerFixture()
	entered := make(chan struct{})
	s, err := NewService(l, runnerFunc(func(_ context.Context, _ Execute, c <-chan struct{}) Outcome {
		close(entered)
		<-c
		return Outcome{StopReason: "aborted", CleanExit: true, Quiescent: true}
	}), fixtureProfile(), 2)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	s.Start()
	<-entered
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := s.Enqueue(ctx, "other-owner", Input{}, "fixture"); !errors.Is(err, context.Canceled) {
		t.Fatal(err)
	}
	if _, err := s.Cancel(ctx, "other-owner", fixtureID); !errors.Is(err, context.Canceled) {
		t.Fatal(err)
	}
	if s.fault.Load() || s.ctx.Err() != nil {
		t.Fatal("disconnected request faulted global executor")
	}
	select {
	case <-l.finished:
		t.Fatal("another owner's attempt was aborted")
	default:
	}
	if _, err := s.Cancel(context.Background(), l.owner, fixtureID); err != nil {
		t.Fatal(err)
	}
	awaitOutcome(t, l)
}

func TestHTTPGenericOwnerAndLimitsFixture(t *testing.T) {
	l := newLedgerFixture()
	s, err := NewService(l, runnerFunc(func(context.Context, Execute, <-chan struct{}) Outcome { return fixtureSuccess() }), fixtureProfile(), 2)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	token := strings.Repeat("x", 24)
	otherToken := strings.Repeat("y", 24)
	h, err := s.Handler([]Credential{{Token: token, Owner: l.owner}, {Token: otherToken, Owner: "other-owner"}})
	if err != nil {
		t.Fatal(err)
	}
	body := `{"requestId":"` + fixtureID + `","capability":"shortpost","payloadSchema":"shortpost.input.v1","opaquePayload":{"example":"fixture"}}`
	cases := []struct {
		method, path, body, token string
		status                    int
	}{
		{"POST", "/v1/content/jobs", body, token, 202},
		{"POST", "/v1/content/jobs", strings.Replace(body, `"capability"`, `"owner":"other-owner","capability"`, 1), token, 400},
		{"POST", "/v1/content/jobs", strings.Repeat("x", MaxBodyBytes+1), token, 413},
		{"GET", "/v1/content/jobs/" + fixtureID, "", otherToken, 404},
		{"POST", "/v1/content/jobs/" + fixtureID + "/cancel", "", otherToken, 404},
		{"GET", "/v1/content/jobs", "", "", 401},
		{"GET", "/v1/content/jobs?limit=101", "", token, 400},
		{"GET", "/v1/content/jobs?limit=1&limit=2", "", token, 400},
		{"GET", "/v1/content/jobs?other=x", "", token, 400},
		{"GET", "/v1/content/jobs?before=%zz", "", token, 400},
		{"POST", "/v1/content/jobs/" + fixtureID + "/cancel", `{"owner":"other-owner"}`, token, 400},
	}
	for i, c := range cases {
		req := httptest.NewRequest(c.method, c.path, strings.NewReader(c.body))
		if c.token != "" {
			req.Header.Set("Authorization", "Bearer "+c.token)
		}
		w := httptest.NewRecorder()
		h.ServeHTTP(w, req)
		if w.Code != c.status {
			t.Fatalf("case %d: %d %s", i, w.Code, w.Body.String())
		}
		if strings.Contains(w.Body.String(), token) || strings.Contains(w.Body.String(), "opaquePayload") {
			t.Fatal("credential or full input in response")
		}
	}
}
