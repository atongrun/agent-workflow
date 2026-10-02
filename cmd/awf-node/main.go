// awf-node connects an authenticated AWF host to an existing native OpenCode
// server. It does not install tools or run a shell, Git, PowerShell, or WSL.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/atongrun/agent-workflow/internal/node"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "awf-node:", err)
		os.Exit(1)
	}
}
func run() error {
	config := flag.String("config", "", "path to node JSON configuration")
	listen := flag.String("listen", "", "optional listen address override")
	flag.Parse()
	if *config == "" {
		return errors.New("-config is required")
	}
	f, err := os.Open(*config)
	if err != nil {
		return err
	}
	defer f.Close()
	var cfg node.Config
	decoder := json.NewDecoder(io.LimitReader(f, 1<<20))
	decoder.DisallowUnknownFields()
	if err = decoder.Decode(&cfg); err != nil {
		return err
	}
	if err = decoder.Decode(new(any)); err != io.EOF {
		return errors.New("configuration must contain exactly one JSON object")
	}
	if v := os.Getenv("AWF_NODE_TOKEN"); v != "" {
		cfg.Token = v
	}
	if v := os.Getenv("OPENCODE_SERVER_USERNAME"); v != "" {
		cfg.OpenCodeUsername = v
	}
	if v := os.Getenv("OPENCODE_SERVER_PASSWORD"); v != "" {
		cfg.OpenCodePassword = v
	}
	if *listen != "" {
		cfg.ListenAddress = *listen
	}
	if cfg.ListenAddress == "" {
		cfg.ListenAddress = "127.0.0.1:8788"
	}
	handler, err := node.New(cfg)
	if err != nil {
		return err
	}
	defer handler.(*node.Server).Close()
	server := &http.Server{Addr: cfg.ListenAddress, Handler: handler, ReadHeaderTimeout: 10 * time.Second, ReadTimeout: 30 * time.Second, WriteTimeout: 60 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 16 << 10}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	done := make(chan error, 1)
	go func() { done <- server.ListenAndServe() }()
	fmt.Fprintln(os.Stderr, "awf-node listening on", cfg.ListenAddress)
	select {
	case err = <-done:
		if errors.Is(err, http.ErrServerClosed) {
			return nil
		}
		return err
	case <-ctx.Done():
		shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		return server.Shutdown(shutdown)
	}
}
