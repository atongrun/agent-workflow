//go:build linux

package hostinstall

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

// Opt-in, non-root execution of the pinned Node binary. Only the JavaScript UID
// query is simulated; this test cannot establish real root/service separation.
func TestPiLauncherUpdateUmaskOfflineFixture(t *testing.T) {
	node := launcherFixtureNode(t)
	for _, tc := range []struct {
		name            string
		uid, mask, want int
		args            []string
	}{
		{"root-update-0002", 0, 0002, 0022, []string{"update"}},
		{"root-update-0077", 0, 0077, 0022, []string{"update", "--force"}},
		{"root-version", 0, 0002, 0002, []string{"--version"}},
		{"root-rpc", 0, 0077, 0077, []string{"--mode", "rpc"}},
		{"root-prompt-containing-update", 0, 0002, 0002, []string{"-p", "update"}},
		{"root-other-command", 0, 0002, 0002, []string{"list", "update"}},
		{"root-no-command", 0, 0077, 0077, []string{}},
		{"root-command-case", 0, 0002, 0002, []string{"Update"}},
		{"user-update-0002", 1000, 0002, 0002, []string{"update"}},
		{"user-update-0077", 1000, 0077, 0077, []string{"update"}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			work := privateParent(t)
			launcher := filepath.Join(work, "opt/pi-cli/awf-launcher.mjs")
			cli := filepath.Join(work, "opt/pi-cli/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js")
			for _, name := range []string{filepath.Dir(cli), filepath.Join(work, "opt/node/bin")} {
				if err := os.MkdirAll(name, 0755); err != nil {
					t.Fatal(err)
				}
			}
			if err := os.Symlink(node, filepath.Join(work, "opt/node/bin/node")); err != nil {
				t.Fatal(err)
			}
			writeLauncherFixture(t, launcher, sharedPiLauncher)
			writeLauncherFixture(t, cli, launcherUmaskCLI)
			writeLauncherFixture(t, filepath.Join(filepath.Dir(cli), "package.json"), `{"type":"module"}`)
			guard := filepath.Join(work, "uid.mjs")
			writeLauncherFixture(t, guard, `process.getuid=()=>Number(process.env.AWF_FIXTURE_UID);`)
			outDir := filepath.Join(work, "created")
			result := runLauncherParent(t, node, work, launcher, guard, tc.uid, tc.mask, tc.args, []string{"AWF_FIXTURE_OUTPUT=" + outDir})
			var got struct {
				PID, Mask, ChildMask int
				Args                 []string
			}
			if err := json.Unmarshal([]byte(result.Stdout), &got); err != nil {
				t.Fatal(err, result.Stdout)
			}
			if got.PID != result.PID || got.Mask != tc.want || got.ChildMask != tc.want || !reflect.DeepEqual(got.Args, tc.args) {
				t.Fatalf("execve PID/argv or inherited umask changed: %+v, parent %+v", got, result)
			}
			for name, mode := range map[string]os.FileMode{".": 0777, "file": 0666, "executable": 0777, "child-file": 0666} {
				info, err := os.Stat(filepath.Join(outDir, name))
				want := mode &^ os.FileMode(tc.want)
				if err != nil || info.Mode().Perm() != want {
					t.Fatalf("%s: expected mode %04o, got %v (%v)", name, want, info, err)
				}
			}
		})
	}
}

func launcherFixtureNode(t *testing.T) string {
	t.Helper()
	dir := os.Getenv("AWF_PI_INSTALLED_FIXTURE_DIR")
	if dir == "" {
		t.Skip("explicit verified installed fixture required")
	}
	if os.Getuid() == 0 {
		t.Skip("non-root local fixture only")
	}
	if err := validateSandbox(dir); err != nil {
		t.Fatal(err)
	}
	node := filepath.Join(dir, "node-v22.19.0-linux-x64/bin/node")
	if err := verifyAuditedNode(node); err != nil {
		t.Fatal("pinned Node fixture mismatch", err)
	}
	return node
}

