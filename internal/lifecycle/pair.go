package lifecycle

import (
	"bufio"
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

//go:embed pair_remote.py
var remotePairProgram string

var pairHostRE = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`)
var pairPathRE = regexp.MustCompile(`^/[A-Za-z0-9._/-]+$`)
var pairProofRE = regexp.MustCompile(`^[0-9a-f]{64}$`)

type pairOptions struct {
	host, remote  string
	status, retry bool
}
type pairRequest struct {
	Op        string `json:"op"`
	Path      string `json:"path"`
	Challenge string `json:"challenge"`
	Token     string `json:"token,omitempty"`
}
type pairResponse struct {
	State string `json:"state"`
	Proof string `json:"proof,omitempty"`
}
type pairOperations struct {
	read   func(string) (string, error)
	write  func(string, string, string) error
	remote func(context.Context, string, pairRequest) (pairResponse, error)
}

func nativePairOperations() pairOperations {
	return pairOperations{read: readNodeToken, write: writeNodeToken, remote: callPairRemote}
}
func pair(root string, args []string, in io.Reader, out io.Writer) error {
	f := flag.NewFlagSet("pair", flag.ContinueOnError)
	f.SetOutput(out)
	var o pairOptions
	f.StringVar(&o.host, "ssh-host", "", "existing SSH config alias with a verified known-host key")
	f.StringVar(&o.remote, "remote-env", "", "new absolute Linux Host env-file path in an existing private directory")
	f.BoolVar(&o.status, "status", false, "read-only challenge proof; does not create or transmit a token")
	f.BoolVar(&o.retry, "retry", false, "after confirmation, reuse the existing local identity for a missing remote file")
	if e := f.Parse(args); e != nil {
		return e
	}
	if f.NArg() != 0 || o.status && o.retry {
		return errors.New("usage: awf pair [--status | --retry] [--ssh-host ALIAS --remote-env /absolute/path]")
	}
	c, e := loadConfig(root)
	if e != nil {
		return errors.New("valid initialization is required; run awf init first")
	}
	return pairWith(root, c, o, bufio.NewReader(in), out, nativePairOperations())
}
func validPairTarget(o pairOptions) error {
	if !pairHostRE.MatchString(o.host) {
		return errors.New("SSH host must be a preconfigured alias containing only letters, digits, dot, underscore or hyphen; no options, user@host, or shell syntax")
	}
	if len(o.remote) > 1024 || !pairPathRE.MatchString(o.remote) || path.Clean(o.remote) != o.remote || o.remote == "/" {
		return errors.New("remote env-file must be a clean absolute Linux path using letters, digits, dot, underscore, hyphen and slash; no spaces or traversal")
	}
	return nil
}
func pairInput(r *bufio.Reader, out io.Writer, prompt string) (string, error) {
	fmt.Fprint(out, prompt)
	s, e := r.ReadString('\n')
	if e != nil {
		return "", errors.New("pairing requires an explicit interactive answer; no new credential was created or sent")
	}
	return strings.TrimSpace(s), nil
}
func pairWith(root string, c Config, o pairOptions, r *bufio.Reader, out io.Writer, ops pairOperations) error {
	var e error
	if o.host == "" {
		o.host, e = pairInput(r, out, "Existing trusted SSH Host alias: ")
		if e != nil {
			return e
		}
	}
	if o.remote == "" {
		o.remote, e = pairInput(r, out, "Absolute Linux Host env-file path (parent must already exist and be private): ")
		if e != nil {
			return e
		}
	}
	if e = validPairTarget(o); e != nil {
		return e
	}
	if e = validatePairLocalPath(root, c.CredentialFile); e != nil {
		return e
	}
	var token string
	_, e = os.Lstat(c.CredentialFile)
	local := e == nil
	if e != nil && !os.IsNotExist(e) {
		return errors.New("local credential status is unknown; no pairing changes made")
	}
	if local {
		token, e = ops.read(c.CredentialFile)
		if e != nil {
			return errors.New("existing local credential is unreadable or unsafe; preserved without replacement; explicit recovery is required")
		}
	}
	// The inspection sends only a random challenge, never a credential.
	challenge, e := pairRandom(false)
	if e != nil {
		return e
	}
	req := pairRequest{Op: "inspect", Path: o.remote, Challenge: challenge}
	fmt.Fprintf(out, "Local credential: %s\nSSH Host alias: %s\nRemote env-file: %s\nChecking via system OpenSSH: strict existing known-host key, key-only BatchMode, no forwarding or host-key updates.\n", c.CredentialFile, o.host, o.remote)
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	response, re := ops.remote(ctx, o.host, req)
	cancel()
	if re != nil || response.State == "unknown" {
		fmt.Fprintln(out, "Pairing status: remote-unknown. Remote authentication, file privacy, format, or reachability could not be verified; no pairing changes made.")
		return errors.New("verify the SSH alias, trusted host key, Linux Python 3, and private existing remote parent before retrying")
	}
	if response.State == "present" {
		if local && pairProofMatches(token, challenge, response.Proof) {
			fmt.Fprintln(out, "Pairing status: paired (live challenge verified the same credential in both files). No credentials changed. Host service configuration and node connectivity were not tested.")
			return nil
		}
		fmt.Fprintln(out, "Pairing status: remote-unknown. A remote credential exists but a matching local identity could not be proven. Existing files were preserved; rotation or recovery requires a separate explicit process.")
		return errors.New("existing remote env-file will never be overwritten by awf pair")
	}
	if response.State != "missing" {
		return errors.New("pairing status: remote-unknown; unexpected remote response; no pairing changes made")
	}
	if local {
		fmt.Fprintln(out, "Pairing status: local-only (valid local credential; remote env-file is absent).")
	} else {
		fmt.Fprintln(out, "Pairing status: unpaired (both credential files are absent).")
	}
	if o.status {
		return nil
	}
	if local && !o.retry {
		return errors.New("local identity preserved; run awf pair --retry with the same SSH alias and remote env-file to review and confirm delivery of this identity")
	}
	if !local && o.retry {
		return errors.New("--retry requires an existing readable local credential; no new identity was generated")
	}
	action := "Create a new 32-random-byte identity and protect it with CurrentUser DPAPI"
	if local {
		action = "Reuse the existing CurrentUser DPAPI identity without changing it"
	}
	fmt.Fprintf(out, "\n%s.\nLocal credential: %s\nRemote destination: %s:%s\nThe node token will be sent only over SSH stdin and saved as AWF_WINDOWS_TOKEN in a new mode-0600 file.\nThe SSH alias uses your existing SSH configuration and trusted known-host key. Verify that alias identifies your intended control Host and account.\nNo overwrite, rotation, Host config change, service start, firewall change, or OpenCode credential sharing is performed.\n", action, c.CredentialFile, o.host, o.remote)
	answer, e := pairInput(r, out, "Authorize this exact credential creation/access and transfer? Type PAIR to continue: ")
	if e != nil {
		return e
	}
	if answer != "PAIR" {
		fmt.Fprintln(out, "Pairing cancelled; no credential was created or sent.")
		return nil
	}
	if !local {
		token, e = pairRandom(true)
		if e != nil {
			return e
		}
		if e = ops.write(root, c.CredentialFile, token); e != nil {
			return fmt.Errorf("local credential creation failed; no token was sent; inspect the selected local path before retrying: %w", e)
		}
	}
	req.Op, req.Token = "create", token
	ctx, cancel = context.WithTimeout(context.Background(), 30*time.Second)
	response, re = ops.remote(ctx, o.host, req)
	cancel()
	if re == nil && response.State == "present" && pairProofMatches(token, challenge, response.Proof) {
		fmt.Fprintln(out, "Pairing status: paired (live challenge verified the same credential in both files). Local identity is DPAPI-protected; remote env-file was created privately. Host service configuration and node connectivity were not tested. Run awf start when ready.")
		return nil
	}
	fmt.Fprintln(out, "Pairing status: remote-unknown. The local encrypted identity was retained. The remote file may already exist; no overwrite or replacement will be attempted.")
	return errors.New("run awf pair --status with the same target to verify; if the remote file is absent, awf pair --retry will request confirmation to resend this same identity")
}
func pairRandom(upper bool) (string, error) {
	b := make([]byte, 32)
	if _, e := rand.Read(b); e != nil {
		return "", errors.New("secure random generation failed")
	}
	s := hex.EncodeToString(b)
	for i := range b {
		b[i] = 0
	}
	if upper {
		s = strings.ToUpper(s)
	}
	return s, nil
}
func pairProofMatches(token, challenge, proof string) bool {
	if !pairProofRE.MatchString(proof) {
		return false
	}
	m := hmac.New(sha256.New, []byte(token))
	_, _ = m.Write([]byte(challenge))
	return hmac.Equal([]byte(hex.EncodeToString(m.Sum(nil))), []byte(proof))
}
func validatePairLocalPath(root, credential string) error {
	if !filepath.IsAbs(credential) || filepath.Clean(credential) != credential || strings.ContainsAny(credential, "\r\n\x00") {
		return errors.New("local credential must be a clean absolute path")
	}
	if e := validateCredentialAncestors(credential); e != nil {
		return e
	}
	// Missing directories are only created for the standard managed location.
	if credential == filepath.Join(root, "credentials", "windows-node", "node-token.dpapi") {
		return nil
	}
	st, e := os.Lstat(filepath.Dir(credential))
	if e != nil || !st.IsDir() || st.Mode()&os.ModeSymlink != 0 {
		return errors.New("external credential parent must already exist as a private real directory")
	}
	if e = checkPrivatePath(filepath.Dir(credential)); e != nil {
		return errors.New("external credential parent is not private; its ACL was not changed")
	}
	return nil
}

// Secret-bearing stdin and untrusted stdout/stderr are never attached to the
// terminal or error text. Limit captures even for a broken/malicious receiver.
type pairCapture struct {
	b        bytes.Buffer
	overflow bool
}

func (w *pairCapture) Write(p []byte) (int, error) {
	n := len(p)
	left := 4096 - w.b.Len()
	if len(p) > left {
		w.overflow = true
		p = p[:left]
	}
	_, _ = w.b.Write(p)
	return n, nil
}
func pairSSHArgs(host string) []string {
	// The remote command is entirely fixed; alias is restricted and all
	// per-request values go through bounded JSON stdin, never a shell string.
	command := "python3 -c '" + strings.ReplaceAll(remotePairProgram, "'", "'\"'\"'") + "'"
	return []string{
		"-T",
		"-o", "BatchMode=yes",
		"-o", "StrictHostKeyChecking=yes",
		"-o", "UpdateHostKeys=no",
		"-o", "PasswordAuthentication=no",
		"-o", "KbdInteractiveAuthentication=no",
		"-o", "PreferredAuthentications=publickey",
		"-o", "VerifyHostKeyDNS=no",
		"-o", "ClearAllForwardings=yes",
		"-o", "ForwardAgent=no",
		"-o", "ForwardX11=no",
		"-o", "Tunnel=no",
		"-o", "PermitLocalCommand=no",
		"-o", "RemoteCommand=none",
		"-o", "ControlMaster=no",
		"-o", "ControlPath=none",
		"-o", "ConnectionAttempts=1",
		"-o", "ConnectTimeout=10",
		"-o", "LogLevel=ERROR",
		host, command,
	}
}
func callPairRemote(ctx context.Context, host string, req pairRequest) (pairResponse, error) {
	var result pairResponse
	if e := validPairTarget(pairOptions{host: host, remote: req.Path}); e != nil {
		return result, e
	}
	binary, e := systemSSH()
	if e != nil {
		return result, e
	}
	input, e := json.Marshal(req)
	if e != nil {
		return result, errors.New("cannot encode pairing request")
	}
	defer func() {
		for i := range input {
			input[i] = 0
		}
	}()
	c := exec.CommandContext(ctx, binary, pairSSHArgs(host)...)
	c.WaitDelay = 2 * time.Second
	c.Stdin = bytes.NewReader(input)
	var capture pairCapture
	c.Stdout, c.Stderr = &capture, io.Discard
	if e = c.Run(); e != nil || capture.overflow {
		return result, errors.New("SSH pairing exchange failed; remote output suppressed")
	}
	return decodePairResponse(capture.b.Bytes())
}
func decodePairResponse(b []byte) (pairResponse, error) {
	var result pairResponse
	if len(b) > 4096 {
		return result, errors.New("oversized remote pairing response; output suppressed")
	}
	d := json.NewDecoder(bytes.NewReader(b))
	d.DisallowUnknownFields()
	if e := d.Decode(&result); e != nil || d.Decode(new(any)) != io.EOF {
		return pairResponse{}, errors.New("invalid remote pairing response; output suppressed")
	}
	switch result.State {
	case "present":
		if !pairProofRE.MatchString(result.Proof) {
			return pairResponse{}, errors.New("invalid remote pairing proof; output suppressed")
		}
	case "missing", "exists", "unknown":
		if result.Proof != "" {
			return pairResponse{}, errors.New("unexpected remote pairing proof; output suppressed")
		}
	default:
		return pairResponse{}, errors.New("unknown remote pairing state; output suppressed")
	}
	return result, nil
}
