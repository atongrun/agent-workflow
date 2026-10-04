package hostinstall

import (
	"fmt"
	"os"
	"os/exec"
	"runtime"
	"strconv"
	"strings"
)

type Environment struct {
	OS           string `json:"os"`
	Arch         string `json:"arch"`
	Distribution string `json:"distribution"`
	Release      string `json:"release"`
	Systemd      bool   `json:"systemd"`
	Glibc        bool   `json:"glibc"`
}
type Finding struct {
	Check  string `json:"check"`
	Status string `json:"status"`
	Detail string `json:"detail"`
}
type Plan struct {
	Schema       int               `json:"schema"`
	ReadyToStage bool              `json:"readyToStage"`
	Environment  Environment       `json:"environment"`
	Findings     []Finding         `json:"findings"`
	Components   []Component       `json:"components"`
	Paths        map[string]string `json:"paths"`
	Pending      []string          `json:"pending"`
}

func BuildPlan(m Manifest, e Environment) (Plan, error) {
	if err := m.Validate(); err != nil {
		return Plan{}, err
	}
	p := Plan{Schema: 1, ReadyToStage: true, Environment: e, Findings: []Finding{}, Components: m.Components,
		Paths:   map[string]string{"hostProgram": "/opt/awf", "piProgram": "/opt/pi-cli", "magpieProgram": "/opt/magpie", "hostConfig": "/etc/awf/host.json", "hostState": "/var/lib/awf", "servicePiAgent": "/var/lib/awf/pi-agent"},
		Pending: []string{"program installation", "explicit account and credential initialization", "loopback service configuration", "systemd enable/start", "actual model catalog selection", "maintenance gate and explicit idle reload"}}
	checks := []struct {
		key    string
		ok     bool
		detail string
	}{
		{"platform", e.OS == "linux" && e.Arch == "amd64" && m.Arch == e.Arch, "only Linux amd64 is in the initial acceptance matrix; arm64 is reserved"},
		{"distribution", e.Distribution == "ubuntu" && (e.Release == "22.04" || e.Release == "24.04"), "Ubuntu 22.04 or 24.04 required"},
		{"libc", e.Glibc, "glibc loader presence required; version/native acceptance remains unverified"},
		{"service-manager", e.Systemd, "running systemd required"},
	}
	for _, check := range checks {
		status := "observed"
		if !check.ok {
			status = "blocked"
			p.ReadyToStage = false
		}
		p.Findings = append(p.Findings, Finding{check.key, status, check.detail})
	}
	return p, nil
}

// ObserveEnvironment reads metadata only: no executable/version probes or network.
func ObserveEnvironment() Environment {
	e := Environment{OS: runtime.GOOS, Arch: runtime.GOARCH}
	if data, err := os.ReadFile("/etc/os-release"); err == nil && len(data) < 64<<10 {
		for _, line := range strings.Split(string(data), "\n") {
			fields := strings.SplitN(line, "=", 2)
			if len(fields) != 2 {
				continue
			}
			value := strings.Trim(fields[1], `"`)
			switch fields[0] {
			case "ID":
				e.Distribution = value
			case "VERSION_ID":
				e.Release = value
			}
		}
	}
	info, err := os.Stat("/run/systemd/system")
	e.Systemd = err == nil && info.IsDir()
	loader := "/lib64/ld-linux-x86-64.so.2"
	if e.Arch == "arm64" {
		loader = "/lib/ld-linux-aarch64.so.1"
	}
	info, err = os.Stat(loader)
	e.Glibc = err == nil && info.Mode().IsRegular()
	return e
}

func Doctor(m Manifest, e Environment) (Plan, error) {
	return inspectDoctor(m, e, os.Lstat, exec.LookPath, listenerStatus)
}
func inspectDoctor(m Manifest, e Environment, lstat func(string) (os.FileInfo, error), lookPath func(string) (string, error), portStatus func(int) string) (Plan, error) {
	p, err := BuildPlan(m, e)
	if err != nil {
		return p, err
	}
	for _, name := range []string{"hostProgram", "piProgram", "magpieProgram", "hostConfig", "hostState", "servicePiAgent"} {
		path := p.Paths[name]
		info, err := lstat(path)
		status, detail := "absent", "not present; no path was created"
		if err == nil {
			status, detail = "needs_review", "existing path; ownership and installation identity require explicit review"
			if info.Mode()&os.ModeSymlink != 0 {
				detail = "existing link; automatic adoption is unsupported"
			}
			p.ReadyToStage = false
		} else if !os.IsNotExist(err) {
			status, detail = "unknown", "path metadata unavailable"
			p.ReadyToStage = false
		}
		p.Findings = append(p.Findings, Finding{name, status, detail})
	}
	for _, name := range []string{"pi", "node", "magpie"} {
		if _, err := lookPath(name); err == nil {
			p.Findings = append(p.Findings, Finding{name + "-command", "needs_review", "existing command resolved; not executed or adopted"})
			p.ReadyToStage = false
		}
	}
	for _, port := range []int{7070, 3425} {
		status := portStatus(port)
		if status != "free_observed" {
			p.ReadyToStage = false
		}
		p.Findings = append(p.Findings, Finding{fmt.Sprintf("port-%d", port), status, "kernel listener snapshot only; no bind, connection or reservation"})
	}
	return p, nil
}
func listenerStatus(port int) string {
	for _, file := range []string{"/proc/net/tcp", "/proc/net/tcp6"} {
		data, err := os.ReadFile(file)
		if err != nil {
			return "unknown"
		}
		for _, line := range strings.Split(string(data), "\n") {
			fields := strings.Fields(line)
			if len(fields) < 4 || fields[3] != "0A" {
				continue
			}
			_, p, ok := strings.Cut(fields[1], ":")
			if !ok {
				continue
			}
			n, err := strconv.ParseInt(p, 16, 32)
			if err == nil && n == int64(port) {
				return "occupied"
			}
		}
	}
	return "free_observed"
}
