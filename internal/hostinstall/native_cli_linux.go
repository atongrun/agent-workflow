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
	case "linux-service-check":
		if len(args) != 2 {
			return true, errors.New("service check requires host or magpie")
		}
		r, err := os.OpenRoot("/")
		if err != nil {
			return true, err
		}
		defer r.Close()
		a := &nativeAdapter{root: r, owner: 0}
		return true, a.serviceCheck(args[1], true)
	case "install", "init", "start", "stop", "update":
	default:
		return false, nil
	}
	ctx, cancel := signal.NotifyContext(ctx, os.Interrupt, syscall.SIGTERM)
	defer cancel()
	f := flag.NewFlagSet("awf "+args[0], flag.ContinueOnError)
	f.SetOutput(progress)
	manifest := f.String("manifest", "", "explicit reviewed Linux release manifest")
	version := f.String("version", "", "optional exact Linux update tag; otherwise use linux-host-v1")
	yes := f.Bool("yes", false, "approve installation or initialization")
	preview := f.Bool("allow-prerelease", false, "approve this Linux preview and future linux-host-v1 previews")
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
	if args[0] != "update" && *version != "" {
		return true, errors.New("--version belongs to update")
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
	var current nativeReceipt
	unchanged := false
	if args[0] == "update" {
		current, err = a.installed(ctx)
		if err != nil {
			return true, err
		}
		m, err = readUpdateManifest(ctx, *manifest, *version, nil, o)
		if err != nil {
			return true, err
		}
		if err := validateUpdateTarget(m, current.Manifest); err != nil {
			return true, err
		}
		unchanged = manifestDigest(m) == manifestDigest(current.Manifest)
		fmt.Fprintf(out, "AWF Linux update: %s -> %s\n", current.Manifest.Version, m.Version)
	} else if args[0] == "install" {
		if *manifest == "" {
			return true, errors.New("install requires --manifest; use the public Linux bootstrap")
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
	}
	if args[0] == "install" || args[0] == "update" {
		a.allowPrerelease, err = approveLinuxPreview(m.Version, *preview || current.AllowPrerelease, *yes, in, out)
		if err != nil {
			return true, err
		}
	}
	if args[0] == "install" || args[0] == "init" || args[0] == "update" {
		if !*yes && !unchanged {
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
		if err := a.update(ctx, m); err != nil {
			return true, err
		}
		fmt.Fprintf(out, "AWF %s verified. Current Pi, configuration, credentials and task state retained.\n", m.Version)
	}
	return true, nil
}

const nativeUsage = "usage: awf install --manifest FILE [--yes] [--allow-prerelease] | awf update [--version TAG | --manifest FILE] [--yes] [--allow-prerelease] | awf init [--yes] | awf start [--enable] | awf stop | awf version | awf host-install plan|doctor --manifest FILE [--json] | awf host --config FILE"
