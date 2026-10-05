//go:build linux

package hostinstall

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"net/http"
	"os"
	"path"
	"strconv"
	"strings"
	"time"
)

func properties(out []byte) map[string]string {
	values := map[string]string{}
	for _, line := range strings.Split(string(out), "\n") {
		if k, v, ok := strings.Cut(line, "="); ok {
			values[k] = v
		}
	}
	return values
}

func (a *nativeAdapter) unit(ctx context.Context, unit string) error {
	expected := hostUnitProposal
	if unit == "awf-magpie.service" {
		expected = magpieUnitProposal
	} else if unit != "awf-host.service" {
		return errors.New("unknown native unit")
	}
	name := "etc/systemd/system/" + unit
	if err := a.parents(name); err != nil {
		return err
	}
	if err := a.trusted(name, false); err != nil {
		return err
	}
	info, _ := a.root.Lstat(name)
	if info.Mode().Perm() != 0644 {
		return errors.New("systemd unit permissions changed")
	}
	b, err := a.boundedRead(name, int64(len(expected))+1)
	if err != nil || string(b) != expected {
		return errors.New("installed systemd unit changed")
	}
	out, err := a.command(ctx, "/usr/bin/systemctl", "show", unit, "--property=FragmentPath,DropInPaths,User,Group,KillMode,Slice", "--no-pager")
	if err != nil {
		return err
	}
	values := properties(out)
	for key, want := range map[string]string{"FragmentPath": "/etc/systemd/system/" + unit, "DropInPaths": "", "User": "awf", "Group": "awf", "KillMode": "control-group", "Slice": "system.slice"} {
		if value, ok := values[key]; !ok || value != want {
			return errors.New("systemd unit ownership, overrides or control-group contract changed")
		}
	}
	return nil
}

// Read-only checks before any program/account mutation. Include vendor/runtime
// definitions, aliases and dependency links, plus the manager's loaded state.
func (a *nativeAdapter) freshUnits(ctx context.Context) error {
	for _, unit := range nativeUnits {
		out, err := a.command(ctx, "/usr/bin/systemctl", "show", unit, "--property=LoadState,FragmentPath,DropInPaths", "--no-pager")
		if err != nil {
			return errors.New("systemd fresh-unit lookup unavailable")
		}
		v := properties(out)
		if v["LoadState"] != "not-found" || v["FragmentPath"] != "" || v["DropInPaths"] != "" {
			return errors.New("existing systemd unit or overrides require inspection")
		}
	}
	count := 0
	for _, dir := range []string{"etc/systemd/system.control", "run/systemd/system.control", "run/systemd/transient", "run/systemd/generator.early", "etc/systemd/system", "etc/systemd/system.attached", "run/systemd/system", "run/systemd/system.attached", "run/systemd/generator", "usr/local/lib/systemd/system", "usr/lib/systemd/system", "lib/systemd/system", "run/systemd/generator.late"} {
		entries, err := fs.ReadDir(a.root.FS(), dir)
		if os.IsNotExist(err) {
			continue
		}
		if err != nil {
			return errors.New("systemd unit search path unreadable")
		}
		for _, entry := range entries {
			count++
			if count > 65536 {
				return errors.New("systemd lookup bound")
			}
			name := entry.Name()
			if name == "awf-host.service" || name == "awf-magpie.service" || name == "awf-host.service.d" || name == "awf-magpie.service.d" || name == "awf-.service.d" {
				return errors.New("existing systemd AWF definition requires inspection")
			}
			full := dir + "/" + name
			if entry.Type()&os.ModeSymlink != 0 {
				target, err := a.root.Readlink(full)
				if err != nil {
					return err
				}
				if nativeUnitName(path.Base(target)) {
					return errors.New("existing systemd AWF alias requires inspection")
				}
			}
			if name == "service.d" || strings.HasSuffix(name, ".wants") || strings.HasSuffix(name, ".requires") {
				children, err := fs.ReadDir(a.root.FS(), full)
				if err != nil {
					return errors.New("systemd dependency/drop-in directory unreadable")
				}
				if name == "service.d" && len(children) != 0 {
					return errors.New("global systemd service overrides require inspection")
				}
				for _, child := range children {
					count++
					if count > 65536 {
						return errors.New("systemd lookup bound")
					}
					if nativeUnitName(child.Name()) {
						return errors.New("existing systemd AWF dependency requires inspection")
					}
					if child.Type()&os.ModeSymlink != 0 {
						target, err := a.root.Readlink(full + "/" + child.Name())
						if err != nil {
							return err
						}
						if nativeUnitName(path.Base(target)) {
							return errors.New("existing systemd AWF dependency alias requires inspection")
						}
					}
				}
			}
		}
	}
	return nil
}
func nativeUnitName(name string) bool {
	return name == "awf-host.service" || name == "awf-magpie.service"
}

