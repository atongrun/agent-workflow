package content

import (
	"bufio"
	"bytes"
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

type ProcessRunner struct {
	Executable string            `json:"executable"`
	Args       []string          `json:"args"`
	Env        map[string]string `json:"env"`
}

func (r ProcessRunner) Validate() error {
	if !filepath.IsAbs(r.Executable) || len(r.Args) > 64 || len(r.Env) > 128 {
		return ErrInvalid
	}
	for _, a := range r.Args {
		if len(a) > 4096 || strings.ContainsRune(a, 0) {
			return ErrInvalid
		}
	}
	for k, v := range r.Env {
		if k == "" || strings.ContainsAny(k, "=\x00") || strings.ContainsRune(v, 0) || len(k) > 128 || len(v) > 16384 {
			return ErrInvalid
		}
	}
	return nil
}

func (r ProcessRunner) Run(ctx context.Context, ex Execute, cancel <-chan struct{}) Outcome {
	return r.RunObserved(ctx, ex, cancel, nil)
}

func (r ProcessRunner) RunObserved(ctx context.Context, ex Execute, cancel <-chan struct{}, observe func(ProcessBinding) error) Outcome {
	select {
	case <-cancel:
		return Outcome{NotStarted: true, Quiescent: true, CleanExit: true}
	default:
	}
	encodedExecute, encodeErr := marshalFrame(ex)
	if encodeErr != nil || len(encodedExecute)+1 > MaxFrameBytes {
		return Outcome{NotStarted: true, Quiescent: true, ErrorCode: "frame_too_large"}
	}
	if r.Validate() != nil || ctx.Err() != nil {
		return Outcome{Quiescent: true, ErrorCode: "dispatch_unknown"}
	}
	deadline, err := time.Parse(time.RFC3339Nano, ex.DeadlineAt)
	if err != nil || !deadline.After(time.Now()) {
		return Outcome{Quiescent: true, ErrorCode: "deadline_exceeded"}
	}
	cmd := exec.Command(r.Executable, r.Args...)
	if err := configureProcess(cmd); err != nil {
		return Outcome{Quiescent: true, ErrorCode: "process_unsupported"}
	}
	// Inherit no HTTP credentials, host environment or provider tokens. The
	// private operator explicitly configures the bridge's required environment.
	cmd.Env = []string{"PATH=/usr/local/bin:/usr/bin:/bin"}
	keys := make([]string, 0, len(r.Env))
	for k := range r.Env {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		if k == "PATH" {
			cmd.Env[0] = "PATH=" + r.Env[k]
		} else {
			cmd.Env = append(cmd.Env, k+"="+r.Env[k])
		}
	}
	stdin, err := cmd.StdinPipe()
	if err != nil {
		return Outcome{Quiescent: true, ErrorCode: "process_start_failed"}
	}
	defer stdin.Close()
	stdout, outWriter, err := os.Pipe()
	if err != nil {
		return Outcome{Quiescent: true, ErrorCode: "process_start_failed"}
	}
	defer stdout.Close()
	cmd.Stdout = outWriter
	cmd.Stderr = io.Discard
	if err = cmd.Start(); err != nil {
		_ = outWriter.Close()
		return Outcome{Quiescent: true, ErrorCode: "process_start_failed"}
	}
	_ = outWriter.Close()
	wait := make(chan error, 1)
	go func() { wait <- cmd.Wait() }()
	frames := make(chan []byte, 1)
	readDone := make(chan error, 1)
	readCtx, stopRead := context.WithCancel(context.Background())
	defer stopRead()
	go func() {
		reader := bufio.NewReaderSize(stdout, MaxFrameBytes)
		for {
			line, e := reader.ReadSlice('\n')
			if e != nil {
				if e == io.EOF && len(line) == 0 {
					readDone <- nil
				} else {
					readDone <- ErrProtocol
				}
				return
			}
			if len(line) > MaxFrameBytes {
				readDone <- ErrProtocol
				return
			}
			line = bytes.TrimSuffix(line, []byte{'\n'})
			select {
			case frames <- append([]byte(nil), line...):
			case <-readCtx.Done():
				return
			}
		}
	}()
	writes := make(chan []byte, 2)
	writeErr := make(chan error, 1)
	writeCtx, stopWrite := context.WithCancel(context.Background())
	defer stopWrite()
	go func() {
		for {
			select {
			case <-writeCtx.Done():
				return
			case frame := <-writes:
				b := append(frame, '\n')
				_, e := io.Copy(stdin, bytes.NewReader(b))
				if e != nil {
					writeErr <- e
					return
				}
			}
		}
	}()
	protocol := NewProtocol(ex)
	timer := time.NewTimer(time.Until(deadline))
	defer timer.Stop()
	var grace *time.Timer
	var graceC <-chan time.Time
	var killTimer *time.Timer
	var killC <-chan time.Time
	var code string
	exited, readFinished, clean, forced := false, false, false, false
	ctxC := ctx.Done()
	cancelC := cancel
	sendCancel := func() {
		if grace != nil {
			return
		}
		b, _ := marshalFrame(CancelFrame{Version: 1, Type: "cancel", JobID: ex.JobID, ExecutionID: ex.ExecutionID, OwnerEpoch: ex.OwnerEpoch})
		writes <- b
		grace = time.NewTimer(5 * time.Second)
		graceC = grace.C
	}
	kill := func() {
		if forced {
			return
		}
		forced = true
		_ = terminateProcessGroup(cmd.Process.Pid)
		_ = stdin.Close()
		killTimer = time.NewTimer(2 * time.Second)
		killC = killTimer.C
	}
	defer func() {
		if grace != nil {
			grace.Stop()
		}
		if killTimer != nil {
			killTimer.Stop()
		}
	}()
	binding := ProcessBinding{PID: cmd.Process.Pid}
	if observe != nil {
		token, err := processStartToken(cmd.Process.Pid)
		binding.StartToken = token
		if err != nil || observe(binding) != nil {
			code = "binding_persistence_failed"
			kill()
		} else {
			writes <- encodedExecute
		}
	} else {
		writes <- encodedExecute
	}
	accept := func(frame []byte) {
		if protocol.Accept(frame) != nil {
			code = "bridge_protocol"
			kill()
			return
		}
		if observe != nil && protocol.result.SessionRef != "" && binding.SessionRef == "" {
			binding.SessionRef = protocol.result.SessionRef
			if observe(binding) != nil {
				code = "binding_persistence_failed"
				kill()
			}
		}
	}
	for !(exited && readFinished) {
		select {
		case frame := <-frames:
			accept(frame)
		case e := <-readDone:
			readFinished = true
			readDone = nil
			// A reader can finish after enqueueing its final frame. Drain it
			// before evaluating settlement, regardless of select ordering.
			for {
				select {
				case frame := <-frames:
					accept(frame)
				default:
					goto drained
				}
			}
		drained:
			if e != nil {
				code = "bridge_protocol"
				kill()
			}
		case e := <-wait:
			exited = true
			clean = e == nil
			wait = nil
			if processGroupAlive(cmd.Process.Pid) {
				code = "process_unknown"
				kill()
			}
		case <-cancelC:
			cancelC = nil
			sendCancel()
		case <-ctxC:
			ctxC = nil
			sendCancel()
		case <-timer.C:
			code = "deadline_exceeded"
			sendCancel()
		case <-graceC:
			graceC = nil
			if code == "" {
				code = "abort_timeout"
			}
			kill()
		case <-killC:
			rr := protocol.Result(false, false)
			rr.ErrorCode = "process_unknown"
			return rr
		case <-writeErr:
			writeErr = nil
			if !protocol.settled {
				code = "bridge_write_failed"
				kill()
			}
		}
	}
	quiescent := !processGroupAlive(cmd.Process.Pid)
	rr := protocol.Result(clean && !forced, quiescent)
	if code != "" {
		rr.ErrorCode = code
	}
	return rr
}

func (r ProcessRunner) String() string {
	return fmt.Sprintf("bridge executable %s", filepath.Base(r.Executable))
}
