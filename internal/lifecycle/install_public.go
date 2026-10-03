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
	context      func() error
	knownFolder  func() (string, error)
	architecture func() (string, error)
	path         func(string, bool) error
	reparse      func(string) error
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
	return publicInstallWith(args, in, out, os.Getenv("LOCALAPPDATA"), interactiveUpdateInput(in), releaseClient(), nativeFreshInstallOps())
}

func publicInstallWith(args []string, in io.Reader, out io.Writer, local string, interactive bool, client *http.Client, ops freshInstallOps) (retErr error) {
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
		return errors.New("cannot establish the Windows LocalAppData known folder")
	}
	if local == "" || strings.IndexFunc(local, unicode.IsControl) >= 0 || !filepath.IsAbs(local) || validateInstallerPath(known, filepath.Clean(local), nil) != nil {
		return errors.New("LOCALAPPDATA must match the current user's Windows known folder; no changes made")
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
		payload, err = readBounded(*archive, maxReleaseBytes)
		if err == nil {
			err = verifyDigest(payload, *digest)
		}
	} else {
		payload, err = downloadSelectedRelease(ctx, client, target, arch, *digest, selection.PreviewApproved, "")
	}
	if err != nil {
		return err
	}
	if err := freshInstallPreflight(root, ops); err != nil {
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
	if err := stageArchive(root, target.Version, arch, payload); err != nil {
		return err
	}
	// Suppress subordinate success until launcher identity and PATH are verified.
	if err := ops.finish(root, target.Version, selection, io.Discard); err != nil {
		return err
	}
	launcher := filepath.Join(root, "bin", "awf.exe")
	if err := ops.path(launcher, false); err != nil {
		return err
	}
	if !*noPath {
		if err := ops.registerPath(filepath.Dir(launcher)); err != nil {
			return fmt.Errorf("AWF is installed, but PATH registration failed; do not rerun install. Continue configuration in PowerShell with: %s. PATH error: %w", installInitCommand(launcher), err)
		}
	}
	if resolved, err := exec.LookPath("awf"); err != nil || validateInstallerPath(launcher, resolved, nil) != nil {
		if _, err := fmt.Fprintf(out, "Command lookup does not resolve the installed launcher in this process. Review shell aliases/functions or earlier machine PATH entries. Direct configuration command (PowerShell): %s\n", installInitCommand(launcher)); err != nil {
			return err
		}
	}
	_, err = fmt.Fprintf(out, "AWF %s installed. Review configuration explicitly (PowerShell):\n%s\nInstallation does not pair credentials, enable autostart or start AWF.\n", target.Version, installInitCommand(launcher))
	return err
}

func freshInstallPreflight(root string, ops freshInstallOps) error {
	if err := ops.context(); err != nil {
		return err
	}
	if err := doctorAncestors(filepath.Dir(root), ops.reparse); err != nil {
		return errors.New("installation parent is missing, unreadable or linked; no changes made")
	}
	if err := ops.path(filepath.Dir(root), false); err != nil {
		return err
	}
	if _, err := os.Lstat(root); err == nil {
		return errors.New("AWF root already exists, including a partial or credentials-only installation; use awf doctor or awf update for a healthy fresh-product install; migration and repair are unsupported, and no files or ACLs changed")
	} else if !os.IsNotExist(err) {
		return errors.New("AWF root state is unknown; no changes made")
	}
	return nil
}

// A native executable invocation, not a generated installer script. Single
// quoting preserves spaces, dollar signs and backslashes in Windows paths.
func installInitCommand(launcher string) string {
	return "& '" + strings.ReplaceAll(launcher, "'", "''") + "' init"
}
