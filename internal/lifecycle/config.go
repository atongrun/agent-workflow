package lifecycle

import (
	"bufio"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/netip"
	"os"
	"path/filepath"
	"strings"
	"unicode"

	"github.com/atongrun/agent-workflow/internal/node"
)

type Config struct {
	Schema         int         `json:"schema"`
	OpenCodeBinary string      `json:"openCodeBinary"`
	CredentialFile string      `json:"credentialFile"`
	Autostart      bool        `json:"autostart"`
	Node           node.Config `json:"node"`
}

func validateConfig(root string, c Config) error {
	printable := func(v string) bool {
		return strings.IndexFunc(v, func(r rune) bool { return unicode.IsControl(r) }) < 0
	}
	if !printable(root) {
		return errors.New("installation path must not contain control characters")
	}
	if c.Schema != 1 {
		return errors.New("unsupported lifecycle configuration schema")
	}
	if c.Node.Token != "" || c.Node.OpenCodePassword != "" || c.Node.OpenCodeUsername != "" {
		return errors.New("configuration must not contain credentials")
	}
	if c.Node.StateDir != filepath.Join(root, "state") {
		return errors.New("managed node stateDir must remain inside this installation's state directory")
	}
	if c.Node.OpenCodeURL != "http://127.0.0.1:4096" {
		return errors.New("managed native OpenCode must use http://127.0.0.1:4096")
	}
	for _, p := range []string{c.OpenCodeBinary, c.CredentialFile} {
		if !filepath.IsAbs(p) || !printable(p) {
			return errors.New("binary and credential paths must be absolute without control characters")
		}
	}
	if strings.ToLower(filepath.Ext(c.OpenCodeBinary)) != ".exe" {
		return errors.New("select the native OpenCode .exe, not a shell wrapper")
	}
	s, e := os.Stat(c.OpenCodeBinary)
	if e != nil || s.IsDir() {
		return errors.New("native OpenCode executable does not exist")
	}
	if len(c.Node.Projects) == 0 {
		return errors.New("at least one existing project workspace is required")
	}
	for id, p := range c.Node.Projects {
		if strings.TrimSpace(id) == "" || !filepath.IsAbs(p) || !printable(id) || !printable(p) {
			return errors.New("project ID and absolute workspace are required")
		}
		s, e := os.Stat(p)
		if e != nil || !s.IsDir() {
			return fmt.Errorf("workspace for project %q must already exist", id)
		}
	}
	ap, e := netip.ParseAddrPort(c.Node.ListenAddress)
	if e != nil || ap.Port() == 0 || ap.Addr().Zone() != "" || ap.Addr().IsUnspecified() || ap.Addr().IsMulticast() {
		return errors.New("listen address must be an exact local interface IP and nonzero port, never a wildcard")
	}
	if !ap.Addr().IsLoopback() && len(c.Node.AllowedSourceIPs) == 0 {
		return errors.New("remote node listen address requires exact allowed control Host source IPs")
	}
	for _, v := range c.Node.AllowedSourceIPs {
		ip, e := netip.ParseAddr(v)
		if e != nil || ip.Zone() != "" || !(ip.IsGlobalUnicast() || ip.IsLoopback() || ip.IsLinkLocalUnicast()) {
			return errors.New("allowed sources must be exact unicast IPs, not CIDRs or hostnames")
		}
	}
	return c.Node.OpenCodeModel.Validate()
}
func loadConfig(root string) (Config, error) {
	var c Config
	e := readJSON(filepath.Join(root, "config.json"), &c)
	if e == nil {
		e = validateConfig(root, c)
	}
	return c, e
}
func initialize(root string, args []string, in io.Reader, out io.Writer) error {
	f := flag.NewFlagSet("init", flag.ContinueOnError)
	f.SetOutput(out)
	workspace := f.String("workspace", "", "existing dedicated project directory")
	project := f.String("project", "acceptance", "explicit project ID shared with the Host")
	opencode := f.String("opencode", "", "absolute native OpenCode .exe path")
	listen := f.String("listen", "127.0.0.1:7071", "exact node interface IP:port")
	sources := f.String("allow-source", "", "comma-separated exact control Host source IPs")
	credential := f.String("credential-file", filepath.Join(root, "credentials", "windows-node", "node-token.dpapi"), "CurrentUser DPAPI credential location; optional pairing follows configuration review")
	if e := f.Parse(args); e != nil {
		return e
	}
	if f.NArg() != 0 {
		return errors.New("unexpected init arguments")
	}
	if _, e := os.Stat(filepath.Join(root, "config.json")); e == nil {
		return errors.New("already initialized; edit the existing configuration explicitly while stopped (credentials and state were not changed)")
	} else if !os.IsNotExist(e) {
		return e
	}
	c := Config{Schema: 1, OpenCodeBinary: *opencode, CredentialFile: *credential, Node: node.Config{StateDir: filepath.Join(root, "state"), ListenAddress: *listen, OpenCodeURL: "http://127.0.0.1:4096", Projects: map[string]string{*project: *workspace}}}
	if *sources != "" {
		c.Node.AllowedSourceIPs = strings.Split(*sources, ",")
	}
	if e := validateConfig(root, c); e != nil {
		return e
	}
	reader := bufio.NewReader(in)
	fmt.Fprint(out, "Start AWF automatically when you sign in as this Windows user? [y/N]: ")
	answer, e := reader.ReadString('\n')
	if e != nil {
		return errors.New("init requires an explicit interactive answer; configuration was not saved")
	}
	c.Autostart = strings.EqualFold(strings.TrimSpace(answer), "y") || strings.EqualFold(strings.TrimSpace(answer), "yes")
	fmt.Fprintf(out, "\nInstallation: %s\nOpenCode executable: %s\nNative OpenCode: %s (separate process-only authentication)\nNode listener: %s\nAllowed Host sources: %v (empty means loopback only)\nProject: %s = %s\nState: %s\nCredential file: %s\nLogin autostart: %t\nDirectory protection: current Windows user and SYSTEM only\nSaving configuration does not change firewall rules or pair credentials.\n", root, c.OpenCodeBinary, c.Node.OpenCodeURL, c.Node.ListenAddress, c.Node.AllowedSourceIPs, *project, *workspace, c.Node.StateDir, c.CredentialFile, c.Autostart)
	fmt.Fprint(out, "Save this exact configuration? [y/N]: ")
	answer, e = reader.ReadString('\n')
	if e != nil || !(strings.EqualFold(strings.TrimSpace(answer), "y") || strings.EqualFold(strings.TrimSpace(answer), "yes")) {
		return errors.New("init cancelled; configuration was not saved")
	}
	if e = privateRoot(root); e != nil {
		return e
	}
	// Empty jobs directory is deliberate: missing storage after init is unknown.
	if _, e = managedDirectory(root, "state", "jobs"); e != nil {
		return e
	}
	if e = writeJSON(filepath.Join(root, "config.json"), c); e != nil {
		return e
	}
	if c.Autostart {
		if e = setAutostart(root, true); e != nil {
			c.Autostart = false
			_ = writeJSON(filepath.Join(root, "config.json"), c)
			return fmt.Errorf("configuration saved, but login autostart was not enabled: %w", e)
		}
	}
	fmt.Fprintln(out, "Configuration saved. Provider authentication stays in native OpenCode.")
	if _, err := os.Lstat(c.CredentialFile); err == nil {
		fmt.Fprintln(out, "Existing local credential preserved. Remote pairing was not checked. Use awf pair --status to verify if needed, then awf start.")
		return nil
	} else if !os.IsNotExist(err) {
		fmt.Fprintln(out, "Local credential status is unknown; nothing was changed. Use awf pair --status after resolving access, then awf start.")
		return nil
	}
	fmt.Fprint(out, "Pair this node with an existing control Host now? [y/N]: ")
	answer, e = reader.ReadString('\n')
	if e != nil || !(strings.EqualFold(strings.TrimSpace(answer), "y") || strings.EqualFold(strings.TrimSpace(answer), "yes")) {
		fmt.Fprintln(out, "Pairing skipped. Run awf pair when ready, then awf start.")
		return nil
	}
	if e = pairWith(root, c, pairOptions{}, reader, out, nativePairOperations()); e != nil {
		return fmt.Errorf("configuration remains saved; pairing did not complete: %w", e)
	}
	return nil
}
