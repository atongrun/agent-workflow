package lifecycle

import (
	"bytes"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
)

// Doctor intentionally uses metadata only. It does not call lifecycle locks,
// configuration loaders, DPAPI, runtime control, or any mutating helper.
type doctorFinding struct {
	Check  string             `json:"check"`
	Status string             `json:"status"`
	Detail string             `json:"detail"`
	ACL    *doctorACLMetadata `json:"acl,omitempty"`
}
type doctorReport struct {
	Schema   int             `json:"schema"`
	Findings []doctorFinding `json:"findings"`
}
type doctorPlatform struct {
	context      func() (string, string)
	localAppData func() (string, error)
	physical     func(string) (string, error)
	acl          func(string) (string, error)
	aclDetails   func(string) doctorACLMetadata
	reparse      func(string) error
}

func runDoctor(args []string, out io.Writer) error {
	f := flag.NewFlagSet("doctor", flag.ContinueOnError)
	f.SetOutput(out)
	asJSON := f.Bool("json", false, "print the read-only diagnostic snapshot as JSON")
	if err := f.Parse(args); err != nil {
		return err
	}
	if f.NArg() != 0 {
		return errors.New("usage: awf doctor [--json]")
	}
	report := inspectDoctor(os.Getenv("LOCALAPPDATA"), nativeDoctorPlatform(), exec.LookPath)
	if *asJSON {
		return json.NewEncoder(out).Encode(report)
	}
	var text bytes.Buffer
	fmt.Fprintln(&text, "AWF doctor: read-only metadata snapshot; no changes made.")
	for _, finding := range report.Findings {
		// Quote OS-supplied text: paths cannot inject terminal controls or lines.
		fmt.Fprintf(&text, "%s: %s %q\n", finding.Check, finding.Status, finding.Detail)
		if finding.ACL != nil {
			renderDoctorACL(&text, finding.ACL)
		}
	}
	fmt.Fprintln(&text, "This snapshot does not establish job idleness, credential validity, or permission to repair. No install, update, or recovery was performed.")
	_, err := io.Copy(out, &text)
	return err
}

func inspectDoctor(local string, platform doctorPlatform, lookPath func(string) (string, error)) doctorReport {
	r := doctorReport{Schema: 1}
	add := func(check, status, detail string) {
		r.Findings = append(r.Findings, doctorFinding{Check: check, Status: status, Detail: detail})
	}
	add("process", "observed", runtime.GOOS+"/"+runtime.GOARCH+"; process architecture only")
	status, detail := platform.context()
	add("package-context", status, detail)
	known, err := platform.localAppData()
	if err != nil {
		add("profile", "unknown", "Windows known-folder lookup unavailable")
	} else if local == "" || !filepath.IsAbs(local) || validateInstallerPath(filepath.Clean(known), filepath.Clean(local), nil) != nil {
		add("profile", "mismatch", "LOCALAPPDATA differs from the Windows known folder")
	} else {
		add("profile", "observed", known)
	}
	if exe, err := os.Executable(); err == nil {
		add("executable", "observed", exe)
	} else {
		add("executable", "unknown", "executable path unavailable")
	}
	if resolved, err := lookPath("awf"); err == nil {
		add("command-resolution", "observed", resolved)
	} else {
		add("command-resolution", "unknown", "awf was not resolved through this process's executable search")
	}
	add("shell-resolution", "unknown", "parent shell aliases, functions and future-shell PATH are not inspected")
	if local == "" || !filepath.IsAbs(local) {
		add("root", "unknown", "LOCALAPPDATA is missing or not absolute")
		return r
	}
	root := filepath.Join(local, "AWF")
	add("intended-root", "observed", root)
	if resolved, err := lookPath("awf"); err == nil {
		if validateInstallerPath(filepath.Join(root, "bin", "awf.exe"), resolved, nil) != nil {
			add("launcher-resolution", "mismatch", "this process resolves awf to a different path than the intended launcher")
		} else {
			add("launcher-resolution", "observed", "this process resolves the intended launcher; identity not verified")
		}
	}
	// Fixed inventory only; never walk an arbitrary tree or read file contents.
	paths := []struct {
		name      string
		directory bool
	}{
		{"", true}, {"bin", true}, {"bin/awf.exe", false}, {"versions", true},
		{"installation.json", false}, {"current.json", false}, {"channel.json", false}, {"config.json", false},
		{"runtime.json", false}, {"starting.json", false}, {"private", true}, {"private/runtime.json", false}, {"private/starting.json", false}, {"state", true}, {"state/jobs", true},
		{"credentials", true}, {"credentials/windows-node", true}, {"credentials/windows-node/node-token.dpapi", false},
	}
	for _, item := range paths {
		path := filepath.Join(root, filepath.FromSlash(item.name))
		label := item.name
		if label == "" {
			label = "root"
		}
		if err := doctorAncestors(path, platform.reparse); err != nil {
			if os.IsNotExist(err) {
				add(label, "missing", "path is absent")
			} else {
				add(label, "unknown", "path is unreadable or contains an unsupported link/reparse boundary")
			}
			continue
		}
		st, err := os.Lstat(path)
		if err != nil {
			add(label, "unknown", "metadata unavailable")
			continue
		}
		if (item.directory && !st.IsDir()) || (!item.directory && !st.Mode().IsRegular()) {
			add(label, "mismatch", "unexpected filesystem object type")
			continue
		}
		add(label, "present", "expected filesystem object type; contents not inspected")
		actual, err := platform.physical(path)
		if err != nil {
			add(label+".physical", "unknown", "physical path query unavailable")
		} else if validateInstallerPath(path, actual, nil) != nil {
			add(label+".physical", "mismatch", actual)
		} else {
			add(label+".physical", "observed", actual)
		}
		if platform.aclDetails != nil {
			metadata := platform.aclDetails(path)
			status, detail := summarizeDoctorACLRole(&metadata, pathPermissionRole(root, path))
			r.Findings = append(r.Findings, doctorFinding{Check: label + ".acl", Status: status, Detail: detail, ACL: &metadata})
		} else {
			metadata, err := platform.acl(path)
			if err != nil {
				add(label+".acl", "unknown", metadata)
			} else {
				add(label+".acl", "private", metadata)
			}
		}
	}
	add("configuration-and-runtime", "unknown", "file contents, configured external credential paths, runtime health and job states are not inspected")
	return r
}

func doctorAncestors(path string, reparse func(string) error) error {
	parent := filepath.Dir(path)
	if parent != path {
		if err := doctorAncestors(parent, reparse); err != nil {
			return err
		}
	}
	st, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if st.Mode()&os.ModeSymlink != 0 {
		return errors.New("linked path")
	}
	return reparse(path)
}
