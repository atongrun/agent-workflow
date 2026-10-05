//go:build linux

package hostinstall

import (
	"context"
	"errors"
	"io"
	"io/fs"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"time"
)

// Public version-specific metadata observed and hash-verified in this task.
// A changed registry response stops preparation; the official lock is unchanged.
var supplementalPins = map[string]string{
	"chord":           "a76a223dcacec39e355fad3379cfa0934b33e01e0793c872688b4efcd13ee6d7",
	"pi-agent-core":   "35ad4f19cc45dadf145d4e3a7b3eac16c776942d2c0cc2553537722d9c611351",
	"pi-ai":           "01ebb484824edd2b55fca135f257aa3d3f19641de5ebb3ef559bf7fa8bedb325",
	"pi-codemode":     "63cc07f5f80d145d33261298a3c6d71eb4e86e7826418a3f7d31b0b02ddb357e",
	"pi-coding-agent": "e437f25be74fe5fce0decd7f07b263e4f69423e8749e8a59cafb92d8dfd96522",
	"pi-mcp":          "cac67d9c278bc8ce62406595851d8432fd788b042ca55a25a658744bee09b2a9",
	"pi-telemetry":    "003bb8f6c73cc6ad1dec3ba19017e1119bfe302e1fd13ec424d24954720b55f6",
	"pi-tui":          "de2a1318e8c211106a64b87bb5f952044cc468647472af8b4cfcadc5900adbcd",
}

