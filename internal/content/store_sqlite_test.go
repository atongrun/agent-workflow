//go:build sqliteintegration && (linux || darwin)

package content

import (
	"bytes"
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"testing"

	_ "modernc.org/sqlite"
)

func sqliteStore(t *testing.T) (*Store, string) {
	t.Helper()
	dir := filepath.Join(t.TempDir(), "ledger")
	s, err := OpenStore(dir)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = s.Close() })
	return s, dir
}
func sqliteInput(t *testing.T, id string) (Input, string) {
	t.Helper()
	in, h, err := ParseInput([]byte(`{"requestId":"` + id + `","capability":"shortpost","payloadSchema":"shortpost.input.v1","opaquePayload":{"example":"fixture"}}`))
	if err != nil {
		t.Fatal(err)
	}
	return in, h
}
func submitSQLite(t *testing.T, s *Store, owner string, limit int) Job {
	t.Helper()
	in, h := sqliteInput(t, newID())
	j, err := s.Enqueue(context.Background(), owner, in, h, fixtureProfile(), limit)
	if err != nil {
		t.Fatal(err)
	}
	return j
}

func TestSQLiteReceiptOwnershipCapacityAndLock(t *testing.T) {
	s, dir := sqliteStore(t)
	ctx := context.Background()
	if duplicate, err := OpenStore(dir); err == nil {
		duplicate.Close()
		t.Fatal("two executors can own same ledger")
	}
	bin, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	child := exec.Command(bin, "-test.run=^TestSQLiteLockHelper$")
	child.Env = []string{"PATH=/usr/bin:/bin", "TMPDIR=" + os.TempDir(), "AWF_CONTENT_SQLITE_TEST_DIR=" + dir}
	if err := child.Run(); err == nil {
		t.Fatal("another process acquired the ledger")
	} else {
		var exit *exec.ExitError
		if !errors.As(err, &exit) || exit.ExitCode() != 42 {
			t.Fatalf("ownership helper failed unexpectedly: %v", err)
		}
	}
	in, h := sqliteInput(t, fixtureID)
	var wg sync.WaitGroup
	jobs := make(chan Job, 32)
	errs := make(chan error, 32)
	for i := 0; i < 32; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			j, err := s.Enqueue(ctx, "owner-a", in, h, fixtureProfile(), 2)
			jobs <- j
			errs <- err
		}()
	}
	wg.Wait()
	close(jobs)
	close(errs)
	for err := range errs {
		if err != nil {
			t.Fatal(err)
		}
	}
	var first Job
	for j := range jobs {
		if first.JobID == "" {
			first = j
		}
		if first.JobID != j.JobID {
			t.Fatal("duplicate request reserved multiple jobs")
		}
	}
	if _, err := s.Enqueue(ctx, "owner-a", in, "different", fixtureProfile(), 2); !errors.Is(err, ErrConflict) {
		t.Fatal(err)
	}
	other, err := s.Enqueue(ctx, "owner-b", in, h, fixtureProfile(), 2)
	if err != nil || other.JobID == first.JobID {
		t.Fatal("owners share idempotency scope")
	}
	newInput, newHash := sqliteInput(t, newID())
	if _, err := s.Enqueue(ctx, "owner-a", newInput, newHash, fixtureProfile(), 2); !errors.Is(err, ErrQueueFull) {
		t.Fatal(err)
	}
	if _, err := s.Get(ctx, "owner-b", first.JobID); !errors.Is(err, ErrNotFound) {
		t.Fatal("cross-owner GET")
	}
	if _, err := s.Cancel(ctx, "owner-b", first.JobID); !errors.Is(err, ErrNotFound) {
		t.Fatal("cross-owner cancel")
	}
	if _, err := s.List(ctx, "owner-b", first.JobID, 1); !errors.Is(err, ErrNotFound) {
		t.Fatal("cross-owner cursor")
	}
	if j, err := s.Cancel(ctx, "owner-a", first.JobID); err != nil || j.Status != Cancelled {
		t.Fatal("queued cancellation blocked by capacity")
	}
	if _, err := s.Enqueue(ctx, "owner-a", newInput, newHash, fixtureProfile(), 2); err != nil {
		t.Fatal("cancel did not free slot")
	}
	for _, name := range []string{"content.db", "content.lock", "content.db-wal", "content.db-shm"} {
		info, err := os.Stat(filepath.Join(dir, name))
		if err == nil && info.Mode().Perm()&0077 != 0 {
			t.Fatalf("unsafe permissions %s: %v", name, info.Mode())
		}
	}
}

