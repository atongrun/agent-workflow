//go:build linux

package hostinstall

import (
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"

	"github.com/atongrun/agent-workflow/internal/host"
)

func (a *nativeAdapter) hostConfiguration() error {
	var config host.Config
	if err := a.read("etc/awf/host.json", &config); err != nil {
		return err
	}
	if config.Listen != "127.0.0.1:7070" || config.InternalURL != "http://127.0.0.1:7070" || config.DataDir != "/var/lib/awf" || config.PiAgentDir != "/var/lib/awf/pi-agent" || config.PiBinary != "/opt/pi-cli/awf-launcher.mjs" || config.PiExtension != "/opt/awf/extensions/awf.ts" || !config.EnableMaintenance || config.TokenEnv != "AWF_HOST_TOKEN" || config.ExtensionTokenEnv != "AWF_EXTENSION_TOKEN" {
		return errors.New("Host native paths, loopback and maintenance configuration must be retained")
	}
	return nil
}

// Missing LAN is Magpie's supported default false (its save format omits false).
// Settings remain ordinary upstream JSON; only machine safety fields are fixed.
func checkedMagpieSettings(b []byte) (map[string]any, error) {
	var values map[string]any
	if len(b) > 1<<20 || uniqueJSON(b) != nil || json.Unmarshal(b, &values) != nil || values == nil {
		return nil, errors.New("invalid Magpie settings")
	}
	if lan, exists := values["lan"]; exists {
		if v, ok := lan.(bool); !ok || v {
			return nil, errors.New("Magpie LAN must be false or omitted")
		}
	}
	return values, nil
}

func (a *nativeAdapter) magpiePortable() error {
	for _, name := range []string{"opt/magpie/.portable", "opt/magpie/data"} {
		if _, err := a.root.Lstat(name); !os.IsNotExist(err) {
			return errors.New("Magpie portable configuration requires inspection")
		}
	}
	return nil
}

// Read only. Invoked by ExecStartPre as awf on every boot/restart. The Magpie
// unit binds the administrator-owned snapshot over its service-owned settings.
func (a *nativeAdapter) serviceCheck(component string, requireMount bool) error {
	if component == "host" {
		return a.hostConfiguration()
	}
	if component != "magpie" {
		return errors.New("unknown service check")
	}
	if err := a.magpiePortable(); err != nil {
		return err
	}
	name := "etc/awf/magpie-settings.json"
	if err := a.parents(name); err != nil {
		return err
	}
	if err := a.trusted(name, false); err != nil {
		return err
	}
	info, _ := a.root.Lstat(name)
	if info.Mode().Perm() != 0640 {
		return errors.New("Magpie snapshot permissions changed")
	}
	file, err := a.root.Open(name)
	if err != nil {
		return err
	}
	b, err := io.ReadAll(io.LimitReader(file, (1<<20)+1))
	file.Close()
	if err != nil {
		return err
	}
	values, err := checkedMagpieSettings(b)
	if err != nil {
		return err
	}
	if values["noAutoUpdate"] != true || values["noStats"] != true {
		return errors.New("Magpie native safety settings changed")
	}
	if requireMount {
		target, err := a.root.Lstat("var/lib/awf/magpie-config/magpie/settings.json")
		if err != nil || !target.Mode().IsRegular() || !os.SameFile(info, target) {
			return errors.New("Magpie read-only settings bind is absent")
		}
		// Matching inode alone could be a hard link. Require the kernel mount
		// record to mark this exact target read-only in the service namespace.
		f, err := a.root.Open("proc/self/mountinfo")
		if err != nil {
			return err
		}
		data, err := io.ReadAll(io.LimitReader(f, (4<<20)+1))
		f.Close()
		if err != nil || len(data) > 4<<20 || !readOnlySettingsMount(data) {
			return errors.New("Magpie settings mount is not read-only")
		}
	}
	return nil
}

func (a *nativeAdapter) snapshotMagpie() error {
	if err := a.magpiePortable(); err != nil {
		return err
	}
	u, err := a.lookup("awf")
	if err != nil {
		return err
	}
	uid, err := strconv.Atoi(u.Uid)
	if err != nil || uid <= 0 {
		return errors.New("invalid service identity")
	}
	gid, err := strconv.Atoi(u.Gid)
	if err != nil || gid <= 0 {
		return errors.New("invalid service group")
	}
	state, err := os.OpenRoot(filepath.Join(a.root.Name(), "var/lib/awf"))
	if err != nil {
		return err
	}
	defer state.Close()
	// Reject links in all state components, including an in-root settings link.
	for _, name := range []string{".", "magpie-config", "magpie-config/magpie", "magpie-config/magpie/settings.json"} {
		info, err := state.Lstat(name)
		if err != nil {
			return err
		}
		st, ok := info.Sys().(*syscall.Stat_t)
		directory := name != "magpie-config/magpie/settings.json"
		if !ok || int(st.Uid) != uid || int(st.Gid) != gid || info.Mode()&(os.ModeSymlink|os.ModeSetuid|os.ModeSetgid) != 0 || info.Mode().Perm()&0077 != 0 || info.IsDir() != directory || (!directory && !info.Mode().IsRegular()) {
			return errors.New("Magpie private state ownership/type changed")
		}
	}
	f, err := state.Open("magpie-config/magpie/settings.json")
	if err != nil {
		return err
	}
	b, err := io.ReadAll(io.LimitReader(f, (1<<20)+1))
	f.Close()
	if err != nil {
		return err
	}
	values, err := checkedMagpieSettings(b)
	if err != nil {
		return err
	}
	values["lan"], values["noAutoUpdate"], values["noStats"] = false, true, true
	data, err := json.Marshal(values)
	if err != nil {
		return err
	}
	return a.replaceMetadata("etc/awf/magpie-settings.json", data, 0640, gid)
}

func readOnlySettingsMount(b []byte) bool {
	for _, line := range strings.Split(string(b), "\n") {
		fields := strings.Fields(line)
		if len(fields) < 7 || fields[4] != "/var/lib/awf/magpie-config/magpie/settings.json" {
			continue
		}
		for _, flag := range strings.Split(fields[5], ",") {
			if flag == "ro" {
				return true
			}
		}
	}
	return false
}