func prepareNativeRuntime(ctx context.Context, m Manifest, o Observer) (string, InstallReceipt, func(), error) {
	var r InstallReceipt
	work, err := os.MkdirTemp("/tmp", "awf-linux-install-")
	if err != nil {
		return "", r, func() {}, err
	}
	cleanup := func() { os.RemoveAll(work) }
	fail := func(err error) (string, InstallReceipt, func(), error) { cleanup(); return "", r, func() {}, err }
	if !auditedRuntimeManifest(m) {
		return fail(errors.New("native preparation requires audited Node/Pi bytes"))
	}
	stage, err := Stage(ctx, m, work, nil, o)
	if err != nil {
		return fail(err)
	}
	bootstrap := filepath.Join(work, "npm-bootstrap")
	if err := os.Mkdir(bootstrap, 0700); err != nil {
		return fail(err)
	}
	root, err := os.OpenRoot(bootstrap)
	if err != nil {
		return fail(err)
	}
	var nodeComponent Component
	for _, c := range m.Components {
		if c.ID == "node" {
			nodeComponent = c
		}
	}
	_, err = extractNodeArchive(ctx, m, nodeComponent, filepath.Join(stage, "node", nodeComponent.Artifacts[0].Name), root, &extractionBudget{}, o, true)
	root.Close()
	if err != nil {
		return fail(err)
	}
	in := RuntimeInput{CacheDirectory: filepath.Join(work, "cache")}
	if err := os.Mkdir(in.CacheDirectory, 0700); err != nil {
		return fail(err)
	}
	client := &http.Client{Timeout: 30 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	o.Event(ProgressEvent{Component: "pi", Stage: "supplemental-metadata", State: "started"})
	for name, digest := range supplementalPins {
		req, _ := http.NewRequestWithContext(ctx, http.MethodGet, "https://registry.npmjs.org/@earendil-works/"+name+"/1.0.2", nil)
		res, err := client.Do(req)
		if err != nil {
			o.Event(ProgressEvent{Component: "pi", Stage: "supplemental-metadata", State: "failed"})
			return fail(errors.New("official supplementary metadata unavailable"))
		}
		b, err := io.ReadAll(io.LimitReader(res.Body, (4<<20)+1))
		res.Body.Close()
		if err != nil || res.StatusCode != 200 || !pinHash(b, digest) {
			o.Event(ProgressEvent{Component: "pi", Stage: "supplemental-metadata", State: "failed"})
			return fail(errors.New("official supplementary metadata changed or unavailable"))
		}
		in.Supplemental = append(in.Supplemental, RegistryMetadata{Data: b, SHA256: digest})
	}
	o.Event(ProgressEvent{Component: "pi", Stage: "supplemental-metadata", State: "completed"})
	if err := populateNativeCache(ctx, bootstrap, stage, in.CacheDirectory, o); err != nil {
		return fail(err)
	}
	sandbox := filepath.Join(work, "runtime")
	if err := os.Mkdir(sandbox, 0700); err != nil {
		return fail(err)
	}
	r, err = ApplyRuntimeFixture(ctx, m, stage, sandbox, o, in)
	if err != nil {
		return fail(err)
	}
	generation := "layout-2-" + manifestDigest(m) + "-" + runtimeInputDigest(in)
	return filepath.Join(sandbox, "releases", generation), r, cleanup, nil
}

func populateNativeCache(ctx context.Context, bootstrap, stage, cache string, o Observer) error {
	install := filepath.Join(bootstrap, "pi-cache-install")
	if err := os.Mkdir(install, 0700); err != nil {
		return err
	}
	for _, name := range []string{"package.json", "package-lock.json"} {
		b, err := os.ReadFile(filepath.Join(stage, "pi", name))
		if err != nil {
			return err
		}
		if err := os.WriteFile(filepath.Join(install, name), b, 0600); err != nil {
			return err
		}
	}
	for _, name := range []string{"user.npmrc", "global.npmrc"} {
		if err := os.WriteFile(filepath.Join(bootstrap, name), nil, 0600); err != nil {
			return err
		}
	}
	node := filepath.Join(bootstrap, "opt/node/bin/node")
	if err := verifyAuditedNode(node); err != nil {
		return errors.New("audited Node executable required for dependency download")
	}
	ctx, cancel := context.WithTimeout(ctx, 5*time.Minute)
	defer cancel()
	cmd := exec.CommandContext(ctx, node, filepath.Join(bootstrap, "opt/node/lib/node_modules/npm/bin/npm-cli.js"), "ci", "--ignore-scripts", "--min-release-age=0", "--omit=dev", "--include=optional", "--no-fund", "--no-audit", "--loglevel=error", "--progress=false")
	cmd.Dir = install
	cmd.Env = []string{"PATH=" + filepath.Dir(node) + ":/usr/bin:/bin", "NODE_OPTIONS=--max-old-space-size=192", "npm_config_registry=https://registry.npmjs.org", "npm_config_cache=" + cache, "npm_config_userconfig=" + filepath.Join(bootstrap, "user.npmrc"), "npm_config_globalconfig=" + filepath.Join(bootstrap, "global.npmrc"), "npm_config_logs_dir=" + bootstrap, "npm_config_prefix=" + install, "npm_config_global=false", "npm_config_cafile=/etc/ssl/certs/ca-certificates.crt"}
	// Preserve only ordinary transport proxy settings, never npm options or auth.
	for _, name := range []string{"HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy"} {
		if v, ok := os.LookupEnv(name); ok {
			cmd.Env = append(cmd.Env, name+"="+v)
		}
	}
	configureRuntimeCommand(cmd)
	cmd.Stdout = io.Discard
	cmd.Stderr = io.Discard
	o.Event(ProgressEvent{Component: "pi", Stage: "npm-cache-download", State: "started"})
	if err := cmd.Start(); err != nil {
		o.Event(ProgressEvent{Component: "pi", Stage: "npm-cache-download", State: "failed"})
		return errors.New("official npm dependency download failed; no programs installed")
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()
	observe := func() {
		// Content files contain actual completed cache transfers. Their size is
		// an observation, not a verified bundle total or a synthetic percentage.
		if bytes, err := nativeCacheBytes(cache); err == nil {
			o.Event(ProgressEvent{Component: "pi", Stage: "npm-cache-download", State: "progress", Bytes: bytes})
		}
	}
	for {
		select {
		case err := <-done:
			observe()
			if err != nil {
				o.Event(ProgressEvent{Component: "pi", Stage: "npm-cache-download", State: "failed"})
				return errors.New("official npm dependency download failed; no programs installed")
			}
			o.Event(ProgressEvent{Component: "pi", Stage: "npm-cache-download", State: "completed"})
			return nil
		case <-ticker.C:
			observe()
		}
	}
}

func nativeCacheBytes(cache string) (int64, error) {
	var total int64
	err := filepath.WalkDir(filepath.Join(cache, "_cacache/content-v2"), func(name string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.Type().IsRegular() {
			info, err := entry.Info()
			if err != nil {
				return err
			}
			total += info.Size()
		}
		return nil
	})
	return total, err
}
