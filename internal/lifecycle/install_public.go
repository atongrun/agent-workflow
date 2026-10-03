package lifecycle

import (
	"bufio"
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"
	"unicode"
)

// These narrow seams keep fresh-install refusal and consent ordering portable.
// Production supplies only native Windows operations and the fixed publisher.
type freshInstallOps struct {
	progress     *installProgress
	context      func() error
	knownFolder  func() (string, error)
	architecture func() (string, error)
	path         func(string, bool) error
	reparse      func(string) error
	checkParent  func(string) error
	checkRoot    func(string) error
	finish       func(string, string, ChannelSelection, io.Writer) error
	registerPath func(string) error
	previewPath  func(string) (bool, error)
}

// Fresh installation never changes an existing root or its DACL.
func publicInstall(args []string, in io.Reader, out io.Writer) error {
	if runtime.GOOS != "windows" {
		return errors.New("awf install requires native Windows")
	}
	programs, err := knownProgramsFolder()
	if err != nil {
		return err
	}
	ops := nativeFreshInstallOps()
	if interactiveUpdateInput(os.Stderr) {
		ops.progress = &installProgress{out: os.Stderr}
	}
	return publicInstallWith(args, in, out, programs, interactiveUpdateInput(in), releaseClient(), ops)
}

func publicInstallWith(args []string, in io.Reader, out io.Writer, local string, interactive bool, client *http.Client, ops freshInstallOps) (retErr error) {
	progress := ops.progress
	defer func() {
		if retErr != nil {
			progress.failed()
		}
	}()
	f := flag.NewFlagSet("install", flag.ContinueOnError)
	f.SetOutput(out)
	version := f.String("version", "", "exact Go release tag; defaults to publisher go-v1 channel")
	archive := f.String("archive", "", "bootstrap-verified local release ZIP (requires version and sha256)")
	digest := f.String("sha256", "", "independently verified archive SHA-256")
	channel := f.String("channel", channelName, "publisher channel go-v1")
	yes := f.Bool("yes", false, "approve fresh per-user installation and user PATH registration unless --no-path")
	allow := f.Bool("allow-prerelease", false, "approve the selected preview and future previews on go-v1")
	noPath := f.Bool("no-path", false, "do not change user or process PATH")
	if err := f.Parse(args); err != nil {
		return err
	}
	if f.NArg() != 0 {
		return errors.New("usage: awf install [--yes] [--allow-prerelease] [--no-path]")
	}
	if *channel != channelName {
		return errors.New("only the go-v1 update channel is supported")
	}
	if *archive != "" && (*version == "" || *digest == "") {
		return errors.New("local archive requires exact --version and --sha256")
	}
	if err := validateReleaseRequest(*version, *allow); err != nil {
		return err
	}
	if err := ops.context(); err != nil {
		return err
	}
	known, err := ops.knownFolder()
	if err != nil {
		return errors.New("cannot establish the Windows per-user Programs known folder")
	}
	if local == "" || strings.IndexFunc(local, unicode.IsControl) >= 0 || !filepath.IsAbs(local) || validateInstallerPath(known, filepath.Clean(local), nil) != nil {
		return errors.New("installation parent must match the current user's Programs known folder; no changes made")
	}
	arch, err := ops.architecture()
	if err != nil {
		return err
	}
	if arch != "amd64" && arch != "arm64" {
		return errors.New("native Windows AMD64 or ARM64 is required")
	}
	root := filepath.Join(local, "AWF")
	if err := freshInstallPreflight(root, ops); err != nil {
		return err
	}
	if !*noPath {
		if _, err := ops.previewPath(filepath.Join(root, "bin")); err != nil {
			return fmt.Errorf("user PATH registration cannot be prepared; use --no-path only if intended: %w", err)
		}
	}
	// EOF/redirected input cannot silently become consent; --yes is explicit.
	if !*yes && (!interactive || in == nil) {
		return errors.New("installation requires interactive confirmation or explicit --yes; no changes made")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()
	progress.stage("Resolve release metadata")
	target, err := resolveReleaseTarget(ctx, client, *version, arch)
	if err != nil {
		return err
	}
	if *version == "" && target.CLIProtocol != "3" {
		return errors.New("publisher channel has not released the fresh-install product (protocol 3); no installation files or PATH changed")
	}
	preview := prereleaseVersion(target.Version)
	if *yes && preview && !*allow {
		return errors.New("the channel selects a preview; --yes alone does not approve previews; add --allow-prerelease only if intended")
	}
	if _, err = fmt.Fprintf(out, "Install AWF %s (%s), publisher channel go-v1, at %q.\n", target.Version, arch, root); err != nil {
		return err
	}
	if _, statErr := os.Lstat(filepath.Dir(root)); os.IsNotExist(statErr) {
		if _, err = fmt.Fprintln(out, "The standard per-user Programs directory will be created with inherited permissions."); err != nil {
			return err
		}
	}
	if !*noPath {
		if _, err = fmt.Fprintln(out, "This adds the verified AWF bin directory first in your user PATH; other entries are preserved. New terminals receive the change."); err != nil {
			return err
		}
	}
	if preview || *allow {
		if _, err = fmt.Fprintln(out, "Preview releases may be unstable. Continuing approves this preview (if selected) and future previews on go-v1."); err != nil {
			return err
		}
	}
	if !*yes {
		if _, err = fmt.Fprint(out, "Proceed with fresh installation? [y/N]: "); err != nil {
			return err
		}
		answer, readErr := bufio.NewReader(io.LimitReader(in, 128)).ReadString('\n')
		if readErr != nil || !(strings.EqualFold(strings.TrimSpace(answer), "y") || strings.EqualFold(strings.TrimSpace(answer), "yes")) {
			return errors.New("installation cancelled; no files, ACLs or PATH changed")
		}
	}
	selection, err := installChannelSelection(channelName, *allow || preview)
	if err != nil {
		return err
	}
	// Hash/source validation precedes even creating an empty AWF directory.
	var payload []byte
	if *archive != "" {
		progress.stage("Verify release archive")
		payload, err = readBounded(*archive, maxReleaseBytes)
		if err == nil {
			err = verifyDigest(payload, *digest)
		}
	} else {
		progress.stage("Download release")
		payload, err = downloadSelectedReleaseProgress(ctx, client, target, arch, *digest, selection.PreviewApproved, "", progress)
	}
	if err != nil {
		return err
	}
	progress.stage("Prepare installation directory")
	if err := freshInstallPreflight(root, ops); err != nil {
		return err
	}
	// Only the standard known-folder parent may be newly created, never repaired.
	programs := filepath.Dir(root)
	if _, statErr := os.Lstat(programs); os.IsNotExist(statErr) {
		if err := os.Mkdir(programs, 0700); err != nil && !os.IsExist(err) {
			return fmt.Errorf("cannot create per-user Programs directory: %w", err)
		}
	}
	if err := inspectProgramsParent(programs, ops, false); err != nil {
		return err
	}
	// Mkdir (never MkdirAll) atomically refuses an existing root, including one
	// created during consent/download. Never protect an existing user's tree.
	if err := os.Mkdir(root, 0700); err != nil {
		return errors.New("AWF root could not be created exclusively; inspect with awf doctor; no existing root was modified")
	}
	// Retain a partial installation instead of deleting or repairing user data.
	defer func() {
		if retErr != nil {
			retErr = fmt.Errorf("fresh installation stopped; the newly created AWF folder was retained. Inspect with awf doctor; install never resumes or migrates an existing root: %w", retErr)
		}
	}()
	// A late failure leaves the partial directory for explicit diagnosis.
	if err := ops.path(root, false); err != nil {
		return err
	}
	if err := ops.checkRoot(root); err != nil {
		return err
	}
	if err := ops.path(root, false); err != nil {
		return err
	}
	lock, err := exclusive(root)
	if err != nil {
		return err
	}
	defer lock.Close()
	progress.stage("Extract verified release")
	if err := stageArchive(root, target.Version, arch, payload); err != nil {
		return err
	}
	progress.stage("Install and verify launcher")
	// Suppress subordinate success until launcher identity and PATH are verified.
	if err := ops.finish(root, target.Version, selection, io.Discard); err != nil {
		return err
	}
	launcher := filepath.Join(root, "bin", "awf.exe")
	if err := ops.path(launcher, false); err != nil {
		return err
	}
	if !*noPath {
		progress.stage("Register user PATH")
		if err := ops.registerPath(filepath.Dir(launcher)); err != nil {
			return fmt.Errorf("AWF is installed, but PATH registration failed; do not rerun install. Continue configuration in PowerShell with: %s. PATH error: %w", installInitCommand(launcher), err)
		}
	}
	progress.stage("Check command lookup")
	if resolved, err := exec.LookPath("awf"); err != nil || validateInstallerPath(launcher, resolved, nil) != nil {
		if _, err := fmt.Fprintf(out, "Command lookup does not resolve the installed launcher in this process. Review shell aliases/functions or earlier machine PATH entries. Direct configuration command (PowerShell): %s\n", installInitCommand(launcher)); err != nil {
			return err
		}
	}
	_, err = fmt.Fprintf(out, "AWF %s installed. Review configuration explicitly (PowerShell):\n%s\nInstallation does not pair credentials, enable autostart or start AWF.\n", target.Version, installInitCommand(launcher))
	if err != nil {
		return err
	}
	progress.stage("Done")
	return nil
}

func freshInstallPreflight(root string, ops freshInstallOps) error {
	if err := ops.context(); err != nil {
		return err
	}
	if err := inspectProgramsParent(filepath.Dir(root), ops, true); err != nil {
		return err
	}
	if _, err := os.Lstat(root); err == nil {
		return errors.New("AWF root already exists, including a partial or credentials-only installation; use awf doctor or awf update for a healthy fresh-product install; migration and repair are unsupported, and no files or ACLs changed")
	} else if !os.IsNotExist(err) {
		return errors.New("AWF root state is unknown; no changes made")
	}
	return nil
}

// A missing standard Programs directory is planned without creating it. Its
// existing parent must be a real, unredirected, integrity-protected directory.
func inspectProgramsParent(programs string, ops freshInstallOps, allowMissing bool) error {
	inspect := programs
	st, err := os.Lstat(programs)
	if os.IsNotExist(err) && allowMissing {
		inspect = filepath.Dir(programs)
	} else if err != nil {
		return err
	} else if !st.IsDir() {
		return errors.New("per-user Programs location is not a directory")
	}
	if err := doctorAncestors(inspect, ops.reparse); err != nil {
		return errors.New("Programs parent is missing, unreadable or linked; no ACLs changed")
	}
	if err := ops.path(inspect, false); err != nil {
		return err
	}
	if err := ops.checkParent(inspect); err != nil {
		return fmt.Errorf("Programs parent permissions are unsafe; no ACLs changed: %w", err)
	}
	return nil
}

// A native executable invocation, not a generated installer script. Single
// quoting preserves spaces, dollar signs and backslashes in Windows paths.
func installInitCommand(launcher string) string {
	return "& '" + strings.ReplaceAll(launcher, "'", "''") + "' init"
}
