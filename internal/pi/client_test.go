package pi

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

func TestOversizedRPCFixture(t *testing.T) {
	if os.Getenv("AWF_TEST_OVERSIZED_RPC") != "1" {
		return
	}
	block := bytes.Repeat([]byte("x"), 1024*1024)
	for range 17 {
		if _, err := os.Stdout.Write(block); err != nil {
			break
		}
	}
	_, _ = io.Copy(io.Discard, os.Stdin)
	os.Exit(0)
}

func TestOversizedRPCStopsTransportAndUnblocksPending(t *testing.T) {
	binary, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(binary, "-test.run=^TestOversizedRPCFixture$")
	cmd.Env = append(os.Environ(), "AWF_TEST_OVERSIZED_RPC=1")
	in, err := cmd.StdinPipe()
	if err != nil {
		t.Fatal(err)
	}
	out, err := cmd.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	client := &Client{cmd: cmd, stdin: in, pending: map[string]chan response{}, ui: map[string]bool{}, done: make(chan struct{})}
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = client.Close() })
	pending := &PendingCall{client: client, id: "original-request", typ: "get_messages", response: make(chan response, 1)}
	client.pending[pending.id] = pending.response
	go client.read(out)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if _, err := pending.Wait(ctx); err == nil || !strings.Contains(err.Error(), "token too long") {
		t.Fatalf("oversized transport did not report its read failure: %v", err)
	}
	if client.Alive() {
		t.Fatal("broken JSONL transport still reported alive")
	}
}

func TestCloseWaitsForFinalCallback(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("POSIX process fixture")
	}
	dir := t.TempDir()
	binary := filepath.Join(dir, "pi")
	if err := os.WriteFile(binary, []byte("#!/bin/sh\ncat >/dev/null\n"), 0700); err != nil {
		t.Fatal(err)
	}
	entered := make(chan struct{})
	release := make(chan struct{})
	client, err := Start(Config{Binary: binary, Directory: dir, SessionDirectory: filepath.Join(dir, "sessions"), OnEvent: func(json.RawMessage) { close(entered); <-release }})
	if err != nil {
		t.Fatal(err)
	}
	closed := make(chan error, 1)
	go func() { closed <- client.Close() }()
	select {
	case <-entered:
	case <-time.After(5 * time.Second):
		t.Fatal("exit callback not reached")
	}
	select {
	case <-closed:
		t.Fatal("Close returned before final callback")
	case <-time.After(20 * time.Millisecond):
	}
	close(release)
	if err := <-closed; err != nil {
		t.Fatal(err)
	}
	if client.Alive() {
		t.Fatal("closed client still alive")
	}
}
