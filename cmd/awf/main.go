// awf runs the Go control Host or calls its authenticated REST API.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/atongrun/agent-workflow/internal/durablebridge"
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
func run(args []string) (runErr error) {
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
		ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
		defer stop()
		var worker *durablebridge.Worker
		var workerDone <-chan struct{}
		var content http.Handler
		if cfg.DurableConfig != "" {
			durableConfig, err := durablebridge.LoadConfig(cfg.DurableConfig)
			if err != nil {
				return err
			}
			protected := []string{os.Getenv(cfg.TokenEnv), os.Getenv(cfg.ExtensionTokenEnv)}
			for _, node := range cfg.Nodes {
				protected = append(protected, os.Getenv(node.TokenEnv))
			}
			worker, err = durablebridge.Start(ctx, durableConfig, protected...)
			if err != nil {
				return err
			}
			app.BindDurableCatalogMaintenance(worker.CatalogMaintenance)
			workerDone, content = worker.Done(), worker.Handler()
			defer func() {
				shutdown, cancel := context.WithTimeout(context.Background(), time.Duration(durableConfig.ShutdownSeconds)*time.Second)
				defer cancel()
				if err := worker.Close(shutdown); err != nil {
					runErr = errors.Join(runErr, err)
				}
			}()
		}
		server := &http.Server{Addr: cfg.Listen, Handler: composeHostHandler(app.Handler(), content), ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 90 * time.Second}
		fmt.Fprintf(os.Stderr, "AWF Host listening on %s\n", cfg.Listen)
		serve := server.ListenAndServe
		if cfg.Bot != nil {
			botListener, err := net.Listen("tcp", cfg.Bot.Listen)
			if err != nil {
				return err
			}
			botServer := &http.Server{Handler: app.BotHandler(), ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 90 * time.Second}
			fmt.Fprintf(os.Stderr, "AWF bot API listening on %s\n", cfg.Bot.Listen)
			serve = func() error {
				errCh := make(chan error, 2)
				go func() { errCh <- server.ListenAndServe() }()
				go func() { errCh <- botServer.Serve(botListener) }()
				err := <-errCh
				shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
				defer cancel()
				_ = server.Shutdown(shutdown)
				_ = botServer.Shutdown(shutdown)
				return err
			}
		}
		return serveHost(ctx, server, serve, workerDone, 10*time.Second)
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

type hostShutdownResult struct {
	err          error
	workerExited bool
}

// serveHost waits for HTTP draining before run returns and its deferred worker
// cleanup can release the single Durable lease. On a bounded drain timeout it
// force-closes client connections, returns that failure, and lets service
// control-group cleanup finish any handler that refused request cancellation.
func serveHost(ctx context.Context, server *http.Server, serve func() error, workerDone <-chan struct{}, timeout time.Duration) error {
	trigger, stop := context.WithCancel(ctx)
	defer stop()
	stopped := make(chan hostShutdownResult, 1)
	go func() {
		result := hostShutdownResult{}
		select {
		case <-trigger.Done():
		case <-workerDone:
			result.workerExited = ctx.Err() == nil
		}
		shutdown, cancel := context.WithTimeout(context.Background(), timeout)
		err := server.Shutdown(shutdown)
		timedOut := errors.Is(err, context.DeadlineExceeded)
		cancel()
		if timedOut {
			if closeErr := server.Close(); closeErr != nil && !errors.Is(closeErr, http.ErrServerClosed) {
				err = errors.Join(err, closeErr)
			}
		}
		if errors.Is(err, http.ErrServerClosed) && !timedOut {
			err = nil
		}
		result.err = err
		stopped <- result
	}()

	serveErr := serve()
	// A listener failure has no signal or worker transition to wake the
	// shutdown goroutine. Stop it and join before returning to deferred close.
	stop()
	result := <-stopped
	if serveErr != nil && !errors.Is(serveErr, http.ErrServerClosed) {
		if result.err != nil {
			return errors.Join(serveErr, result.err)
		}
		return serveErr
	}
	if result.err != nil {
		return result.err
	}
	if result.workerExited {
		return durablebridge.ErrWorkerExited
	}
	return nil
}

// Native content and the existing Host share one listener while retaining
// separate credentials and route ownership. No second TCP server is opened.
func composeHostHandler(host, content http.Handler) http.Handler {
	if content == nil {
		return host
	}
	mux := http.NewServeMux()
	mux.Handle(durablebridge.PublicPrefix+"/", content)
	mux.Handle("/", host)
	return mux
}
