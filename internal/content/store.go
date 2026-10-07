package content

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"time"
)

// Ledger is separate from AWF host state and locks. Claim must durably fence an
// attempt before returning it to a caller that can start a process.
type Ledger interface {
	Enqueue(context.Context, string, Input, string, Profile, int) (Job, error)
	Get(context.Context, string, string) (Job, error)
	List(context.Context, string, string, int) (Page, error)
	Cancel(context.Context, string, string) (Job, error)
	Claim(context.Context, string) (*Execute, error)
	Finish(context.Context, Execute, Outcome) error
	CancelRequested(context.Context, Execute) (bool, error)
	RecordBinding(context.Context, Execute, ProcessBinding) error
	Halted(context.Context) (bool, error)
}

type Store struct {
	db     *sql.DB
	unlock func() error
}

const schema = `
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT OR IGNORE INTO meta VALUES ('halted','0');
CREATE TABLE IF NOT EXISTS jobs (
 ordinal INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL UNIQUE,
 owner TEXT NOT NULL, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
 input_json BLOB NOT NULL, profile_json BLOB NOT NULL,
 capability TEXT NOT NULL, payload_schema TEXT NOT NULL,
 status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 cancel_requested INTEGER NOT NULL DEFAULT 0,
 execution_id TEXT NOT NULL DEFAULT '', owner_epoch TEXT NOT NULL DEFAULT '',
 native_session_ref TEXT NOT NULL DEFAULT '', native_stop_reason TEXT NOT NULL DEFAULT '',
 error_code TEXT NOT NULL DEFAULT '', UNIQUE(owner,request_id)
);
CREATE INDEX IF NOT EXISTS jobs_owner_ordinal ON jobs(owner,ordinal);
CREATE INDEX IF NOT EXISTS jobs_status_ordinal ON jobs(status,ordinal);
CREATE TABLE IF NOT EXISTS attempts (
 execution_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(job_id),
 owner_epoch TEXT NOT NULL, dispatched_at TEXT NOT NULL, finished_at TEXT,
 stop_reason TEXT NOT NULL DEFAULT '', error_code TEXT NOT NULL DEFAULT '',
 bridge_pid INTEGER NOT NULL DEFAULT 0, bridge_start_token TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS artifacts (
 job_id TEXT PRIMARY KEY REFERENCES jobs(job_id), schema TEXT NOT NULL,
 media_type TEXT NOT NULL, bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, raw BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
 ordinal INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES jobs(job_id),
 status TEXT NOT NULL, at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pending_recovery (
 execution_id TEXT PRIMARY KEY REFERENCES attempts(execution_id),
 job_id TEXT NOT NULL REFERENCES jobs(job_id)
);
CREATE TABLE IF NOT EXISTS recovery_history (
 ordinal INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT NOT NULL, at TEXT NOT NULL
);
PRAGMA user_version=1;
`

// OpenStore expects the CGO-free sqlite driver to be registered by the caller.
// It acquires its own Linux lock before touching schema or recovering attempts.
func OpenStore(dir string) (_ *Store, err error) {
	if !filepath.IsAbs(dir) {
		return nil, fmt.Errorf("content data directory must be absolute")
	}
	dir = filepath.Clean(dir)
	if err := validateDataDirectory(dir, true); err != nil {
		return nil, err
	}
	if err := os.MkdirAll(dir, 0700); err != nil {
		return nil, err
	}
	if err := validateDataDirectory(dir, false); err != nil {
		return nil, err
	}
	unlock, err := acquireContentLock(filepath.Join(dir, "content.lock"))
	if err != nil {
		return nil, err
	}
	defer func() {
		if err != nil {
			_ = unlock()
		}
	}()
	path := filepath.Join(dir, "content.db")
	for _, sidecar := range []string{path + "-wal", path + "-shm"} {
		info, e := os.Lstat(sidecar)
		if e != nil && !os.IsNotExist(e) {
			return nil, e
		}
		if e == nil && validateContentFile(info) != nil {
			return nil, fmt.Errorf("unsafe content ledger sidecar")
		}
	}
	f, err := privateFile(path)
	if err != nil {
		return nil, err
	}
	if err = f.Close(); err != nil {
		return nil, err
	}
	dsn := (&url.URL{Scheme: "file", Path: path}).String()
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		return nil, err
	}
	defer func() {
		if err != nil {
			_ = db.Close()
		}
	}()
	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	for _, q := range []string{"PRAGMA journal_mode=WAL", "PRAGMA synchronous=FULL", "PRAGMA foreign_keys=ON", "PRAGMA busy_timeout=5000"} {
		if _, err = db.ExecContext(ctx, q); err != nil {
			return nil, err
		}
	}
	var version, synchronous, foreignKeys int
	var journalMode string
	for q, dst := range map[string]any{"PRAGMA user_version": &version, "PRAGMA synchronous": &synchronous, "PRAGMA foreign_keys": &foreignKeys, "PRAGMA journal_mode": &journalMode} {
		if err = db.QueryRowContext(ctx, q).Scan(dst); err != nil {
			return nil, err
		}
	}
	if (version != 0 && version != 1) || synchronous != 2 || foreignKeys != 1 || journalMode != "wal" {
		return nil, fmt.Errorf("unsupported content ledger configuration")
	}
	if _, err = db.ExecContext(ctx, schema); err != nil {
		return nil, err
	}
	s := &Store{db: db, unlock: unlock}
	if err = s.recover(ctx); err != nil {
		return nil, err
	}
	return s, nil
}

