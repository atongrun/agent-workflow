//go:build linux

package hostinstall

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"strings"
	"syscall"
)

// HandleNative owns only Linux machine lifecycle commands. Windows dispatch and
// its installer channel remain in lifecycle. No native path override is exposed.
func HandleNative(ctx context.Context, args []string, in io.Reader, out, progress io.Writer) (bool, error) {
	if len(args) == 0 {
		return true, errors.New(nativeUsage)
	}
	switch args[0] {
	case "help", "--help", "-h":
		fmt.Fprintln(out, nativeUsage)
		return true, nil
	case "version":
		fmt.Fprintln(out, NativeBuildIdentity().Version)
		return true, nil
	case "linux-install-protocol":
		fmt.Fprintln(out, "1")
		return true, nil
	case "linux-build-identity":
		return true, json.NewEncoder(out).Encode(NativeBuildIdentity())
	case "install", "init", "start", "stop", "update":
	default:
		return false, nil
	}
	ctx, cancel := signal.NotifyContext(ctx, os.Interrupt, syscall.SIGTERM)
	defer cancel()
	f := flag.NewFlagSet("awf "+args[0], flag.ContinueOnError)
	f.SetOutput(progress)
	manifest := f.String("manifest", "", "explicit reviewed Linux release manifest")
	yes := f.Bool("yes", false, "approve installation or initialization")
	preview := f.Bool("allow-prerelease", false, "approve a Linux prerelease")
	enable := f.Bool("enable", false, "enable service autostart with start")
	if err := f.Parse(args[1:]); err != nil {
		return true, err
	}
	if f.NArg() != 0 {
		return true, errors.New("unexpected lifecycle arguments")
	}
	if args[0] != "install" && args[0] != "update" && (*manifest != "" || *preview) {
		return true, errors.New("manifest and prerelease options belong to install/update")
	}
	if args[0] != "start" && *enable {
		return true, errors.New("--enable belongs to start")
	}
	o := &Progress{Out: progress, TTY: false}
	a, err := openNative(o)
	if err != nil {
		return true, err
	}
	defer a.root.Close()
	var m Manifest
	if args[0] == "install" || args[0] == "update" {
		if *manifest == "" {
			return true, errors.New("an explicit reviewed Linux manifest is required; no channel is published")
		}
		file, err := os.Open(*manifest)
		if err != nil {
			return true, errors.New("manifest unreadable")
		}
		b, err := io.ReadAll(io.LimitReader(file, MaxManifestBytes+1))
		file.Close()
		if err != nil {
			return true, errors.New("manifest unreadable")
		}
		m, err = ParseManifest(b)
		if err != nil {
			return true, err
		}
		if strings.Contains(m.Version, "-rc.") && !*preview {
			return true, errors.New("Linux prerelease requires --allow-prerelease")
		}
	}
	if args[0] == "install" || args[0] == "init" || args[0] == "update" {
		if !*yes {
			fmt.Fprintf(out, "AWF %s changes this machine's fixed AWF paths. Continue? [y/N] ", args[0])
			var answer string
			if _, err := fmt.Fscanln(in, &answer); err != nil || (answer != "y" && answer != "Y") {
				return true, errors.New("operation declined; no machine changes made")
			}
		}
	}
	// Fresh preflight is read-only and precedes even creation of the operation lock.
	if args[0] == "install" {
		if err := a.fresh(); err != nil {
			return true, err
		}
	}
	lock, err := a.lock()
	if err != nil {
		return true, err
	}
	defer lock.Close()
	switch args[0] {
	case "install":
		generation, r, cleanup, err := prepareNativeRuntime(ctx, m, o)
		if err != nil {
			return true, err
		}
		defer cleanup()
		if err := a.installPrepared(ctx, m, generation, r); err != nil {
			return true, err
		}
		fmt.Fprintln(out, "AWF programs installed. Run awf init, then awf start. Services have not started.")
	case "init":
		if err := a.initialize(ctx); err != nil {
			return true, err
		}
		fmt.Fprintln(out, "AWF initialized with independent service state and empty project/model configuration. Run awf start; authenticate the service's Magpie account explicitly when needed.")
	case "start":
		return true, a.start(ctx, *enable)
	case "stop":
		return true, a.stop(ctx)
	case "update":
		return true, a.update(ctx, m)
	}
	return true, nil
}

const nativeUsage = "usage: awf install|update --manifest FILE [--yes] [--allow-prerelease] | awf init [--yes] | awf start [--enable] | awf stop | awf version | awf host-install plan|doctor --manifest FILE [--json] | awf host --config FILE"