func (a *nativeAdapter) boundedRead(name string, limit int64) ([]byte, error) {
	f, err := a.root.Open(name)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	b, err := io.ReadAll(io.LimitReader(f, limit+1))
	if err != nil || int64(len(b)) > limit {
		return nil, errors.New("native read bound")
	}
	return b, nil
}

type nativeListener struct{ port, inode string }

func (a *nativeAdapter) listeners() ([]nativeListener, error) {
	var result []nativeListener
	for _, name := range []string{"proc/net/tcp", "proc/net/tcp6"} {
		b, err := a.boundedRead(name, 1<<20)
		if err != nil {
			return nil, errors.New("kernel listener snapshot unavailable")
		}
		for _, line := range strings.Split(string(b), "\n") {
			fields := strings.Fields(line)
			if len(fields) < 4 || fields[3] != "0A" {
				continue
			}
			address, port, ok := strings.Cut(fields[1], ":")
			if !ok || (port != "1B9E" && port != "0D61") {
				continue
			}
			if len(fields) < 10 || address != "0100007F" {
				return nil, errors.New("AWF or Magpie listener is not fixed IPv4 loopback")
			}
			inode, err := strconv.ParseUint(fields[9], 10, 64)
			if err != nil || inode == 0 {
				return nil, errors.New("kernel listener inode unavailable")
			}
			result = append(result, nativeListener{port, fields[9]})
		}
	}
	return result, nil
}
func (a *nativeAdapter) unoccupiedPorts() error {
	listeners, err := a.listeners()
	if err != nil {
		return err
	}
	if len(listeners) != 0 {
		return errors.New("AWF/Magpie ports are already occupied; inspect without stopping other applications")
	}
	return nil
}

func (a *nativeAdapter) activePID(ctx context.Context, unit string) (string, error) {
	out, err := a.command(ctx, "/usr/bin/systemctl", "show", unit, "--property=ActiveState,MainPID,ControlGroup", "--no-pager")
	if err != nil {
		return "", err
	}
	values := properties(out)
	pid, err := strconv.Atoi(values["MainPID"])
	if err != nil || pid <= 0 || values["ActiveState"] != "active" || values["ControlGroup"] != "/system.slice/"+unit {
		return "", errors.New("systemd service is not active in its fixed control group")
	}
	want := "/opt/awf/awf"
	if unit == "awf-magpie.service" {
		want = "/opt/magpie/magpie"
	}
	exe, err := a.root.Readlink("proc/" + values["MainPID"] + "/exe")
	if err != nil || exe != want {
		return "", errors.New("systemd main process executable changed")
	}
	return values["MainPID"], nil
}

func (a *nativeAdapter) groupPIDs(unit string) (map[string]bool, error) {
	pids := map[string]bool{}
	count := 0
	err := fs.WalkDir(a.root.FS(), "sys/fs/cgroup/system.slice/"+unit, func(name string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		count++
		if count > 4096 {
			return errors.New("cgroup traversal bound")
		}
		if entry.Name() != "cgroup.procs" {
			return nil
		}
		b, err := a.boundedRead(name, 64<<10)
		if err != nil {
			return err
		}
		for _, pid := range strings.Fields(string(b)) {
			n, err := strconv.Atoi(pid)
			if err != nil || n <= 0 || strconv.Itoa(n) != pid {
				return errors.New("invalid cgroup process identity")
			}
			pids[pid] = true
			if len(pids) > 4096 {
				return errors.New("cgroup process bound")
			}
		}
		return nil
	})
	return pids, err
}

func (a *nativeAdapter) unitSockets(ctx context.Context, unit string) (map[string]bool, string, error) {
	if err := a.unit(ctx, unit); err != nil {
		return nil, "", err
	}
	main, err := a.activePID(ctx, unit)
	if err != nil {
		return nil, "", err
	}
	pids, err := a.groupPIDs(unit)
	if err != nil || !pids[main] {
		return nil, "", errors.New("systemd main process missing from cgroup")
	}
	owned := map[string]bool{}
	for pid := range pids {
		entries, err := fs.ReadDir(a.root.FS(), "proc/"+pid+"/fd")
		if err != nil {
			if pid != main && os.IsNotExist(err) {
				continue
			}
			return nil, "", errors.New("service socket ownership unavailable")
		}
		if len(entries) > 65536 {
			return nil, "", errors.New("service descriptor bound")
		}
		for _, entry := range entries {
			target, err := a.root.Readlink("proc/" + pid + "/fd/" + entry.Name())
			if err != nil {
				continue
			} // descriptors may close during inspection
			if strings.HasPrefix(target, "socket:[") && strings.HasSuffix(target, "]") {
				owned[strings.TrimSuffix(strings.TrimPrefix(target, "socket:["), "]")] = true
			}
		}
	}
	return owned, main, nil
}