func (s *Store) Close() error {
	err := s.db.Close()
	if e := s.unlock(); err == nil {
		err = e
	}
	return err
}

// A restart cannot prove that native descendants of a previous bridge are gone.
// Persist an admission halt alongside restart_unknown; operator verification is
// required before an offline recovery. Never clear it on a later restart.
func (s *Store) recover(ctx context.Context) error {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	at := timestamp()
	result, err := tx.ExecContext(ctx, `INSERT INTO events(job_id,status,at) SELECT job_id,?,? FROM jobs WHERE status IN ('running','cancelling')`, NeedsVerification, at)
	if err != nil {
		return err
	}
	n, err := result.RowsAffected()
	if err != nil {
		return err
	}
	if n > 0 {
		if _, err = tx.ExecContext(ctx, `INSERT OR IGNORE INTO pending_recovery(execution_id,job_id) SELECT execution_id,job_id FROM jobs WHERE status IN ('running','cancelling')`); err != nil {
			return err
		}
		if _, err = tx.ExecContext(ctx, `UPDATE jobs SET status=?,error_code='restart_unknown',updated_at=? WHERE status IN ('running','cancelling')`, NeedsVerification, at); err != nil {
			return err
		}
		if _, err = tx.ExecContext(ctx, `UPDATE attempts SET finished_at=?,error_code='restart_unknown' WHERE finished_at IS NULL`, at); err != nil {
			return err
		}
		if _, err = tx.ExecContext(ctx, `UPDATE meta SET value='1' WHERE key='halted'`); err != nil {
			return err
		}
	}
	return tx.Commit()
}

func (s *Store) Halted(ctx context.Context) (bool, error) {
	var value string
	err := s.db.QueryRowContext(ctx, `SELECT value FROM meta WHERE key='halted'`).Scan(&value)
	return value != "0", err
}

func txHalted(ctx context.Context, tx *sql.Tx) error {
	var value string
	if err := tx.QueryRowContext(ctx, `SELECT value FROM meta WHERE key='halted'`).Scan(&value); err != nil {
		return err
	}
	if value != "0" {
		return ErrUnavailable
	}
	return nil
}

const jobColumns = `j.job_id,j.request_id,j.capability,j.payload_schema,j.status,j.created_at,j.updated_at,j.cancel_requested,j.execution_id,j.owner_epoch,j.native_session_ref,j.native_stop_reason,j.error_code`

func scanSummary(row interface{ Scan(...any) error }) (Job, error) {
	var j Job
	err := row.Scan(summaryDestinations(&j)...)
	if errors.Is(err, sql.ErrNoRows) {
		err = ErrNotFound
	}
	return j, err
}

func summaryDestinations(j *Job) []any {
	return []any{&j.JobID, &j.RequestID, &j.Capability, &j.PayloadSchema, &j.Status, &j.CreatedAt, &j.UpdatedAt, &j.CancelRequested, &j.ExecutionID, &j.OwnerEpoch, &j.NativeSessionRef, &j.NativeStopReason, &j.ErrorCode}
}

type querier interface {
	QueryRowContext(context.Context, string, ...any) *sql.Row
}

