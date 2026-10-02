package pi

import (
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"testing"
	"time"
)

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
