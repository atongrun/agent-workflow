package content

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
)

type RecoveryReport struct {
	Halted          bool              `json:"halted"`
	QueuedCount     int               `json:"queuedCount"`
	UnknownAttempts []RecoveryAttempt `json:"unknownAttempts"`
	RecoveryToken   string            `json:"recoveryToken,omitempty"`
}

type RecoveryAttempt struct {
	Job
	BridgePID        int    `json:"bridgePid,omitempty"`
	BridgeStartToken string `json:"bridgeStartToken,omitempty"`
}

// Inspection omits input, owner credentials and artifacts. OpenStore owns the
// independent offline lock, so inspect/recover cannot race a running GoHost.
func recoveryReport(ctx context.Context, tx *sql.Tx) (RecoveryReport, error) {
	r := RecoveryReport{UnknownAttempts: []RecoveryAttempt{}}
	var halted string
	if err := tx.QueryRowContext(ctx, `SELECT value FROM meta WHERE key='halted'`).Scan(&halted); err != nil {
		return r, err
	}
	r.Halted = halted != "0"
	if err := tx.QueryRowContext(ctx, `SELECT count(*) FROM jobs WHERE status='queued'`).Scan(&r.QueuedCount); err != nil {
		return r, err
	}
	rows, err := tx.QueryContext(ctx, `SELECT `+jobColumns+`,a.bridge_pid,a.bridge_start_token FROM jobs j JOIN pending_recovery p ON p.job_id=j.job_id JOIN attempts a ON a.execution_id=p.execution_id ORDER BY j.ordinal`)
	if err != nil {
		return r, err
	}
	for rows.Next() {
		var j RecoveryAttempt
		destinations := append(summaryDestinations(&j.Job), &j.BridgePID, &j.BridgeStartToken)
		err := rows.Scan(destinations...)
		if err != nil {
			rows.Close()
			return r, err
		}
		r.UnknownAttempts = append(r.UnknownAttempts, j)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return r, err
	}
	if r.Halted {
		b, err := json.Marshal(r)
		if err != nil {
			return r, err
		}
		sum := sha256.Sum256(b)
		r.RecoveryToken = hex.EncodeToString(sum[:])
	}
	return r, nil
}

func (s *Store) InspectRecovery(ctx context.Context) (RecoveryReport, error) {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return RecoveryReport{}, err
	}
	defer tx.Rollback()
	r, err := recoveryReport(ctx, tx)
	if err != nil {
		return r, err
	}
	return r, tx.Commit()
}

// RecoverExecution requires an explicit operator attestation and the current
// inspection token. It clears only the pause, preserving unknown jobs and all
// data. It never launches a process or requeues any dispatched attempt.
func (s *Store) RecoverExecution(ctx context.Context, token string, confirmedQuiescent bool) error {
	if !confirmedQuiescent || len(token) != 64 {
		return ErrInvalid
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	r, err := recoveryReport(ctx, tx)
	if err != nil {
		return err
	}
	if !r.Halted || token != r.RecoveryToken {
		return ErrConflict
	}
	if _, err := tx.ExecContext(ctx, `INSERT INTO recovery_history(token,at) VALUES(?,?)`, token, timestamp()); err != nil {
		return err
	}
	if _, err := tx.ExecContext(ctx, `DELETE FROM pending_recovery`); err != nil {
		return err
	}
	if _, err := tx.ExecContext(ctx, `UPDATE meta SET value='0' WHERE key='halted'`); err != nil {
		return err
	}
	return tx.Commit()
}
