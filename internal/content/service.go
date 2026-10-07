package content

import (
	"context"
	"errors"
	"sync"
	"sync/atomic"
	"time"
)

type Runner interface {
	Run(context.Context, Execute, <-chan struct{}) Outcome
}

// Production process runners record independently observed process identity;
// fixture runners do not claim this evidence.
type ObservedRunner interface {
	RunObserved(context.Context, Execute, <-chan struct{}, func(ProcessBinding) error) Outcome
}

// Service has one bounded executor. HTTP cancellation persists intent before
// waking it; it never waits behind a process call or holds a DB transaction.
type Service struct {
	ledger       Ledger
	runner       Runner
	profile      Profile
	queueLimit   int
	epoch        string
	wake         chan struct{}
	ctx          context.Context
	stop         context.CancelFunc
	wg           sync.WaitGroup
	fault        atomic.Bool
	mu           sync.Mutex
	started      bool
	closed       bool
	activeID     string
	cancelActive chan struct{}
}

func NewService(ledger Ledger, runner Runner, profile Profile, queueLimit int) (*Service, error) {
	if ledger == nil || runner == nil || queueLimit < 1 || queueLimit > 1024 || validProfile(profile) != nil {
		return nil, ErrInvalid
	}
	// Own a snapshot; callers cannot change queued job resources through a map.
	versions := make(map[string]string, len(profile.ResourceVersions))
	for k, v := range profile.ResourceVersions {
		versions[k] = v
	}
	profile.ResourceVersions = versions
	ctx, stop := context.WithCancel(context.Background())
	return &Service{ledger: ledger, runner: runner, profile: profile, queueLimit: queueLimit, epoch: newID(), wake: make(chan struct{}, 1), ctx: ctx, stop: stop}, nil
}

func (s *Service) Start() {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.started || s.closed {
		return
	}
	s.started = true
	s.wg.Add(1)
	go func() { defer s.wg.Done(); s.loop() }()
}
func (s *Service) Close() { s.mu.Lock(); s.closed = true; s.stop(); s.mu.Unlock(); s.wg.Wait() }
func (s *Service) notify() {
	select {
	case s.wake <- struct{}{}:
	default:
	}
}

func expected(err error) bool {
	return errors.Is(err, ErrInvalid) || errors.Is(err, ErrConflict) || errors.Is(err, ErrQueueFull) || errors.Is(err, ErrNotFound) || errors.Is(err, ErrUnavailable)
}

func (s *Service) Enqueue(ctx context.Context, owner string, in Input, hash string) (Job, error) {
	if err := ctx.Err(); err != nil {
		return Job{}, err
	}
	if s.fault.Load() || s.ctx.Err() != nil {
		return Job{}, ErrUnavailable
	}
	txCtx, txStop := context.WithTimeout(context.WithoutCancel(ctx), 10*time.Second)
	defer txStop()
	j, err := s.ledger.Enqueue(txCtx, owner, in, hash, s.profile, s.queueLimit)
	if err != nil && !expected(err) {
		s.fault.Store(true)
		s.stop()
		return Job{}, ErrUnavailable
	}
	if err == nil {
		s.notify()
	}
	return j, err
}

func (s *Service) Cancel(ctx context.Context, owner, id string) (Job, error) {
	if err := ctx.Err(); err != nil {
		return Job{}, err
	}
	if s.fault.Load() || s.ctx.Err() != nil {
		return Job{}, ErrUnavailable
	}
	txCtx, txStop := context.WithTimeout(context.WithoutCancel(ctx), 10*time.Second)
	defer txStop()
	j, err := s.ledger.Cancel(txCtx, owner, id)
	if err != nil && !expected(err) {
		s.fault.Store(true)
		s.stop()
		return Job{}, ErrUnavailable
	}
	if err == nil && j.CancelRequested && !j.Status.Terminal() {
		s.mu.Lock()
		if s.activeID == id && s.cancelActive != nil {
			close(s.cancelActive)
			s.cancelActive = nil
		}
		s.mu.Unlock()
	}
	return j, err
}

func (s *Service) loop() {
	for {
		if s.ctx.Err() != nil {
			return
		}
		ex, err := s.ledger.Claim(s.ctx, s.epoch)
		if err != nil {
			if !errors.Is(err, ErrUnavailable) {
				s.fault.Store(true)
			}
			return
		}
		if ex == nil {
			select {
			case <-s.ctx.Done():
				return
			case <-s.wake:
			}
			continue
		}
		cancel := make(chan struct{})
		s.mu.Lock()
		s.activeID = ex.JobID
		s.cancelActive = cancel
		s.mu.Unlock()
		// Close the Claim/active-registration race using the durable job, not an
		// in-memory cancellation cache. No owner needs to be exposed to Runner.
		checkCtx, checkStop := context.WithTimeout(context.Background(), 5*time.Second)
		requested, checkErr := s.ledger.CancelRequested(checkCtx, *ex)
		checkStop()
		var r Outcome
		if checkErr != nil {
			r = Outcome{Quiescent: true, ErrorCode: "dispatch_unknown"}
			s.fault.Store(true)
			s.stop()
		} else if requested {
			r = Outcome{Quiescent: true, CleanExit: true, NotStarted: true}
		} else {
			if observed, ok := s.runner.(ObservedRunner); ok {
				r = observed.RunObserved(s.ctx, *ex, cancel, func(b ProcessBinding) error {
					ctx, stop := context.WithTimeout(context.Background(), 10*time.Second)
					defer stop()
					err := s.ledger.RecordBinding(ctx, *ex, b)
					if err != nil {
						s.fault.Store(true)
						s.stop()
					}
					return err
				})
			} else {
				r = s.runner.Run(s.ctx, *ex, cancel)
			}
		}
		s.mu.Lock()
		s.activeID = ""
		s.cancelActive = nil
		s.mu.Unlock()
		ctx, stop := context.WithTimeout(context.Background(), 10*time.Second)
		err = s.ledger.Finish(ctx, *ex, r)
		stop()
		if err != nil || s.fault.Load() {
			s.fault.Store(true)
			s.stop()
			return
		}
		if !r.Quiescent {
			s.fault.Store(true)
			s.stop()
			return
		}
	}
}
