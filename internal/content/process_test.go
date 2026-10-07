//go:build linux

package content

import (
	"bufio"
	"context"
	"encoding/json"
	"os"
	"strings"
	"testing"
	"time"
)

// These are isolated protocol-child fixtures. They never start Pi, read private
// content, contact a provider or establish native bridge acceptance.
func TestBridgeHelper(t *testing.T) {
	mode := os.Getenv("AWF_CONTENT_TEST_HELPER")
	if mode == "" {
		return
	}
	if os.Getenv("AWF_CONTENT_FIXTURE_PRIVATE_CREDENTIAL") != "" {
		os.Exit(8)
	}
	d := json.NewDecoder(bufio.NewReader(os.Stdin))
	var ex Execute
	if d.Decode(&ex) != nil {
		os.Exit(2)
	}
	enc := json.NewEncoder(os.Stdout)
	ready := frame(ex, 1, "ready")
	ready.NativeSessionRef = "fixture-session"
	_ = enc.Encode(ready)
	if mode == "cancel" || mode == "ignore_cancel" {
		var c CancelFrame
		if d.Decode(&c) != nil || c.Type != "cancel" || c.ExecutionID != ex.ExecutionID || c.OwnerEpoch != ex.OwnerEpoch {
			os.Exit(3)
		}
		if mode == "ignore_cancel" {
			time.Sleep(30 * time.Second)
			os.Exit(4)
		}
		e := frame(ex, 2, "settled")
		e.StopReason = "aborted"
		_ = enc.Encode(e)
		os.Exit(0)
	}
	a := artifactFor([]byte("{\n\"example\":\"fixture\"\n}"))
	if mode == "bad_hash" {
		a.SHA256 = "0000000000000000000000000000000000000000000000000000000000000000"
	}
	art := frame(ex, 2, "artifact")
	art.Artifact = &a
	_ = enc.Encode(art)
	if mode == "missing_settlement" {
		os.Exit(0)
	}
	e := frame(ex, 3, "settled")
	e.StopReason = "completed"
	_ = enc.Encode(e)
	if mode == "extra_frame" {
		_ = enc.Encode(e)
	}
	if mode == "exit_failure" {
		os.Exit(7)
	}
	os.Exit(0)
}

func helperRunner(t *testing.T, mode string) ProcessRunner {
	t.Helper()
	exe, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	return ProcessRunner{Executable: exe, Args: []string{"-test.run=^TestBridgeHelper$"}, Env: map[string]string{"AWF_CONTENT_TEST_HELPER": mode}}
}

func TestProcessFixtureEvidence(t *testing.T) {
	for _, mode := range []string{"success", "bad_hash", "missing_settlement", "extra_frame", "exit_failure"} {
		t.Run(mode, func(t *testing.T) {
			ex := fixtureExecute()
			ex.DeadlineAt = time.Now().Add(10 * time.Second).UTC().Format(time.RFC3339Nano)
			r := helperRunner(t, mode).Run(context.Background(), ex, make(chan struct{}))
			status, _ := terminalOutcome(false, r)
			want := NeedsVerification
			if mode == "success" {
				want = Succeeded
			}
			if status != want || !r.Quiescent {
				t.Fatalf("%s: %+v -> %s", mode, r, status)
			}
		})
	}
}

func TestProcessFixtureCancelAndBoundedAbort(t *testing.T) {
	ex := fixtureExecute()
	ex.DeadlineAt = time.Now().Add(15 * time.Second).UTC().Format(time.RFC3339Nano)
	for _, mode := range []string{"cancel", "ignore_cancel"} {
		t.Run(mode, func(t *testing.T) {
			cancel := make(chan struct{})
			timer := time.AfterFunc(100*time.Millisecond, func() { close(cancel) })
			defer timer.Stop()
			start := time.Now()
			r := helperRunner(t, mode).Run(context.Background(), ex, cancel)
			status, _ := terminalOutcome(true, r)
			if mode == "cancel" && (status != Cancelled || r.StopReason != "aborted") {
				t.Fatalf("cancel evidence: %+v %s", r, status)
			}
			if mode == "ignore_cancel" && (status != NeedsVerification || time.Since(start) > 8*time.Second) {
				t.Fatalf("abort not bounded: %+v %s", r, status)
			}
			if !r.Quiescent {
				t.Fatal("fixture process not cleaned up")
			}
		})
	}
}

func TestProcessDoesNotInheritServiceCredential(t *testing.T) {
	// A configured env snapshot contains exactly what the runner passes. The
	// helper verifies an inherited secret is absent rather than logging it.
	t.Setenv("AWF_CONTENT_FIXTURE_PRIVATE_CREDENTIAL", "must-not-inherit")
	ex := fixtureExecute()
	ex.DeadlineAt = time.Now().Add(10 * time.Second).UTC().Format(time.RFC3339Nano)
	r := helperRunner(t, "success").Run(context.Background(), ex, make(chan struct{}))
	if status, _ := terminalOutcome(false, r); status != Succeeded {
		t.Fatal(status)
	}
}

func TestOversizedExecuteDoesNotStartFixtureProcess(t *testing.T) {
	ex := fixtureExecute()
	ex.DeadlineAt = time.Now().Add(time.Second).UTC().Format(time.RFC3339Nano)
	ex.OpaquePayload = json.RawMessage(`{"example":"` + strings.Repeat("x", MaxFrameBytes) + `"}`)
	r := helperRunner(t, "success").Run(context.Background(), ex, make(chan struct{}))
	if !r.NotStarted || !r.Quiescent || r.ErrorCode != "frame_too_large" {
		t.Fatalf("oversized preflight: %+v", r)
	}
}

func TestObservedProcessFixtureRecordsOwnershipBeforeExecute(t *testing.T) {
	ex := fixtureExecute()
	ex.DeadlineAt = time.Now().Add(10 * time.Second).UTC().Format(time.RFC3339Nano)
	var bindings []ProcessBinding
	r := helperRunner(t, "success").RunObserved(context.Background(), ex, make(chan struct{}), func(b ProcessBinding) error {
		bindings = append(bindings, b)
		if b.PID <= 0 || b.StartToken == "" {
			t.Error("missing Go-observed process identity")
		}
		if b.SessionRef == "" {
			token, err := processStartToken(b.PID)
			if err != nil || token != b.StartToken {
				t.Errorf("identity changed before execution: %v", err)
			}
		}
		return nil
	})
	if status, _ := terminalOutcome(false, r); status != Succeeded || len(bindings) != 2 || bindings[1].SessionRef != "fixture-session" {
		t.Fatalf("bindings %+v, result %+v", bindings, r)
	}
}
