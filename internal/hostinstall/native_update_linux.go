//go:build linux

package hostinstall

import (
	"context"
	"encoding/json"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
)

// AWF updates its fixed programs under the owned durable Host seal and verified
// systemd shutdown. Pi remains at its sole global npm prefix and updates itself.
// Interrupted replacements retain backups and the seal for explicit inspection.
func (a *nativeAdapter) update(ctx context.Context, m Manifest) error {
	old, err := a.installed(ctx)
	if err != nil {
		return err
	}
	if err := a.absent("etc/awf/update-pending.json"); err != nil {
		return err
	}
	if manifestDigest(old.Manifest) == manifestDigest(m) {
		a.event("bundle", "verify-current", "completed")
		return nil
	}
	generation, r, cleanup, err := prepareNativeRuntime(ctx, m, a.observer)
	if err != nil {
		return err
	}
	defer cleanup()
	if err := a.checkPreparedHost(ctx, m, generation); err != nil {
		return err
	}
	if err := a.stopFor(ctx, manifestDigest(m)); err != nil {
		return err
	}
	data, _ := json.Marshal(map[string]any{"schema": 1, "targetManifestSHA256": manifestDigest(m), "phase": "sealed-stopped", "nativeAcceptance": false})
	if err := a.writeNew("etc/awf/update-pending.json", data, 0600); err != nil {
		return err
	}
	if err := a.replacePrepared(ctx, m, generation, r, old); err != nil {
		return err
	}
	if err := a.start(ctx, false); err != nil {
		return err
	}
	return a.root.Remove("etc/awf/update-pending.json")
}

func (a *nativeAdapter) replacePrepared(ctx context.Context, m Manifest, generation string, r InstallReceipt, old nativeReceipt) error {
	b, _ := json.Marshal(r)
	if r.Schema != 2 || r.PiRuntime == nil || r.ManifestSHA256 != manifestDigest(m) || verifyGeneration(generation, r, b) != nil {
		return errors.New("new verified runtime preparation required")
	}
	work, err := os.MkdirTemp(filepath.Join(a.root.Name(), "opt"), ".awf-update-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(work)
	dest, err := os.OpenRoot(work)
	if err != nil {
		return err
	}
	defer dest.Close()
	var links []InstalledFile
	for _, c := range r.Components {
		if c.ID == "pi" {
			continue
		}
		for _, f := range c.Files {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			if f.LinkTarget != "" {
				links = append(links, f)
				continue
			}
			file, err := os.Open(filepath.Join(generation, f.Path))
			if err != nil {
				return err
			}
			copy, err := writeSelected(ctx, dest, f.Path, file, f.Bytes, f.Mode)
			file.Close()
			if err != nil {
				return err
			}
			if copy.SHA256 != f.SHA256 {
				return errors.New("update source changed during copy")
			}
		}
	}
	for _, link := range links {
		if err := createPinnedLink(dest, link); err != nil {
			return err
		}
	}
	if err := filepath.WalkDir(work, func(name string, e fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if e.IsDir() {
			return os.Chmod(name, 0755)
		}
		return nil
	}); err != nil {
		return err
	}
	if err := syncTreeDirectories(work); err != nil {
		return err
	}
	for _, name := range []string{"opt/node", "opt/awf", "opt/magpie"} {
		backup := name + ".before-" + manifestDigest(m)
		if err := a.absent(backup); err != nil {
			return err
		}
		if err := a.trusted(name, true); err != nil {
			return err
		}
		if err := a.phase(filepath.Base(name), "update", func() error {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			if err := a.root.Rename(name, backup); err != nil {
				return err
			}
			return os.Rename(filepath.Join(work, name), filepath.Join(a.root.Name(), name))
		}); err != nil {
			return errors.New("program update incomplete; services remain sealed/stopped, inspect pending marker and retained backups")
		}
	}
	if err := syncDirectory(filepath.Join(a.root.Name(), "opt")); err != nil {
		return err
	}
	// The Pi evidence describes the original installation, not a tree copied by
	// this update. Never restore Pi 1.0.2 over a root-owned upstream update.
	for i, c := range r.Components {
		if c.ID == "pi" {
			for _, prior := range old.Preparation.Components {
				if prior.ID == "pi" {
					r.Components[i] = prior
				}
			}
		}
	}
	r.PiRuntime = old.Preparation.PiRuntime
	next := nativeReceipt{1, "linux-host-native-v1", m, r, true, false}
	data, _ := json.Marshal(next)
	if err := a.writeNew("etc/awf/install-next.json", data, 0600); err != nil {
		return err
	}
	if err := a.root.Rename("etc/awf/install-next.json", "etc/awf/install.json"); err != nil {
		return err
	}
	return syncDirectory(filepath.Join(a.root.Name(), "etc/awf"))
}
