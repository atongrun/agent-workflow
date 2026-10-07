// awf-content is an isolated development/test entry point. Production content
// routes are embedded in awf host with --content-config, sharing its listener.
package main

import (
	"context"
	"flag"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/atongrun/agent-workflow/internal/content"
	"github.com/atongrun/agent-workflow/internal/contentsql"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func run() error {
	file := flag.String("config", "", "Private content configuration path")
	listen := flag.String("listen", "127.0.0.1:7071", "Loopback development listener")
	flag.Parse()
	if *file == "" || !content.ValidLoopbackListen(*listen) {
		return fmt.Errorf("private --config and loopback --listen required")
	}
	cfg, err := content.LoadConfig(*file)
	if err != nil {
		return fmt.Errorf("content configuration rejected")
	}
	store, err := contentsql.Open(cfg.DataDir)
	if err != nil {
		return fmt.Errorf("content ledger unavailable: %w", err)
	}
	defer store.Close()
	service, err := content.NewService(store, cfg.Bridge, cfg.Profile, cfg.QueueLimit)
	if err != nil {
		return err
	}
	defer service.Close()
	handler, err := service.Handler(cfg.Credentials)
	if err != nil {
		return fmt.Errorf("content credentials rejected")
	}
	server := &http.Server{Addr: *listen, Handler: handler, ReadHeaderTimeout: 10 * time.Second, ReadTimeout: 30 * time.Second, WriteTimeout: 30 * time.Second, IdleTimeout: 90 * time.Second, MaxHeaderBytes: 16384}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
	}()
	service.Start()
	err = server.ListenAndServe()
	if err == http.ErrServerClosed {
		return nil
	}
	return err
}
