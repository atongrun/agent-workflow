// awf runs the Go control Host or calls its authenticated REST API.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/atongrun/agent-workflow/internal/host"
	"github.com/atongrun/agent-workflow/internal/lifecycle"
)

func main() {
	if handled, err := lifecycle.Forward(os.Args[1:]); handled {
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		return
	}
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
func run(args []string) error {
	if len(args) == 0 {
		return fmt.Errorf("usage: awf host --config host.json | awf request METHOD /v1/path [JSON] | awf doctor [--json] | awf install | awf init | awf pair [--status | --retry] | awf start | awf stop | awf update [--version vX.Y.Z] | awf version")
	}
	switch args[0] {
	case "host":
		flags := flag.NewFlagSet("host", flag.ContinueOnError)
		file := flags.String("config", "host.json", "Host configuration path")
		if err := flags.Parse(args[1:]); err != nil {
			return err
		}
		cfg, err := host.LoadConfig(*file)
		if err != nil {
			return err
		}
		if cfg.Listen == "" {
			cfg.Listen = "127.0.0.1:7070"
		}
		app, err := host.New(cfg)
		if err != nil {
			return err
		}
		defer app.Close()
		server := &http.Server{Addr: cfg.Listen, Handler: app.Handler(), ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 90 * time.Second}
		ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
		defer stop()
		go func() {
			<-ctx.Done()
			shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
			defer cancel()
			_ = server.Shutdown(shutdown)
		}()
		fmt.Fprintf(os.Stderr, "AWF Host listening on %s\n", cfg.Listen)
		err = server.ListenAndServe()
		if err == http.ErrServerClosed {
			return nil
		}
		return err
	case "request":
		if len(args) < 3 {
			return fmt.Errorf("usage: awf request METHOD /v1/path [JSON]")
		}
		base, token := os.Getenv("AWF_HOST_URL"), os.Getenv("AWF_HOST_TOKEN")
		if base == "" || token == "" {
			return fmt.Errorf("AWF_HOST_URL and AWF_HOST_TOKEN required")
		}
		if !strings.HasPrefix(args[2], "/v1/") {
			return fmt.Errorf("request path must begin /v1/")
		}
		var body io.Reader
		if len(args) > 3 {
			var v any
			if err := json.Unmarshal([]byte(args[3]), &v); err != nil {
				return err
			}
			body = bytes.NewBufferString(args[3])
		}
		req, err := http.NewRequest(args[1], strings.TrimRight(base, "/")+args[2], body)
		if err != nil {
			return err
		}
		req.Header.Set("Authorization", "Bearer "+token)
		req.Header.Set("Content-Type", "application/json")
		client := &http.Client{Timeout: 30 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
		res, err := client.Do(req)
		if err != nil {
			return err
		}
		defer res.Body.Close()
		_, err = io.Copy(os.Stdout, io.LimitReader(res.Body, 16*1024*1024))
		if err != nil {
			return err
		}
		if res.StatusCode >= 300 {
			return fmt.Errorf("Host returned HTTP %d", res.StatusCode)
		}
		return nil
	case "doctor", "install", "init", "pair", "start", "stop", "update", "version", "install-protocol", "_serve", "_install":
		return lifecycle.Run(args, os.Stdin, os.Stdout)
	default:
		return fmt.Errorf("unknown command %q", args[0])
	}
}
