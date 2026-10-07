package contentsql

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"time"

	"github.com/atongrun/agent-workflow/internal/content"
)

// RecoveryCLI is an offline operator path, not an HTTP/browser control.
func RecoveryCLI(args []string, out io.Writer) error {
	if len(args) == 0 || (args[0] != "inspect" && args[0] != "recover") {
		return fmt.Errorf("usage: awf content inspect|recover --content-config FILE [--confirm-quiescent --recovery-token TOKEN]")
	}
	f := flag.NewFlagSet("content "+args[0], flag.ContinueOnError)
	file := f.String("content-config", "", "Private content configuration path")
	confirm := f.Bool("confirm-quiescent", false, "Attest all reported old native processes are stopped")
	token := f.String("recovery-token", "", "Token from current offline inspection")
	if err := f.Parse(args[1:]); err != nil {
		return err
	}
	if *file == "" || f.NArg() != 0 {
		return content.ErrInvalid
	}
	if args[0] == "recover" && (!*confirm || len(*token) != 64) {
		return content.ErrInvalid
	}
	cfg, err := content.LoadConfig(*file)
	if err != nil {
		return fmt.Errorf("content configuration rejected")
	}
	s, err := Open(cfg.DataDir)
	if err != nil {
		return fmt.Errorf("content ledger unavailable: %w", err)
	}
	defer s.Close()
	ctx, stop := context.WithTimeout(context.Background(), 10*time.Second)
	defer stop()
	if args[0] == "recover" {
		if err := s.RecoverExecution(ctx, *token, *confirm); err != nil {
			return err
		}
	}
	r, err := s.InspectRecovery(ctx)
	if err != nil {
		return err
	}
	return json.NewEncoder(out).Encode(r)
}
