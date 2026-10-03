package lifecycle

import (
	"bufio"
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func testPairProof(token, challenge string) string {
	m := hmac.New(sha256.New, []byte(token))
	_, _ = m.Write([]byte(challenge))
	return hex.EncodeToString(m.Sum(nil))
}
func TestPairReviewRecoveryAndStatus(t *testing.T) {
	const existing = "ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789"
	for _, tc := range []struct {
		name                         string
		local, retry, status         bool
		remote, delivery, answer     string
		wantErr, wantWrite, wantSend bool
		wantOutput                   string
	}{
		{name: "cancel", remote: "missing", answer: "no\n", wantOutput: "cancelled"},
		{name: "eof", remote: "missing", wantErr: true},
		{name: "status-absent", remote: "missing", status: true, wantOutput: "unpaired"},
		{name: "status-local", local: true, remote: "missing", status: true, wantOutput: "local-only"},
		{name: "paired", local: true, remote: "match", wantOutput: "Pairing status: paired"},
		{name: "paired-retry-no-resend", local: true, retry: true, remote: "match", wantOutput: "Pairing status: paired"},
		{name: "local-requires-retry", local: true, remote: "missing", answer: "PAIR\n", wantErr: true, wantOutput: "local-only"},
		{name: "retry-requires-local", retry: true, remote: "missing", answer: "PAIR\n", wantErr: true},
		{name: "remote-only", remote: "match", answer: "PAIR\n", wantErr: true, wantOutput: "remote-unknown"},
		{name: "mismatch", local: true, retry: true, remote: "different", answer: "PAIR\n", wantErr: true, wantOutput: "remote-unknown"},
		{name: "unknown-new", remote: "unknown", answer: "PAIR\n", wantErr: true, wantOutput: "remote-unknown"},
		{name: "unknown-existing", local: true, retry: true, remote: "failure", answer: "PAIR\n", wantErr: true, wantOutput: "remote-unknown"},
		{name: "create", remote: "missing", delivery: "match", answer: "PAIR\n", wantWrite: true, wantSend: true, wantOutput: "Pairing status: paired"},
		{name: "retry", local: true, retry: true, remote: "missing", delivery: "match", answer: "PAIR\n", wantSend: true, wantOutput: "Pairing status: paired"},
		{name: "failed-delivery-retains-identity", remote: "missing", delivery: "failure", answer: "PAIR\n", wantWrite: true, wantSend: true, wantErr: true, wantOutput: "local encrypted identity was retained"},
		{name: "remote-race-no-overwrite", remote: "missing", delivery: "exists", answer: "PAIR\n", wantWrite: true, wantSend: true, wantErr: true, wantOutput: "remote-unknown"},
		{name: "retry-failed-no-rekey", local: true, retry: true, remote: "missing", delivery: "failure", answer: "PAIR\n", wantSend: true, wantErr: true, wantOutput: "local encrypted identity was retained"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			root, c, _ := lifecycleConfigFixture(t)
			if e := privateRoot(root); e != nil {
				t.Fatal(e)
			}
			if tc.local {
				if _, e := managedDirectory(root, "credentials", "windows-node"); e != nil {
					t.Fatal(e)
				}
				mustWriteFixture(t, c.CredentialFile, []byte("inert encrypted identity stand-in"))
			}
			var out bytes.Buffer
			writes, sends := 0, 0
			saved := ""
			ops := pairOperations{
				read: func(string) (string, error) { return existing, nil },
				write: func(_, p, token string) error {
					writes++
					saved = token
					if token == existing || len(token) != 64 || strings.ToUpper(token) != token {
						t.Fatal("not a fresh uppercase random identity")
					}
					if _, e := hex.DecodeString(token); e != nil {
						t.Fatal(e)
					}
					if _, e := managedDirectory(root, "credentials", "windows-node"); e != nil {
						t.Fatal(e)
					}
					f, e := os.OpenFile(p, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
					if e != nil {
						return e
					}
					defer f.Close()
					_, e = f.Write([]byte("synthetic encrypted stand-in"))
					return e
				},
				remote: func(_ context.Context, host string, req pairRequest) (pairResponse, error) {
					if host != "fixture-host" || req.Path != "/private/node.env" || !pairProofRE.MatchString(req.Challenge) {
						t.Fatal("wrong target/challenge")
					}
					state := tc.remote
					key := existing
					if req.Op == "inspect" && req.Token != "" {
						t.Fatal("inspection transmitted a token")
					}
					if req.Op == "create" {
						sends++
						state = tc.delivery
						key = req.Token
						if tc.local && key != existing {
							t.Fatal("existing identity was rotated")
						}
						if !tc.local && key != saved {
							t.Fatal("sent identity differs from saved identity")
						}
					}
					switch state {
					case "match":
						return pairResponse{State: "present", Proof: testPairProof(key, req.Challenge)}, nil
					case "different":
						return pairResponse{State: "present", Proof: testPairProof("DIFFERENT", req.Challenge)}, nil
					case "failure":
						return pairResponse{}, errors.New(existing)
					default:
						return pairResponse{State: state}, nil
					}
				},
			}
			e := pairWith(root, c, pairOptions{host: "fixture-host", remote: "/private/node.env", retry: tc.retry, status: tc.status}, bufio.NewReader(strings.NewReader(tc.answer)), &out, ops)
			if (e != nil) != tc.wantErr {
				t.Fatalf("error=%v wantErr=%v output=%s", e, tc.wantErr, out.String())
			}
			if (writes > 0) != tc.wantWrite || (sends > 0) != tc.wantSend || writes > 1 || sends > 1 {
				t.Fatalf("writes=%d sends=%d", writes, sends)
			}
			text := out.String()
			if e != nil {
				text += e.Error()
			}
			if strings.Contains(text, existing) || saved != "" && strings.Contains(text, saved) {
				t.Fatal("credential leaked into output/error")
			}
			if !strings.Contains(out.String(), tc.wantOutput) {
				t.Fatalf("missing status %q: %s", tc.wantOutput, out.String())
			}
			if tc.wantWrite {
				if _, e := os.Stat(c.CredentialFile); e != nil {
					t.Fatal("local identity not retained")
				}
			}
			if tc.local {
				b, e := os.ReadFile(c.CredentialFile)
				if e != nil || string(b) != "inert encrypted identity stand-in" {
					t.Fatal("existing local file altered")
				}
			}
			if tc.wantSend {
				for _, s := range []string{c.CredentialFile, "fixture-host:/private/node.env", "Type PAIR", "known-host key"} {
					if !strings.Contains(text, s) {
						t.Errorf("confirmation omitted %s", s)
					}
				}
			}
		})
	}
}
func TestPairTargetRejectsShellOptionsAndTraversal(t *testing.T) {
	for _, host := range []string{"", "-oProxyCommand=bad", "user@host", "host;id", "a b", "host\n", "$(id)", strings.Repeat("a", 129)} {
		if e := validPairTarget(pairOptions{host: host, remote: "/private/node.env"}); e == nil {
			t.Errorf("unsafe host accepted %q", host)
		}
	}
	for _, p := range []string{"", "relative", "/", "/private/../node.env", "/private/./node.env", "/private//node.env", "/private/node.env/", "/tmp/a b", "/tmp/a;id", "/tmp/$(id)", "/tmp/a\n", "/" + strings.Repeat("a", 1024)} {
		if e := validPairTarget(pairOptions{host: "control-1.example", remote: p}); e == nil {
			t.Errorf("unsafe path accepted %q", p)
		}
	}
	if e := validPairTarget(pairOptions{host: "control-1.example", remote: "/home/user/.awf/windows-node.env"}); e != nil {
		t.Fatal(e)
	}
}
func TestPairSSHNeverPlacesRequestInArguments(t *testing.T) {
	args := pairSSHArgs("fixture-host")
	command := args[len(args)-1]
	if !strings.HasPrefix(command, "python3 -c '") || args[len(args)-2] != "fixture-host" {
		t.Fatal("remote program/target changed")
	}
	for _, want := range []string{"BatchMode=yes", "StrictHostKeyChecking=yes", "UpdateHostKeys=no", "PasswordAuthentication=no", "KbdInteractiveAuthentication=no", "ClearAllForwardings=yes", "ForwardAgent=no", "ForwardX11=no", "Tunnel=no", "VerifyHostKeyDNS=no", "PreferredAuthentications=publickey", "PermitLocalCommand=no", "RemoteCommand=none", "ControlPath=none"} {
		if !strings.Contains(strings.Join(args, "\n"), want) {
			t.Errorf("missing SSH guard %s", want)
		}
	}
	var capture pairCapture
	n, e := capture.Write(bytes.Repeat([]byte("x"), 10000))
	if e != nil || n != 10000 || capture.b.Len() != 4096 || !capture.overflow {
		t.Fatal("remote output is not bounded")
	}
}
func TestPairRejectsUnsafeLocalAndUnreadableIdentity(t *testing.T) {
	root, c, _ := lifecycleConfigFixture(t)
	if e := privateRoot(root); e != nil {
		t.Fatal(e)
	}
	if _, e := managedDirectory(root, "credentials", "windows-node"); e != nil {
		t.Fatal(e)
	}
	mustWriteFixture(t, c.CredentialFile, []byte("inert"))
	calls := 0
	ops := pairOperations{read: func(string) (string, error) { return "", errors.New("bad credential") }, remote: func(context.Context, string, pairRequest) (pairResponse, error) { calls++; return pairResponse{}, nil }}
	var out bytes.Buffer
	e := pairWith(root, c, pairOptions{host: "fixture", remote: "/private/node.env"}, bufio.NewReader(strings.NewReader("PAIR\n")), &out, ops)
	if e == nil || calls != 0 {
		t.Fatal("unsafe local identity did not stop before network")
	}
	c.CredentialFile = "relative"
	if e := validatePairLocalPath(root, c.CredentialFile); e == nil {
		t.Fatal("relative path accepted")
	}
	if runtime.GOOS != "windows" {
		link := filepath.Join(t.TempDir(), "link")
		if e := os.Symlink(root, link); e != nil {
			t.Fatal(e)
		}
		if e := validatePairLocalPath(root, filepath.Join(link, "credentials", "windows-node", "new.dpapi")); e == nil {
			t.Fatal("symlink ancestor accepted")
		}
	}
}

// Run only against temporary synthetic files; no SSH, real Host, or credential
// store is touched. This also exercises the exact Python program embedded in awf.
func TestPairRemoteProgramFixtures(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Linux receiver fixtures run on Linux; native DPAPI tests cover Windows")
	}
	python, e := exec.LookPath("python3")
	if e != nil {
		t.Skip("python3 unavailable")
	}
	root := t.TempDir()
	if e := os.Chmod(root, 0700); e != nil {
		t.Fatal(e)
	}
	token := strings.Repeat("AB0123CD", 8)
	challenge := strings.Repeat("a1", 32)
	target := filepath.Join(root, "node.env")
	run := func(op, p, key string) pairResponse {
		t.Helper()
		b, e := json.Marshal(pairRequest{Op: op, Path: p, Challenge: challenge, Token: key})
		if e != nil {
			t.Fatal(e)
		}
		c := exec.Command(python, "-c", remotePairProgram)
		c.Stdin = bytes.NewReader(b)
		out, e := c.CombinedOutput()
		if e != nil {
			t.Fatalf("receiver failed: %v", e)
		}
		if bytes.Contains(out, []byte(token)) {
			t.Fatal("receiver leaked credential")
		}
		var r pairResponse
		if e := json.Unmarshal(out, &r); e != nil {
			t.Fatal("invalid receiver result")
		}
		return r
	}
	if r := run("inspect", target, ""); r.State != "missing" {
		t.Fatalf("initial=%+v", r)
	}
	r := run("create", target, token)
	if r.State != "present" || !pairProofMatches(token, challenge, r.Proof) {
		t.Fatal("creation proof failed")
	}
	b, e := os.ReadFile(target)
	if e != nil || string(b) != "AWF_WINDOWS_TOKEN="+token+"\n" {
		t.Fatal("env contract mismatch")
	}
	st, _ := os.Stat(target)
	if st.Mode().Perm() != 0600 {
		t.Fatal("env mode not 0600")
	}
	if r := run("create", target, strings.Repeat("F", 64)); r.State != "exists" {
		t.Fatal("existing destination not refused")
	}
	if r := run("inspect", target, ""); r.State != "present" || !pairProofMatches(token, challenge, r.Proof) {
		t.Fatal("existing credential changed")
	}
	for _, name := range []string{"malformed", "broad", "hardlink", "symlink", "fifo", "directory"} {
		t.Run(name, func(t *testing.T) {
			p := filepath.Join(root, name)
			switch name {
			case "malformed":
				_ = os.WriteFile(p, []byte("bad"), 0600)
			case "broad":
				_ = os.WriteFile(p, b, 0644)
			case "hardlink":
				if e := os.Link(target, p); e != nil {
					t.Fatal(e)
				}
				defer os.Remove(p)
			case "symlink":
				if e := os.Symlink(target, p); e != nil {
					t.Fatal(e)
				}
			case "fifo":
				c := exec.Command("mkfifo", p)
				if e := c.Run(); e != nil {
					t.Skip("mkfifo unavailable")
				}
			case "directory":
				_ = os.Mkdir(p, 0700)
			}
			if r := run("inspect", p, ""); r.State != "unknown" {
				t.Fatalf("unsafe destination accepted %+v", r)
			}
			if r := run("create", p, token); r.State != "exists" {
				t.Fatalf("unsafe destination was not preserved %+v", r)
			}
		})
	}
	for _, p := range []string{filepath.Join(root, "absent", "env"), root + "/../escape.env"} {
		if r := run("create", p, token); r.State != "unknown" {
			t.Fatal("invalid parent/traversal accepted")
		}
	}
	parent := filepath.Join(root, "broad-parent")
	_ = os.Mkdir(parent, 0755)
	if r := run("create", filepath.Join(parent, "env"), token); r.State != "unknown" {
		t.Fatal("broad parent accepted")
	}
	symlink := filepath.Join(root, "linked-parent")
	if e := os.Symlink(root, symlink); e != nil {
		t.Fatal(e)
	}
	if r := run("create", filepath.Join(symlink, "other.env"), token); r.State != "unknown" {
		t.Fatal("linked ancestor accepted")
	}
}