func getJob(ctx context.Context, q querier, owner, id string) (Job, error) {
	j, err := scanSummary(q.QueryRowContext(ctx, `SELECT `+jobColumns+` FROM jobs j WHERE j.owner=? AND j.job_id=?`, owner, id))
	if err != nil {
		return Job{}, err
	}
	if j.Status == Succeeded {
		var a Artifact
		var raw []byte
		if err := q.QueryRowContext(ctx, `SELECT schema,media_type,bytes,sha256,raw FROM artifacts WHERE job_id=?`, id).Scan(&a.Schema, &a.MediaType, &a.Bytes, &a.SHA256, &raw); err != nil {
			return Job{}, err
		}
		a.DataBase64 = base64.StdEncoding.EncodeToString(raw)
		if _, err := VerifyArtifact(a); err != nil {
			return Job{}, err
		}
		j.Result = &a
	}
	return j, nil
}

func (s *Store) Get(ctx context.Context, owner, id string) (Job, error) {
	return getJob(ctx, s.db, owner, id)
}

func (s *Store) Enqueue(ctx context.Context, owner string, in Input, fingerprint string, profile Profile, limit int) (Job, error) {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return Job{}, err
	}
	defer tx.Rollback()
	// Replay works even when admission is halted or the queue is full.
	var id, oldFingerprint string
	err = tx.QueryRowContext(ctx, `SELECT job_id,fingerprint FROM jobs WHERE owner=? AND request_id=?`, owner, in.RequestID).Scan(&id, &oldFingerprint)
	if err == nil {
		if oldFingerprint != fingerprint {
			return Job{}, ErrConflict
		}
		j, err := getJob(ctx, tx, owner, id)
		if err != nil {
			return Job{}, err
		}
		return j, tx.Commit()
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return Job{}, err
	}
	if err := txHalted(ctx, tx); err != nil {
		return Job{}, err
	}
	var count int
	if err := tx.QueryRowContext(ctx, `SELECT count(*) FROM jobs WHERE status IN ('queued','running','cancelling')`).Scan(&count); err != nil {
		return Job{}, err
	}
	if count >= limit {
		return Job{}, ErrQueueFull
	}
	input, err := marshalFrame(in)
	if err != nil {
		return Job{}, err
	}
	p, err := json.Marshal(profile)
	if err != nil {
		return Job{}, err
	}
	at := timestamp()
	j := Job{JobID: newID(), RequestID: in.RequestID, Capability: in.Capability, PayloadSchema: in.PayloadSchema, Status: Queued, CreatedAt: at, UpdatedAt: at}
	if _, err := tx.ExecContext(ctx, `INSERT INTO jobs(job_id,owner,request_id,fingerprint,input_json,profile_json,capability,payload_schema,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)`, j.JobID, owner, in.RequestID, fingerprint, input, p, in.Capability, in.PayloadSchema, Queued, at, at); err != nil {
		return Job{}, err
	}
	if _, err := tx.ExecContext(ctx, `INSERT INTO events(job_id,status,at) VALUES(?,?,?)`, j.JobID, Queued, at); err != nil {
		return Job{}, err
	}
	return j, tx.Commit()
}

func (s *Store) List(ctx context.Context, owner, before string, limit int) (Page, error) {
	var ordinal int64 = 9223372036854775807
	if before != "" {
		if err := s.db.QueryRowContext(ctx, `SELECT ordinal FROM jobs WHERE owner=? AND job_id=?`, owner, before).Scan(&ordinal); err != nil {
			if errors.Is(err, sql.ErrNoRows) {
				return Page{}, ErrNotFound
			}
			return Page{}, err
		}
	}
	rows, err := s.db.QueryContext(ctx, `SELECT `+jobColumns+` FROM jobs j WHERE owner=? AND ordinal<? ORDER BY ordinal DESC LIMIT ?`, owner, ordinal, limit+1)
	if err != nil {
		return Page{}, err
	}
	defer rows.Close()
	p := Page{Jobs: []Job{}}
	for rows.Next() {
		j, err := scanSummary(rows)
		if err != nil {
			return Page{}, err
		}
		p.Jobs = append(p.Jobs, j)
	}
	if err := rows.Err(); err != nil {
		return Page{}, err
	}
	if len(p.Jobs) > limit {
		p.Jobs = p.Jobs[:limit]
		p.NextCursor = p.Jobs[limit-1].JobID
	}
	return p, nil
}

