package lifecycle

import (
	"bytes"
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"

	"github.com/atongrun/agent-workflow/internal/node"
)

// Forward keeps the installed launcher immutable while versioned implementations
// evolve. Windows never has to overwrite its own running executable.
func Forward(args []string) (bool, error) {
	if runtime.GOOS != "windows" {
		return false, nil
	}
	root, e := DefaultRoot()
	if e != nil {
		return false, nil
	}
	exe, e := os.Executable()
	if e != nil {
		return false, e
	}
	if !strings.EqualFold(filepath.Clean(exe), filepath.Join(root, "bin", "awf.exe")) {
		return false, nil
	}
	if e = validateInstallRoot(root); e != nil {
		return true, e
	}
	p, e := current(root)
	if e != nil {
		return true, e
	}
	c := exec.Command(binary(root, p.Version), args...)
	c.Stdin = os.Stdin
	c.Stdout = os.Stdout
	c.Stderr = os.Stderr
	return true, c.Run()
}
func Run(args []string, in io.Reader, out io.Writer) error {
	if len(args) == 0 {
		return errors.New("missing lifecycle command")
	}
	if args[0] == "version" {
		fmt.Fprintln(out, Version)
		return nil
	}
	if args[0] == "update" {
		for _, s := range args[1:] {
			if s == "--all" || s == "-all" || strings.HasPrefix(s, "--all=") {
				return errors.New("awf update --all is not implemented; no AWF, Pi, or OpenCode tool was changed")
			}
		}
	}
	if runtime.GOOS != "windows" {
		return errors.New("managed init/pair/start/stop/update require native Windows; host and request remain available here")
	}
	root, e := DefaultRoot()
	if e != nil {
		return e
	}
	if args[0] == "_serve" {
		if len(args) != 1 {
			return errors.New("unexpected serve arguments")
		}
		if e = validateInstallRoot(root); e != nil {
			return e
		}
		return serve(root)
	}
	if args[0] == "_install" {
		return install(root, args[1:], out)
	}
	if e = validateInstallRoot(root); e != nil {
		return e
	}
	lock, e := exclusive(root)
	if e != nil {
		return e
	}
	defer lock.Close()
	switch args[0] {
	case "init":
		if _, e = current(root); e != nil {
			return errors.New("install AWF for this user before running init")
		}
		if st, err := os.Stat(filepath.Join(root, "bin", "awf.exe")); err != nil || !st.Mode().IsRegular() {
			return errors.New("the installed native launcher is missing")
		}
		return initialize(root, args[1:], in, out)
	case "pair":
		return pair(root, args[1:], in, out)
	case "start":
		if len(args) != 1 {
			return errors.New("usage: awf start")
		}
		return start(root, out)
	case "stop":
		if len(args) != 1 {
			return errors.New("usage: awf stop")
		}
		return stop(root, out)
	case "update":
		return updateWithInput(root, args[1:], in, out)
	}
	return errors.New("unknown lifecycle command")
}
func update(root string, args []string, out io.Writer) error {
	return updateWithInput(root, args, nil, out)
}
func updateWithInput(root string, args []string, in io.Reader, out io.Writer) error {
	f := flag.NewFlagSet("update", flag.ContinueOnError)
	f.SetOutput(out)
	version := f.String("version", "", "exact Go release tag; default follows the saved go-v1 channel without downgrading")
	allowPrerelease := f.Bool("allow-prerelease", false, "approve channel previews durably, or permit an explicitly pinned RC")
	pin := f.String("sha256", "", "optional independently verified archive SHA-256")
	if e := f.Parse(args); e != nil {
		return e
	}
	if f.NArg() != 0 {
		return errors.New("unexpected update arguments")
	}
	if e := validateReleaseRequest(*version, *allowPrerelease); e != nil {
		return e
	}
	if e := noPendingStartup(root); e != nil {
		return e
	}
	old, e := current(root)
	if e != nil {
		return e
	}
	selection, e := loadChannel(root)
	if e != nil {
		return e
	}
	cfg, e := loadConfig(root)
	if e != nil && !os.IsNotExist(e) {
		return e
	}
	initialized := e == nil
	if !initialized {
		if _, err := os.Stat(filepath.Join(root, "state")); !os.IsNotExist(err) {
			return errors.New("state exists without valid configuration; upgrade state is unknown")
		}
	}
	wasRunning := false
	if r, e := readRuntime(root); e == nil {
		if e = control(r, "GET", "/health"); e != nil {
			return e
		}
		wasRunning = true
	} else if !os.IsNotExist(e) {
		return e
	}
	if wasRunning && !initialized {
		return errors.New("runtime exists without a valid configuration; upgrade state is unknown")
	}
	// Gate before network access, then stop/gate again just before switching.
	if wasRunning {
		r, _ := readRuntime(root)
		if e = control(r, "POST", "/idle"); e != nil {
			return e
		}
	} else if initialized {
		l, e := node.OfflineIdle(cfg.Node)
		if e != nil {
			return e
		}
		l.Close()
	}
	ctx, client := context.Background(), releaseClient()
	target, e := resolveReleaseTarget(ctx, client, *version, runtime.GOARCH)
	if e != nil {
		return e
	}
	if order, err := compareReleaseVersions(target.Version, old.Version); err != nil {
		return err
	} else if order < 0 {
		return errors.New("selected release is older than the installed version; downgrade is blocked")
	}
	approved := *allowPrerelease
	if *version == "" {
		selection, e = approveChannelPreview(selection, target.Version, *allowPrerelease, in, out, interactiveUpdateInput(in))
		if e != nil {
			return e
		}
		approved = selection.PreviewApproved
	}
	v, e := stageSelectedRelease(ctx, client, root, target, runtime.GOARCH, *pin, approved, old.Version)
	if e != nil {
		return e
	}
	if v == old.Version {
		if e = writeJSON(filepath.Join(root, "channel.json"), selection); e != nil {
			return e
		}
		fmt.Fprintln(out, "AWF is already at", v)
		return nil
	}
	if e = verifyExecutable(binary(root, v), v); e != nil {
		return e
	}
	if wasRunning {
		if e = stop(root, out); e != nil {
			return e
		}
	}
	var offline *os.File
	runtimeGuard, e := lockFile(filepath.Join(root, "runtime.lock"))
	if e != nil {
		return errors.New("runtime ownership is unknown; version was not switched")
	}
	defer runtimeGuard.Close()
	if initialized {
		offline, e = node.OfflineIdle(cfg.Node)
		if e != nil {
			if wasRunning {
				runtimeGuard.Close()
				_ = start(root, out)
			}
			return e
		}
	}
	if offline != nil {
		defer offline.Close()
	}
	if e = switchVersion(root, v, old, func() error {
		if wasRunning {
			runtimeGuard.Close()
			if offline != nil {
				offline.Close()
				offline = nil
			}
			if err := start(root, out); err != nil {
				if noPendingStartup(root) != nil {
					return &activationUnknown{err}
				}
				// Never roll the selected pointer back under an unverified new process.
				if _, statErr := os.Stat(runtimePath(root)); statErr == nil {
					if stopErr := stop(root, io.Discard); stopErr != nil {
						return &activationUnknown{err}
					}
				} else if !os.IsNotExist(statErr) {
					return &activationUnknown{err}
				}
				guard, ge := lockFile(filepath.Join(root, "runtime.lock"))
				if ge != nil {
					return &activationUnknown{err}
				}
				guard.Close()
				return err
			}
			return nil
		}
		return verifyExecutable(binary(root, v), v)
	}, func() error {
		if wasRunning {
			return start(root, out)
		}
		return nil
	}); e != nil {
		return e
	}
	if e = writeJSON(filepath.Join(root, "channel.json"), selection); e != nil {
		return fmt.Errorf("AWF updated, but saving the update channel failed: %w", e)
	}
	fmt.Fprintf(out, "AWF updated to %s. Configuration, credentials, native authentication, and job state were preserved.\n", v)
	return nil
}
func verifyExecutable(path, v string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	c := exec.CommandContext(ctx, path, "version")
	b, e := c.Output()
	if e != nil || strings.TrimSpace(string(b)) != v {
		return errors.New("new AWF executable version self-check failed")
	}
	return nil
}