func TestSQLiteLockHelper(t *testing.T) {
	dir := os.Getenv("AWF_CONTENT_SQLITE_TEST_DIR")
	if dir == "" {
		return
	}
	s, err := OpenStore(dir)
	if err != nil {
		os.Exit(42)
	}
	s.Close()
	os.Exit(0)
}

func TestSQLiteExactArtifactAtomicFailureAndFence(t *testing.T) {
	s, _ := sqliteStore(t)
	ctx := context.Background()
	j := submitSQLite(t, s, "owner", 4)
	ex, err := s.Claim(ctx, newID())
	if err != nil || ex == nil {
		t.Fatal(err)
	}
	if err := s.RecordBinding(ctx, *ex, ProcessBinding{PID: 123, StartToken: "1001", SessionRef: "fixture-session"}); err != nil {
		t.Fatal(err)
	}
	stale := *ex
	stale.ExecutionID = newID()
	if err := s.Finish(ctx, stale, fixtureSuccess()); !errors.Is(err, ErrFence) {
		t.Fatal("stale attempt committed")
	}
	// Abort during final status write, after artifact insertion, must roll back
	// all of it. This tests a real SQLite transaction rather than a mock.
	_, err = s.db.Exec(`CREATE TRIGGER fixture_fail BEFORE UPDATE OF status ON jobs WHEN NEW.status='succeeded' BEGIN SELECT RAISE(ABORT,'fixture final write failure'); END`)
	if err != nil {
		t.Fatal(err)
	}
	r := fixtureSuccess()
	r.RawArtifact = []byte("{\n \"example\" : \"fixture\"\n}")
	a := artifactFor(r.RawArtifact)
	r.Artifact = &a
	if err := s.Finish(ctx, *ex, r); err == nil {
		t.Fatal("injected final write succeeded")
	}
	got, err := s.Get(ctx, "owner", j.JobID)
	if err != nil || got.Status != Running || got.Result != nil {
		t.Fatalf("partial success published: %+v %v", got, err)
	}
	var artifacts int
	if err := s.db.QueryRow(`SELECT count(*) FROM artifacts`).Scan(&artifacts); err != nil || artifacts != 0 {
		t.Fatal("artifact insert was not rolled back")
	}
	if _, err := s.db.Exec(`DROP TRIGGER fixture_fail`); err != nil {
		t.Fatal(err)
	}
	if err := s.Finish(ctx, *ex, r); err != nil {
		t.Fatal(err)
	}
	got, err = s.Get(ctx, "owner", j.JobID)
	if err != nil || got.Status != Succeeded || got.Result == nil || got.Result.SHA256 != a.SHA256 {
		t.Fatal("success receipt missing")
	}
	var stored []byte
	if err := s.db.QueryRow(`SELECT raw FROM artifacts WHERE job_id=?`, j.JobID).Scan(&stored); err != nil || !bytes.Equal(stored, r.RawArtifact) {
		t.Fatal("artifact bytes changed")
	}
	if err := s.Finish(ctx, *ex, r); !errors.Is(err, ErrFence) {
		t.Fatal("duplicate finish accepted")
	}
}

