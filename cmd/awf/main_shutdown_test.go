package main

import (
	"context"
	"errors"
	"net"
	"net/http"
	"testing"
	"time"
)

func TestServeHostWaitsForDelayedHandlerDrain(t *testing.T) {
	entered := make(chan struct{})
	release := make(chan struct{})
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(entered)
		<-release
		w.WriteHeader(http.StatusNoContent)
	})}
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() {
		done <- serveHost(ctx, server, func() error { return server.Serve(listener) }, nil, time.Second)
	}()

	clientDone := make(chan struct{})
	go func() {
		response, err := http.Get("http://" + listener.Addr().String())
		if err == nil {
			response.Body.Close()
		}
		close(clientDone)
	}()
	select {
	case <-entered:
	case <-time.After(time.Second):
		t.Fatal("handler did not start")
	}
	cancel()
	select {
	case err := <-done:
		t.Fatal("server returned before handler drained", err)
	case <-time.After(30 * time.Millisecond):
	}
	close(release)
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("server did not finish after handler drained")
	}
	select {
	case <-clientDone:
	case <-time.After(time.Second):
		t.Fatal("drained handler did not complete its client")
	}
}

func TestServeHostForceClosesAfterDrainTimeout(t *testing.T) {
	entered := make(chan struct{})
	release := make(chan struct{})
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(entered)
		<-release // Deliberately ignores request cancellation.
	})}
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() {
		done <- serveHost(ctx, server, func() error { return server.Serve(listener) }, nil, 25*time.Millisecond)
	}()
	request, err := http.NewRequest(http.MethodGet, "http://"+listener.Addr().String(), nil)
	if err != nil {
		t.Fatal(err)
	}
	clientDone := make(chan struct{})
	go func() { _, _ = http.DefaultClient.Do(request); close(clientDone) }()
	select {
	case <-entered:
	case <-time.After(time.Second):
		t.Fatal("handler did not start")
	}
	cancel()
	select {
	case err := <-done:
		if !errors.Is(err, context.DeadlineExceeded) {
			t.Fatal("expected bounded shutdown failure", err)
		}
	case <-time.After(time.Second):
		t.Fatal("force close did not bound shutdown")
	}
	close(release)
	select {
	case <-clientDone:
	case <-time.After(time.Second):
		t.Fatal("force close left client connected")
	}
}

func TestServeHostJoinsShutdownAfterListenFailure(t *testing.T) {
	occupied, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer occupied.Close()
	server := &http.Server{Addr: occupied.Addr().String(), Handler: http.NotFoundHandler()}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	if err := serveHost(ctx, server, server.ListenAndServe, nil, time.Second); err == nil || errors.Is(err, http.ErrServerClosed) {
		t.Fatal("listener bind failure was hidden", err)
	}
}
