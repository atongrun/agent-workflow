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

	"github.com/atongrun/agent-workflow/internal/content"
	"github.com/atongrun/agent-workflow/internal/contentsql"
	"github.com/atongrun/agent-workflow/internal/host"
	"github.com/atongrun/agent-workflow/internal/lifecycle"
	"path/filepath"
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
		return fmt.Errorf("usage: awf host --config host.json [--content-config content.json] | awf content inspect|recover --content-config content.json | awf request METHOD /v1/path [JSON] | awf doctor [--json] | awf install | awf init | awf pair [--status | --retry] | awf start | awf stop | awf update [--version vX.Y.Z] | awf version")
	}
	switch args[0] {
	case "content":
		return contentsql.RecoveryCLI(args[1:], os.Stdout)
	case "host":
		flags := flag.NewFlagSet("host", flag.ContinueOnError)
		file := flags.String("config", "host.json", "Host configuration path")
		contentFile := flags.String("content-config", "", "Optional private content configuration path")
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
		var contentService *content.Service
		if *contentFile != "" {
			cc, err := content.LoadConfig(*contentFile)
			if err != nil {
				return fmt.Errorf("content configuration rejected")
			}
			if content.ValidateCredentialIsolation(cc.Credentials, os.Getenv(cfg.TokenEnv), os.Getenv(cfg.ExtensionTokenEnv)) != nil {
				return fmt.Errorf("content credentials must be distinct from AWF Host and extension credentials")
			}
			hostDir, err := filepath.Abs(cfg.DataDir)
			if err != nil || filepath.Clean(cc.DataDir) == filepath.Clean(hostDir) {
				return fmt.Errorf("content dataDir must be separate from AWF dataDir")
			}
			ledger, err := contentsql.Open(cc.DataDir)
			if err != nil {
				return fmt.Errorf("content ledger unavailable: %w", err)
			}
			defer ledger.Close()
			contentService, err = content.NewService(ledger, cc.Bridge, cc.Profile, cc.QueueLimit)
			if err != nil {
				return err
			}
			defer contentService.Close()
			cfg.ContentHandler, err = contentService.Handler(cc.Credentials)
			if err != nil {
				return fmt.Errorf("content credentials rejected")
			}
		}
		app, err := host.New(cfg)
		if err != nil {
			return err
		}
		defer func() {
			if contentService != nil {
				contentService.Close()
			}
			app.Close()
		}()
		if contentService != nil {
			contentService.Start()
		}
		server := &http.Server{Addr: cfg.Listen, Handler: app.Handler(), ReadHeaderTimeout: 10 * time.Second, ReadTimeout: 30 * time.Second, IdleTimeout: 90 * time.Second, MaxHeaderBytes: 16384}
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
