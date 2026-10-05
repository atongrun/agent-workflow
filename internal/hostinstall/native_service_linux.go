//go:build linux

package hostinstall

import (
	"context"
	"errors"
	"io"
	"strconv"
	"strings"
	"time"
)

func (a *nativeAdapter) unit(ctx context.Context, unit string) error {
	out, err := a.command(ctx, "/usr/bin/systemctl", "show", unit, "--property=FragmentPath,DropInPaths,User,Group,KillMode,Slice", "--no-pager")
	if err != nil {
		return err
	}
	values := map[string]string{}
	for _, line := range strings.Split(string(out), "\n") {
		k, v, ok := strings.Cut(line, "=")
		if ok {
			values[k] = v
		}
	}
	for key, want := range map[string]string{"FragmentPath": "/etc/systemd/system/" + unit, "DropInPaths": "", "User": "awf", "Group": "awf", "KillMode": "control-group", "Slice": "system.slice"} {
		if value, ok := values[key]; !ok || value != want {
			return errors.New("systemd unit ownership, overrides or control-group contract changed")
		}
	}
	return nil
}

func (a *nativeAdapter) loopbackListeners() error {
	seen := map[string]bool{"1B9E": false, "0D61": false} // 7070 and 3425
	for _, name := range []string{"proc/net/tcp", "proc/net/tcp6"} {
		f, err := a.root.Open(name)
		if err != nil {
			return errors.New("kernel listener snapshot unavailable")
		}
		b, err := io.ReadAll(io.LimitReader(f, (1<<20)+1))
		f.Close()
		if err != nil || len(b) > 1<<20 {
			return errors.New("kernel listener snapshot bound")
		}
		for _, line := range strings.Split(string(b), "\n") {
			fields := strings.Fields(line)
			if len(fields) < 4 || fields[3] != "0A" {
				continue
			}
			address, port, ok := strings.Cut(fields[1], ":")
			if !ok {
				continue
			}
			if _, tracked := seen[port]; !tracked {
				continue
			}
			if address != "0100007F" {
				return errors.New("AWF or Magpie listener is not fixed IPv4 loopback")
			}
			seen[port] = true
		}
	}
	for _, found := range seen {
		if !found {
			return errors.New("AWF and Magpie loopback listeners not both observed")
		}
	}
	return nil
}

func (a *nativeAdapter) started(ctx context.Context, unit string) error {
	out, err := a.command(ctx, "/usr/bin/systemctl", "show", unit, "--property=ActiveState,MainPID,ControlGroup", "--no-pager")
	if err != nil {
		return err
	}
	values := map[string]string{}
	for _, line := range strings.Split(string(out), "\n") {
		if k, v, ok := strings.Cut(line, "="); ok {
			values[k] = v
		}
	}
	pid, err := strconv.Atoi(values["MainPID"])
	if err != nil || pid <= 0 || values["ActiveState"] != "active" || values["ControlGroup"] != "/system.slice/"+unit {
		return errors.New("systemd service is not active in its fixed control group")
	}
	return nil
}

func (a *nativeAdapter) failedStart(_ context.Context, cause error) error {
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()
	err := a.phase("bundle", "failed-start-stop", func() error {
		for _, unit := range nativeUnits {
			if _, err := a.command(ctx, "/usr/bin/systemctl", "stop", unit); err != nil {
				return err
			}
		}
		for _, unit := range nativeUnits {
			if err := a.stopped(ctx, unit); err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		return errors.New("startup/health failed and systemd cleanup is unverified; inspect services and retained maintenance lease")
	}
	return cause
}