// Verify ownership before posting a maintenance mutation as well as after
// startup. An unrelated Host binary outside this unit must not acquire a lease.
func (a *nativeAdapter) hostListenerOwned(ctx context.Context) error {
	owned, main, err := a.unitSockets(ctx, "awf-host.service")
	if err != nil {
		return err
	}
	listeners, err := a.listeners()
	if err != nil {
		return err
	}
	seen := false
	for _, listener := range listeners {
		if listener.port != "1B9E" {
			continue
		}
		if !owned[listener.inode] {
			return errors.New("Host maintenance listener belongs to another process")
		}
		seen = true
	}
	if !seen {
		return errors.New("owned Host maintenance listener unavailable")
	}
	after, err := a.activePID(ctx, "awf-host.service")
	if err != nil || after != main {
		return errors.New("Host process changed during maintenance verification")
	}
	return nil
}

func (a *nativeAdapter) loopbackListeners(ctx context.Context) error {
	owned := map[string]map[string]bool{}
	mains := map[string]string{}
	for i, unit := range nativeUnits {
		sockets, main, err := a.unitSockets(ctx, unit)
		if err != nil {
			return err
		}
		mains[unit] = main
		port := "1B9E"
		if i == 1 {
			port = "0D61"
		}
		owned[port] = sockets
	}
	listeners, err := a.listeners()
	if err != nil {
		return err
	}
	seen := map[string]bool{}
	for _, listener := range listeners {
		if !owned[listener.port][listener.inode] {
			return errors.New("AWF/Magpie listener belongs to another process")
		}
		seen[listener.port] = true
	}
	if !seen["1B9E"] || !seen["0D61"] {
		return errors.New("AWF and Magpie owned listeners not both observed")
	}
	for _, unit := range nativeUnits {
		main, err := a.activePID(ctx, unit)
		if err != nil || main != mains[unit] {
			return errors.New("service process changed during health verification")
		}
	}
	return nil
}

func (a *nativeAdapter) magpieHealth(ctx context.Context, m Manifest) error {
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, "http://127.0.0.1:3425/", nil)
	response, err := a.client.Do(req)
	if err != nil {
		return errors.New("loopback Magpie health unavailable")
	}
	defer response.Body.Close()
	b, err := io.ReadAll(io.LimitReader(response.Body, (64<<10)+1))
	var info struct{ Name, Version string }
	if err != nil || len(b) > 64<<10 || response.StatusCode != 200 || json.Unmarshal(b, &info) != nil || info.Name != "magpie" {
		return errors.New("Magpie read-only identity health failed")
	}
	for _, component := range m.Components {
		if component.ID == "magpie" && strings.TrimPrefix(info.Version, "v") != strings.TrimPrefix(component.Version, "v") {
			return errors.New("Magpie health version differs from installed artifact")
		}
	}
	return nil
}

// Attempt every trusted fixed unit independently, including verification after
// a failed stop. One failure must not abandon the other service's cleanup.
func (a *nativeAdapter) stopUnits(ctx context.Context) error {
	var problems []error
	for _, unit := range nativeUnits {
		if err := a.unit(ctx, unit); err != nil {
			problems = append(problems, fmt.Errorf("%s: %w", unit, err))
			continue
		}
		if _, err := a.command(ctx, "/usr/bin/systemctl", "stop", unit); err != nil {
			problems = append(problems, fmt.Errorf("%s: %w", unit, err))
		}
		if err := a.stopped(ctx, unit); err != nil {
			problems = append(problems, fmt.Errorf("%s: %w", unit, err))
		}
	}
	return errors.Join(problems...)
}

func (a *nativeAdapter) failedStart(_ context.Context, cause error) error {
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()
	err := a.phase("bundle", "failed-start-stop", func() error { return a.stopUnits(ctx) })
	if err != nil {
		return errors.Join(cause, errors.New("startup/health failed and systemd cleanup is unverified; inspect services and retained maintenance lease"), err)
	}
	return cause
}