type activationUnknown struct{ error }

// switchVersion has a single pointer commit. If activation fails, restore the
// exact prior pointer before attempting to reactivate that version.
func switchVersion(root, v string, old Pointer, activate, rollback func() error) error {
	if e := validVersion(v); e != nil {
		return e
	}
	if e := writeJSON(filepath.Join(root, "current.json"), Pointer{Version: v}); e != nil {
		return e
	}
	if e := activate(); e != nil {
		var unknown *activationUnknown
		if errors.As(e, &unknown) {
			return fmt.Errorf("activation outcome is unknown; new version remains selected and no process was killed: %w", e)
		}
		if re := writeJSON(filepath.Join(root, "current.json"), old); re != nil {
			return fmt.Errorf("activation failed; pointer rollback also failed: %w", re)
		}
		if re := rollback(); re != nil {
			return fmt.Errorf("new activation failed; prior version restored but its restart needs attention: %w", re)
		}
		return fmt.Errorf("new activation failed; prior version restored: %w", e)
	}
	return nil
}
func install(root string, args []string, out io.Writer) error {
	f := flag.NewFlagSet("_install", flag.ContinueOnError)
	f.SetOutput(out)
	archive := f.String("archive", "", "verified downloaded ZIP")
	channel := f.String("channel", "", "publisher update channel (go-v1); explicit selection enables durable preview consent")
	version := f.String("version", "", "exact release tag")
	allowPrerelease := f.Bool("allow-prerelease", false, "explicitly allow a pinned RC bootstrap")
	digest := f.String("sha256", "", "verified archive SHA-256")
	if e := f.Parse(args); e != nil {
		return e
	}
	if f.NArg() != 0 {
		return errors.New("unexpected installer arguments")
	}
	selection, e := installChannelSelection(*channel, *allowPrerelease)
	if e != nil {
		return e
	}
	if *version == "" {
		return errors.New("bootstrap requires an exact --version")
	}
	if e := validateReleaseRequest(*version, *allowPrerelease); e != nil {
		return e
	}
	// Reject an unapproved RC before creating or changing the per-user root.
	if e := privateRoot(root); e != nil {
		return e
	}
	lock, e := exclusive(root)
	if e != nil {
		return e
	}
	defer lock.Close()

	if _, e := os.Stat(filepath.Join(root, "current.json")); e == nil {
		return errors.New("AWF is already installed; use awf update so live-job checks and rollback are enforced")
	} else if !os.IsNotExist(e) {
		return e
	}
	if _, e := os.Stat(filepath.Join(root, "config.json")); e == nil {
		return errors.New("existing configuration without an install pointer requires explicit recovery, not bootstrap overwrite")
	} else if !os.IsNotExist(e) {
		return e
	}
	for _, name := range []string{"runtime.json", "starting.json", "state"} {
		if _, err := os.Stat(filepath.Join(root, name)); !os.IsNotExist(err) {
			return errors.New("existing runtime or job state requires explicit recovery, not bootstrap overwrite")
		}
	}
	if _, e = loadChannel(root); e != nil {
		return e
	}
	b, e := readBounded(*archive, maxReleaseBytes)
	if e != nil {
		return e
	}
	if len(b) > maxReleaseBytes {
		return errors.New("release archive is too large")
	}
	if e = verifyDigest(b, *digest); e != nil {
		return e
	}
	if e = stageArchive(root, *version, runtime.GOARCH, b); e != nil {
		return e
	}
	if e = verifyExecutable(binary(root, *version), *version); e != nil {
		return e
	}
	bin, e := managedDirectory(root, "bin")
	if e != nil {
		return e
	}
	data, e := os.ReadFile(binary(root, *version))
	if e != nil {
		return e
	}
	launcher := filepath.Join(bin, "awf.exe")
	if existing, err := readBounded(launcher, maxReleaseBytes); err == nil {
		if !bytes.Equal(existing, data) {
			return errors.New("existing launcher without pointer has different bytes; explicit recovery is required")
		}
	} else if os.IsNotExist(err) {
		if e = atomicWrite(launcher, data); e != nil {
			return e
		}
	} else {
		return err
	}
	if e = writeJSON(filepath.Join(root, "channel.json"), selection); e != nil {
		return e
	}
	if e = writeJSON(filepath.Join(root, "current.json"), Pointer{Version: *version}); e != nil {
		return e
	}
	fmt.Fprintf(out, "AWF %s installed for this user at %s. Run awf init to review configuration.\n", *version, root)
	return nil
}