func (s *Store) Cancel(ctx context.Context, owner, id string) (Job, error) {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return Job{}, err
	}
	defer tx.Rollback()
	j, err := getJob(ctx, tx, owner, id)
	if err != nil {
		return Job{}, err
	}
	if j.Status.Terminal() {
		return j, tx.Commit()
	}
	j.CancelRequested = true
	j.UpdatedAt = timestamp()
	if j.Status == Queued {
		j.Status = Cancelled
	} else {
		j.Status = Cancelling
	}
	if _, err := tx.ExecContext(ctx, `UPDATE jobs SET status=?,cancel_requested=1,updated_at=? WHERE owner=? AND job_id=?`, j.Status, j.UpdatedAt, owner, id); err != nil {
		return Job{}, err
	}
	if _, err := tx.ExecContext(ctx, `INSERT INTO events(job_id,status,at) VALUES(?,?,?)`, id, j.Status, j.UpdatedAt); err != nil {
		return Job{}, err
	}
	return j, tx.Commit()
}

func (s *Store) Claim(ctx context.Context, epoch string) (*Execute, error) {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()
	if err := txHalted(ctx, tx); err != nil {
		return nil, err
	}
	var id string
	var input, profile []byte
	err = tx.QueryRowContext(ctx, `SELECT job_id,input_json,profile_json FROM jobs WHERE status='queued' AND cancel_requested=0 ORDER BY ordinal LIMIT 1`).Scan(&id, &input, &profile)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, tx.Commit()
	}
	if err != nil {
		return nil, err
	}
	var in Input
	var p Profile
	if strictJSON(input, &in) != nil || strictJSON(profile, &p) != nil || validProfile(p) != nil {
		return nil, ErrInvalid
	}
	at := timestamp()
	ex := Execute{Version: 1, Type: "execute", JobID: id, ExecutionID: newID(), OwnerEpoch: epoch, Capability: in.Capability, PayloadSchema: in.PayloadSchema, OpaquePayload: in.OpaquePayload, ModelRef: p.ModelRef, ResourceVersions: p.ResourceVersions, DeadlineAt: time.Now().Add(time.Duration(p.TimeoutSeconds) * time.Second).UTC().Format(time.RFC3339Nano)}
	if _, err := tx.ExecContext(ctx, `UPDATE jobs SET status=?,execution_id=?,owner_epoch=?,updated_at=? WHERE job_id=? AND status='queued'`, Running, ex.ExecutionID, epoch, at, id); err != nil {
		return nil, err
	}
	if _, err := tx.ExecContext(ctx, `INSERT INTO attempts(execution_id,job_id,owner_epoch,dispatched_at) VALUES(?,?,?,?)`, ex.ExecutionID, id, epoch, at); err != nil {
		return nil, err
	}
	if _, err := tx.ExecContext(ctx, `INSERT INTO events(job_id,status,at) VALUES(?,?,?)`, id, Running, at); err != nil {
		return nil, err
	}
	if err := tx.Commit(); err != nil {
		return nil, err
	}
	return &ex, nil
}

func (s *Store) CancelRequested(ctx context.Context, ex Execute) (bool, error) {
	var requested bool
	var id, epoch string
	if err := s.db.QueryRowContext(ctx, `SELECT cancel_requested,execution_id,owner_epoch FROM jobs WHERE job_id=?`, ex.JobID).Scan(&requested, &id, &epoch); err != nil {
		return false, err
	}
	if id != ex.ExecutionID || epoch != ex.OwnerEpoch {
		return false, ErrFence
	}
	return requested, nil
}