func TestSQLiteCancelCompletionRace(t *testing.T) {
	s, _ := sqliteStore(t)
	ctx := context.Background()
	for i := 0; i < 30; i++ {
		j := submitSQLite(t, s, "owner", 4)
		ex, err := s.Claim(ctx, newID())
		if err != nil || ex == nil {
			t.Fatal(err)
		}
		var wg sync.WaitGroup
		var cancelJob Job
		var cancelErr, finishErr error
		wg.Add(2)
		go func() { defer wg.Done(); cancelJob, cancelErr = s.Cancel(ctx, "owner", j.JobID) }()
		go func() { defer wg.Done(); finishErr = s.Finish(ctx, *ex, fixtureSuccess()) }()
		wg.Wait()
		if cancelErr != nil || finishErr != nil {
			t.Fatalf("race errors %v %v", cancelErr, finishErr)
		}
		got, err := s.Get(ctx, "owner", j.JobID)
		if err != nil {
			t.Fatal(err)
		}
		if got.Status == Succeeded {
			if cancelJob.Status != Succeeded || got.Result == nil {
				t.Fatal("cancel intent committed before success but result published")
			}
		} else if got.Status == Cancelled {
			if got.Result != nil || !got.CancelRequested || got.NativeStopReason != "completed" {
				t.Fatal("cancelled job lost native reason or published result")
			}
		} else {
			t.Fatalf("unexpected race status %s", got.Status)
		}
	}
}

func TestSQLiteRestartUnknownAndExplicitRecovery(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "ledger")
	s, err := OpenStore(dir)
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	first := submitSQLite(t, s, "owner", 4)
	queued := submitSQLite(t, s, "owner", 4)
	ex, err := s.Claim(ctx, newID())
	if err != nil || ex == nil {
		t.Fatal(err)
	}
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	s, err = OpenStore(dir)
	if err != nil {
		t.Fatal(err)
	}
	j, err := s.Get(ctx, "owner", first.JobID)
	if err != nil || j.Status != NeedsVerification || j.ErrorCode != "restart_unknown" {
		t.Fatalf("restart did not fence: %+v %v", j, err)
	}
	if _, err := s.Claim(ctx, newID()); !errors.Is(err, ErrUnavailable) {
		t.Fatal("uncertain old process did not pause execution")
	}
	r, err := s.InspectRecovery(ctx)
	if err != nil || !r.Halted || len(r.UnknownAttempts) != 1 || r.QueuedCount != 1 {
		t.Fatalf("recovery report: %+v %v", r, err)
	}
	if err := s.RecoverExecution(ctx, r.RecoveryToken, false); !errors.Is(err, ErrInvalid) {
		t.Fatal("implicit recovery")
	}
	if err := s.RecoverExecution(ctx, "0000000000000000000000000000000000000000000000000000000000000000", true); !errors.Is(err, ErrConflict) {
		t.Fatal("stale recovery token")
	}
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	s, err = OpenStore(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	if halted, err := s.Halted(ctx); err != nil || !halted {
		t.Fatal("restart silently cleared halt")
	}
	if err := s.RecoverExecution(ctx, r.RecoveryToken, true); err != nil {
		t.Fatal(err)
	}
	next, err := s.Claim(ctx, newID())
	if err != nil || next == nil || next.JobID != queued.JobID {
		t.Fatal("recovery requeued unknown or lost undispatched job")
	}
	j, err = s.Get(ctx, "owner", first.JobID)
	if err != nil || j.Status != NeedsVerification {
		t.Fatal("recovery changed unknown outcome")
	}
}

func TestSQLitePaginationDoesNotExposeResults(t *testing.T) {
	s, _ := sqliteStore(t)
	ctx := context.Background()
	for i := 0; i < 3; i++ {
		submitSQLite(t, s, "owner", 4)
	}
	ex, err := s.Claim(ctx, newID())
	if err != nil || ex == nil {
		t.Fatal(err)
	}
	if err := s.Finish(ctx, *ex, fixtureSuccess()); err != nil {
		t.Fatal(err)
	}
	page, err := s.List(ctx, "owner", "", 2)
	if err != nil || len(page.Jobs) != 2 || page.NextCursor == "" {
		t.Fatal("first page")
	}
	next, err := s.List(ctx, "owner", page.NextCursor, 2)
	if err != nil || len(next.Jobs) != 1 || next.NextCursor != "" {
		t.Fatal("next page")
	}
	for _, j := range append(page.Jobs, next.Jobs...) {
		if j.Result != nil {
			t.Fatal("list exposed full result")
		}
	}
}