func TestPairResponseParserSuppressesUntrustedOutput(t *testing.T) {
	secret := strings.Repeat("A", 64)
	for _, raw := range []string{"", "null", "[]", "not-json " + secret, `{"state":"missing","extra":"` + secret + `"}`, `{"state":"missing"}{"state":"present"}`, `{"state":"present","proof":"` + secret + `"}`, `{"state":"missing","proof":"` + strings.Repeat("a", 64) + `"}`, `{"state":"` + secret + `"}`, strings.Repeat(secret, 65)} {
		if _, e := decodePairResponse([]byte(raw)); e == nil {
			t.Fatalf("invalid remote response accepted")
		} else if strings.Contains(e.Error(), secret) {
			t.Fatal("remote content leaked in parser error")
		}
	}
	for _, state := range []string{"missing", "exists", "unknown"} {
		if r, e := decodePairResponse([]byte(`{"state":"` + state + `"}`)); e != nil || r.State != state {
			t.Fatal("valid state rejected")
		}
	}
	proof := strings.Repeat("a", 64)
	if r, e := decodePairResponse([]byte(`{"state":"present","proof":"` + proof + `"}`)); e != nil || r.Proof != proof {
		t.Fatal("valid proof response rejected")
	}
}

func TestPairRemoteProgramRejectsMalformedRequests(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Linux receiver fixtures")
	}
	python, e := exec.LookPath("python3")
	if e != nil {
		t.Skip("python3 unavailable")
	}
	root := t.TempDir()
	_ = os.Chmod(root, 0700)
	target := filepath.Join(root, "node.env")
	secret := strings.Repeat("AB0123CD", 8)
	valid := pairRequest{Op: "create", Path: target, Challenge: strings.Repeat("a1", 32), Token: secret}
	b, _ := json.Marshal(valid)
	for _, raw := range []string{"", "{}", "null", "[]", "1", `{"op":1}`, strings.Repeat("x", 4097), string(b) + "{}", strings.Replace(string(b), `"op":"create"`, `"op":"unsupported"`, 1), strings.Replace(string(b), `"path":"`+target+`"`, `"path":123`, 1), strings.Replace(string(b), `"challenge":"`+valid.Challenge+`"`, `"challenge":null`, 1), strings.Replace(string(b), `"token":"`+secret+`"`, `"token":[]`, 1), strings.Replace(string(b), secret, strings.ToLower(secret), 1), strings.Replace(string(b), `"op":"create"`, `"op":"inspect"`, 1)} {
		c := exec.Command(python, "-c", remotePairProgram)
		c.Stdin = strings.NewReader(raw)
		out, e := c.Output()
		if e != nil {
			t.Fatal("receiver crashed on malformed input")
		}
		r, e := decodePairResponse(out)
		if e != nil || r.State != "unknown" {
			t.Fatal("malformed request accepted")
		}
		if bytes.Contains(out, []byte(secret)) {
			t.Fatal("receiver echoed token")
		}
		if _, e := os.Lstat(target); !os.IsNotExist(e) {
			t.Fatal("malformed request created destination")
		}
	}
	// A restrictive caller umask cannot silently break the exact 0600 contract.
	script := "import os\nos.umask(0o777)\n" + remotePairProgram
	c := exec.Command(python, "-c", script)
	c.Stdin = bytes.NewReader(b)
	out, e := c.Output()
	if e != nil {
		t.Fatal(e)
	}
	r, e := decodePairResponse(out)
	if e != nil || r.State != "present" || !pairProofMatches(secret, valid.Challenge, r.Proof) {
		t.Fatal("restrictive umask broke creation")
	}
	st, e := os.Stat(target)
	if e != nil || st.Mode().Perm() != 0600 {
		t.Fatal("restrictive umask altered final file privacy")
	}
}