// Executes the real official Pi CLI and its npm updater, with only the latest
// release response fixed to cached 1.0.4. No actual root, network or services.
func TestPiLauncherOfficialUpdateOfflineFixture(t *testing.T) {
	node := launcherFixtureNode(t)
	cache := os.Getenv("AWF_PI_UPDATE_NPM_CACHE_DIR")
	if cache == "" {
		t.Skip("explicit verified 1.0.4 npm cache required")
	}
	if err := validateSandbox(cache); err != nil {
		t.Fatal(err)
	}
	work := privateParent(t)
	prefix := filepath.Join(work, "opt/pi-cli")
	if err := os.MkdirAll(filepath.Join(prefix, "lib"), 0755); err != nil {
		t.Fatal(err)
	}
	// These are new fixture files, given the initial installer's safe modes. No
	// existing installation or dependency fixture is chmodded or overwritten.
	copyLauncherFixtureTree(t, filepath.Join(os.Getenv("AWF_PI_INSTALLED_FIXTURE_DIR"), "pi-release/node_modules"), filepath.Join(prefix, "lib/node_modules"))
	copyLauncherFixtureTree(t, filepath.Dir(filepath.Dir(node)), filepath.Join(work, "opt/node"))
	node = filepath.Join(work, "opt/node/bin/node")
	if err := os.Mkdir(filepath.Join(prefix, "bin"), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("../lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js", filepath.Join(prefix, "bin/pi")); err != nil {
		t.Fatal(err)
	}
	launcher := filepath.Join(prefix, "awf-launcher.mjs")
	writeLauncherFixture(t, launcher, sharedPiLauncher)
	if err := os.Chmod(launcher, 0755); err != nil {
		t.Fatal(err)
	}
	writeLauncherFixture(t, filepath.Join(work, "user.npmrc"), "")
	writeLauncherFixture(t, filepath.Join(work, "global.npmrc"), "")
	guard := filepath.Join(work, "guard.mjs")
	writeLauncherFixture(t, guard, piOfflineGuard+launcherOfficialUpdateGuard)
	info, err := os.Stat(prefix)
	if err != nil {
		t.Fatal(err)
	}
	pkg := filepath.Join(prefix, "lib/node_modules/@earendil-works/pi-coding-agent/package.json")
	checkVersion := func(want string) {
		t.Helper()
		b, err := os.ReadFile(pkg)
		var p struct{ Name, Version string }
		if err != nil || json.Unmarshal(b, &p) != nil || p.Name != "@earendil-works/pi-coding-agent" || p.Version != want {
			t.Fatal("official Pi version mismatch", want, err)
		}
	}
	checkVersion("1.0.2")
	result := runLauncherParent(t, node, work, launcher, guard, 0, 0002, []string{"update"}, []string{
		"npm_config_offline=true", "npm_config_cache=" + cache, "npm_config_ignore_scripts=true", "npm_config_audit=false", "npm_config_fund=false",
		"npm_config_userconfig=" + filepath.Join(work, "user.npmrc"), "npm_config_globalconfig=" + filepath.Join(work, "global.npmrc"),
	})
	if !strings.Contains(result.Stdout, "Updated pi from 1.0.2 to 1.0.4") || !strings.Contains(result.Stdout, "--ignore-scripts") || !strings.Contains(result.Stdout, "--prefix "+prefix) || strings.Contains(result.Stderr, "awf_network_denied") || !strings.Contains(result.Stderr, `"blockedNetworkCalls":0`) || !strings.Contains(result.Stderr, `"type":"awf_fixture_latest"`) {
		t.Fatal("official update/guard evidence missing", result.Stdout, result.Stderr)
	}
	checkVersion("1.0.4")
	after, err := os.Stat(prefix)
	if err != nil || !os.SameFile(info, after) {
		t.Fatal("sole prefix inode replaced", err)
	}
	b, err := os.ReadFile(launcher)
	if err != nil || string(b) != sharedPiLauncher {
		t.Fatal("stable launcher changed", err)
	}
	root, err := os.OpenRoot(work)
	if err != nil {
		t.Fatal(err)
	}
	defer root.Close()
	inspector := nativeAdapter{root: root, owner: os.Getuid()}
	var entries int
	if err := filepath.WalkDir(prefix, func(name string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		info, err := entry.Info()
		if err != nil {
			return err
		}
		entries++
		if info.Mode()&os.ModeSymlink == 0 {
			rel, err := filepath.Rel(work, name)
			if err != nil {
				return err
			}
			if err := inspector.trusted(rel, entry.IsDir()); err != nil {
				return fmt.Errorf("updated fixture prefix %s mode %04o: %w", rel, info.Mode().Perm(), err)
			}
		}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	for name, want := range map[string]os.FileMode{pkg: 0644, filepath.Dir(pkg): 0755, launcher: 0755} {
		info, err := os.Stat(name)
		if err != nil || info.Mode().Perm() != want {
			t.Fatalf("%s: wanted %04o, got %v (%v)", name, want, info, err)
		}
	}
	checkPiOfflineVersion(t, work, node, launcher, "1.0.4")
	t.Logf("Official Pi 1.0.2 -> 1.0.4, %d prefix entries, parent 0002 preserved; npm offline/ignore-scripts, simulated JS root only", entries)
}

func copyLauncherFixtureTree(t *testing.T, source, destination string) {
	t.Helper()
	if err := filepath.WalkDir(source, func(name string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(source, name)
		if err != nil {
			return err
		}
		out := filepath.Join(destination, rel)
		if entry.IsDir() {
			return os.Mkdir(out, 0755)
		}
		info, err := entry.Info()
		if err != nil {
			return err
		}
		if info.Mode()&os.ModeSymlink != 0 {
			target, err := os.Readlink(name)
			if err != nil {
				return err
			}
			return os.Symlink(target, out)
		}
		in, err := os.Open(name)
		if err != nil {
			return err
		}
		defer in.Close()
		mode := os.FileMode(0644)
		if info.Mode().Perm()&0111 != 0 {
			mode = 0755
		}
		file, err := os.OpenFile(out, os.O_CREATE|os.O_EXCL|os.O_WRONLY, mode)
		if err != nil {
			return err
		}
		_, err = io.Copy(file, in)
		closeErr := file.Close()
		if err != nil {
			return err
		}
		return closeErr
	}); err != nil {
		t.Fatal(err)
	}
}

func writeLauncherFixture(t *testing.T, name, contents string) {
	t.Helper()
	if err := os.WriteFile(name, []byte(contents), 0600); err != nil {
		t.Fatal(err)
	}
}

type launcherParentResult struct {
	Before, After, PID, Status int
	Stdout, Stderr             string
}

func runLauncherParent(t *testing.T, node, work, launcher, guard string, uid, mask int, args, extraEnv []string) launcherParentResult {
	t.Helper()
	parent := filepath.Join(work, "parent.mjs")
	writeLauncherFixture(t, parent, launcherUmaskParent)
	plan, err := json.Marshal(struct {
		Launcher, Guard string
		UID, Mask       int
		Args            []string
	}{launcher, guard, uid, mask, args})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, node, parent, string(plan))
	cmd.Dir = work
	cmd.Env = append([]string{"PATH=" + filepath.Dir(node) + ":/usr/bin:/bin", "HOME=" + filepath.Join(work, "home")}, extraEnv...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatal("launcher fixture parent", err, string(out))
	}
	var result launcherParentResult
	if err := json.Unmarshal(out, &result); err != nil {
		t.Fatal(err, string(out))
	}
	if result.Status != 0 || result.Before != mask || result.After != mask {
		t.Fatalf("child status or parent umask changed: %+v", result)
	}
	return result
}

const launcherUmaskParent = `import {spawnSync} from "node:child_process";
const plan=JSON.parse(process.argv[2]);
process.umask(plan.Mask);
const before=process.umask();
const child=spawnSync(process.execPath,[plan.Launcher,...plan.Args],{
 encoding:"utf8",env:{...process.env,NODE_OPTIONS:"--import="+plan.Guard,AWF_FIXTURE_UID:String(plan.UID)}
});
if(child.error)throw child.error;
console.log(JSON.stringify({before,after:process.umask(),pid:child.pid,status:child.status,stdout:child.stdout,stderr:child.stderr}));
`

const launcherUmaskCLI = `import fs from "node:fs";
import path from "node:path";
import {spawnSync} from "node:child_process";
const root=process.env.AWF_FIXTURE_OUTPUT;
fs.mkdirSync(root);
fs.writeFileSync(path.join(root,"file"),"fixture");
fs.writeFileSync(path.join(root,"executable"),"fixture",{mode:0o777});
const child=spawnSync(process.execPath,["--input-type=module","--eval",
 'import fs from "node:fs";fs.writeFileSync(process.argv[1],"fixture");console.log(process.umask());',
 path.join(root,"child-file")],{encoding:"utf8"});
if(child.error||child.status!==0)throw child.error||new Error(child.stderr);
console.log(JSON.stringify({pid:process.pid,mask:process.umask(),childMask:Number(child.stdout),args:process.argv.slice(2)}));
`

const launcherOfficialUpdateGuard = `process.getuid=()=>Number(process.env.AWF_FIXTURE_UID);
const fixtureFetch=async(url)=>{
 if(String(url)!=="https://pi.dev/api/latest-version")return deny();
 process.stderr.write(JSON.stringify({type:"awf_fixture_latest",version:"1.0.4"})+"\n");
 return new Response(JSON.stringify({version:"1.0.4",packageName:"@earendil-works/pi-coding-agent"}),{status:200,headers:{"Content-Type":"application/json"}});
};
// Pi installs Undici globals during startup. Retain this transport fixture;
// every real socket remains denied by the preceding offline guard.
Object.defineProperty(globalThis,"fetch",{get:()=>fixtureFetch,set:()=>{}});
`