func (s *Store) RecordBinding(ctx context.Context, ex Execute, b ProcessBinding) error {
	if b.PID <= 0 || b.StartToken == "" || len(b.StartToken) > 32 || len(b.SessionRef) > 512 {
		return ErrInvalid
	}
	for _, c := range b.StartToken {
		if c < '0' || c > '9' {
			return ErrInvalid
		}
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	var id, epoch, oldStart string
	var status Status
	var oldPID int
	err = tx.QueryRowContext(ctx, `SELECT j.execution_id,j.owner_epoch,j.status,a.bridge_pid,a.bridge_start_token FROM jobs j JOIN attempts a ON a.execution_id=j.execution_id WHERE j.job_id=?`, ex.JobID).Scan(&id, &epoch, &status, &oldPID, &oldStart)
	if err != nil {
		return err
	}
	if id != ex.ExecutionID || epoch != ex.OwnerEpoch || (status != Running && status != Cancelling) || (oldPID != 0 && (oldPID != b.PID || oldStart != b.StartToken)) {
		return ErrFence
	}
	if _, err := tx.ExecContext(ctx, `UPDATE attempts SET bridge_pid=?,bridge_start_token=? WHERE execution_id=? AND owner_epoch=?`, b.PID, b.StartToken, ex.ExecutionID, ex.OwnerEpoch); err != nil {
		return err
	}
	if b.SessionRef != "" {
		if _, err := tx.ExecContext(ctx, `UPDATE jobs SET native_session_ref=?,updated_at=? WHERE job_id=? AND execution_id=? AND owner_epoch=?`, b.SessionRef, timestamp(), ex.JobID, ex.ExecutionID, ex.OwnerEpoch); err != nil {
			return err
		}
	}
	return tx.Commit()
}

func terminalOutcome(cancelRequested bool, r Outcome) (Status, string) {
	if r.NotStarted && r.Quiescent {
		if cancelRequested {
			return Cancelled, ""
		}
		code := r.ErrorCode
		if code == "" {
			code = "dispatch_failed"
		}
		return Failed, code
	}
	if !r.Quiescent || !r.CleanExit {
		return NeedsVerification, "process_unknown"
	}
	if r.ErrorCode != "" && r.ErrorCode != "execution_failed" && r.ErrorCode != "invalid_input" {
		return NeedsVerification, r.ErrorCode
	}
	switch r.StopReason {
	case "completed":
		if r.ErrorCode != "" || r.Artifact == nil {
			return NeedsVerification, "missing_artifact"
		}
		b, err := VerifyArtifact(*r.Artifact)
		if err != nil || !bytes.Equal(b, r.RawArtifact) {
			return NeedsVerification, "bridge_protocol"
		}
		if cancelRequested {
			return Cancelled, ""
		}
		return Succeeded, ""
	case "aborted":
		return Cancelled, ""
	case "failed":
		if cancelRequested {
			return Cancelled, r.ErrorCode
		}
		if r.ErrorCode == "" {
			return Failed, "execution_failed"
		}
		return Failed, r.ErrorCode
	default:
		return NeedsVerification, "missing_settlement"
	}
}

func (s *Store) Finish(ctx context.Context, ex Execute, r Outcome) error {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	var status Status
	var executionID, epoch string
	var cancelled bool
	if err := tx.QueryRowContext(ctx, `SELECT status,execution_id,owner_epoch,cancel_requested FROM jobs WHERE job_id=?`, ex.JobID).Scan(&status, &executionID, &epoch, &cancelled); err != nil {
		return err
	}
	if executionID != ex.ExecutionID || epoch != ex.OwnerEpoch || (status != Running && status != Cancelling) {
		return ErrFence
	}
	status, code := terminalOutcome(cancelled, r)
	at := timestamp()
	if r.Artifact != nil {
		a := r.Artifact
		verified, verifyErr := VerifyArtifact(*a)
		if verifyErr == nil && bytes.Equal(verified, r.RawArtifact) {
			if _, err := tx.ExecContext(ctx, `INSERT INTO artifacts(job_id,schema,media_type,bytes,sha256,raw) VALUES(?,?,?,?,?,?)`, ex.JobID, a.Schema, a.MediaType, a.Bytes, a.SHA256, r.RawArtifact); err != nil {
				return err
			}
		}
	}
	if _, err := tx.ExecContext(ctx, `UPDATE jobs SET status=?,updated_at=?,native_session_ref=?,native_stop_reason=?,error_code=? WHERE job_id=? AND execution_id=? AND owner_epoch=?`, status, at, r.SessionRef, r.StopReason, code, ex.JobID, ex.ExecutionID, ex.OwnerEpoch); err != nil {
		return err
	}
	if _, err := tx.ExecContext(ctx, `UPDATE attempts SET finished_at=?,stop_reason=?,error_code=? WHERE execution_id=? AND owner_epoch=?`, at, r.StopReason, code, ex.ExecutionID, ex.OwnerEpoch); err != nil {
		return err
	}
	if _, err := tx.ExecContext(ctx, `INSERT INTO events(job_id,status,at) VALUES(?,?,?)`, ex.JobID, status, at); err != nil {
		return err
	}
	if !r.Quiescent {
		if _, err := tx.ExecContext(ctx, `INSERT INTO pending_recovery(execution_id,job_id) VALUES(?,?)`, ex.ExecutionID, ex.JobID); err != nil {
			return err
		}
		if _, err := tx.ExecContext(ctx, `UPDATE meta SET value='1' WHERE key='halted'`); err != nil {
			return err
		}
	}
	return tx.Commit()
}
