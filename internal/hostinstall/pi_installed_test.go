package hostinstall

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"
	"time"
)

// Opt-in development acceptance only. The fixture was installed from the exact
// official lock with scripts disabled and all selected tarballs checked. This
// never installs dependencies, discovers credentials, sends prompts or enables a
// service. Default test runs execute no downloaded program.
func TestPiInstalledOfflineFixture(t *testing.T) {
	dir := os.Getenv("AWF_PI_INSTALLED_FIXTURE_DIR")
	if dir == "" {
		t.Skip("explicit verified installed /tmp dependency fixture required")
	}
	if runtime.GOOS != "linux" || runtime.GOARCH != "amd64" {
		t.Fatal("this acceptance fixture is Linux amd64 only")
	}
	if err := validateSandbox(dir); err != nil {
		t.Fatal(err)
	}
	node := filepath.Join(dir, "node-v22.19.0-linux-x64/bin/node")
	checkHash := func(path, expected string) {
		t.Helper()
		data, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		sum := sha256.Sum256(data)
		if hex.EncodeToString(sum[:]) != expected {
			t.Fatal("fixed official input mismatch", path)
		}
	}
	checkHash(node, "596b5144ff242737f1c1be6a5f0ccb3907dbba2482344143cb1a6898633402a9")
	checkHash(filepath.Join(dir, "pi-release/package-lock.json"), "b8e9e6a191bcf1e6e3ff8dafe5c0c9042b48e0087cd6d6816dcaa051222ba680")
	checkPiOffline(t, dir, node, filepath.Join(dir, "pi-release/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js"))
}

func checkPiOffline(t *testing.T, dir, node, cli string, preparedExtension ...string) {
	t.Helper()
	work, err := os.MkdirTemp(dir, "offline-check-")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(work)
	agent := filepath.Join(work, "agent")
	if err := os.Mkdir(agent, 0700); err != nil {
		t.Fatal(err)
	}
	guard := filepath.Join(work, "guard.mjs")
	if err := os.WriteFile(guard, []byte(piOfflineGuard), 0600); err != nil {
		t.Fatal(err)
	}
	extension, err := os.ReadFile(filepath.Join("..", "..", "extensions", "awf.ts"))
	if err != nil {
		t.Fatal(err)
	}
	extPath, probe := filepath.Join(work, "awf.ts"), filepath.Join(work, "probe.ts")
	if len(preparedExtension) == 1 {
		extPath = preparedExtension[0]
	} else if err := os.WriteFile(extPath, extension, 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(probe, []byte(piRegistrationProbe), 0600); err != nil {
		t.Fatal(err)
	}
	env := []string{"PATH=" + filepath.Dir(node) + ":/usr/bin:/bin", "PI_CODING_AGENT_DIR=" + agent, "NODE_OPTIONS=--import=" + guard, "XDG_CONFIG_HOME=" + filepath.Join(work, "xdg-config"), "XDG_CACHE_HOME=" + filepath.Join(work, "xdg-cache"),
		"PI_INSTALLER_API_BASE=http://127.0.0.1:1/forbidden", "AWF_HOST_URL=http://127.0.0.1:0", "AWF_EXTENSION_TOKEN=offline-registration-fixture-not-an-issued-credential", "AWF_TASK_ID=dependency-fixture", "AWF_ROLE=architect", "AWF_LIFECYCLE_REVISION=0"}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	version := exec.CommandContext(ctx, node, cli, "--version")
	version.Env = env
	version.Dir = work
	var versionStderr bytes.Buffer
	version.Stderr = &versionStderr
	if out, err := version.Output(); err != nil || strings.TrimSpace(string(out)) != "1.0.2" {
		t.Fatal("Pi version", string(out), err)
	}
	if strings.Contains(versionStderr.String(), "awf_network_denied") || !strings.Contains(versionStderr.String(), `"blockedNetworkCalls":0`) {
		t.Fatal("version guarded network check", versionStderr.String())
	}
	cmd := exec.CommandContext(ctx, node, cli, "--mode", "rpc", "--no-session", "--no-extensions", "--extension", extPath, "--extension", probe, "--no-skills", "--no-prompt-templates", "--no-builtin-tools")
	cmd.Env = env
	cmd.Dir = work
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	stdin, err := cmd.StdinPipe()
	if err != nil {
		t.Fatal(err)
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	defer func() {
		if cmd.ProcessState == nil {
			cmd.Process.Kill()
			cmd.Wait()
		}
	}()
	if _, err := stdin.Write([]byte("{\"type\":\"get_state\",\"id\":\"offline-state\"}\n")); err != nil {
		t.Fatal(err)
	}
	var response struct {
		Type    string `json:"type"`
		ID      string `json:"id"`
		Success bool   `json:"success"`
		Data    struct {
			IsStreaming  bool `json:"isStreaming"`
			MessageCount int  `json:"messageCount"`
		} `json:"data"`
	}
	if err := json.NewDecoder(stdout).Decode(&response); err != nil {
		t.Fatal("read-only state response", err)
	}
	stdin.Close()
	if err := cmd.Wait(); err != nil {
		t.Fatal("orderly stdin-EOF shutdown", err, stderr.String())
	}
	if response.Type != "response" || response.ID != "offline-state" || !response.Success || response.Data.IsStreaming || response.Data.MessageCount != 0 {
		t.Fatal("unexpected native state", response)
	}
	var registration struct {
		Type                string   `json:"type"`
		Tools               []string `json:"tools"`
		BlockedNetworkCalls int      `json:"blockedNetworkCalls"`
		PID                 int      `json:"pid"`
		ManagedRoot         string   `json:"managedRoot"`
		InstallerAPIBase    string   `json:"installerAPIBase"`
		ExecPath            string   `json:"execPath"`
		Path                string   `json:"path"`
	}
	finalNetworkProbe := false
	for _, line := range strings.Split(stderr.String(), "\n") {
		var value struct {
			Type string `json:"type"`
		}
		if json.Unmarshal([]byte(line), &value) == nil && value.Type == "awf_network_denied" {
			t.Fatal("guarded network attempt during fixture check")
		}
		if value.Type == "awf_network_final" {
			var final struct {
				BlockedNetworkCalls int `json:"blockedNetworkCalls"`
			}
			if json.Unmarshal([]byte(line), &final) != nil || final.BlockedNetworkCalls != 0 {
				t.Fatal("network attempt after registration")
			}
			finalNetworkProbe = true
		}
		if json.Unmarshal([]byte(line), &value) == nil && value.Type == "awf_dependency_probe" {
			if err := json.Unmarshal([]byte(line), &registration); err != nil {
				t.Fatal(err)
			}
		}
	}
	if strings.HasSuffix(cli, "/opt/pi-cli/bin/pi") && (registration.ManagedRoot != filepath.Dir(filepath.Dir(cli)) || registration.InstallerAPIBase != "" || registration.ExecPath != node || strings.Split(registration.Path, ":")[0] != filepath.Dir(node)) {
		t.Fatal("shared launcher contract", registration)
	}
	if registration.PID != cmd.Process.Pid {
		t.Fatal("launcher changed process identity", registration.PID, cmd.Process.Pid)
	}
	if !finalNetworkProbe || registration.Type != "awf_dependency_probe" || registration.BlockedNetworkCalls != 0 || !reflect.DeepEqual(registration.Tools, []string{"awf_execution", "awf_finish", "awf_plan", "awf_task"}) {
		t.Fatal("bundled extension registration", stderr.String())
	}
	// Pi creates empty auth/model stores even for an ephemeral RPC launch.
	// Empty stores are config placeholders, never issued provider credentials.
	for _, name := range []string{"auth.json", "models-store.json"} {
		data, err := os.ReadFile(filepath.Join(agent, name))
		if err != nil {
			t.Fatal(err)
		}
		var v map[string]json.RawMessage
		if json.Unmarshal(data, &v) != nil || len(v) != 0 {
			t.Fatal("unexpected nonempty isolated store", name)
		}
	}
}

const piOfflineGuard = `import http from "node:http";
import https from "node:https";
import net from "node:net";
import tls from "node:tls";
import {syncBuiltinESMExports} from "node:module";
globalThis.__awfBlockedNetworkCalls=0;
const deny=()=>{globalThis.__awfBlockedNetworkCalls++;process.stderr.write(JSON.stringify({type:"awf_network_denied"})+"\n");throw new Error("Offline dependency check forbids network");};
globalThis.fetch=deny;
http.request=http.get=https.request=https.get=net.connect=net.createConnection=tls.connect=deny;
net.Socket.prototype.connect=net.Server.prototype.listen=deny;
process.on("exit",()=>process.stderr.write(JSON.stringify({type:"awf_network_final",blockedNetworkCalls:globalThis.__awfBlockedNetworkCalls})+"\n"));
syncBuiltinESMExports();
`
const piRegistrationProbe = `export default function(pi) {
pi.on("session_start",()=>{process.stderr.write(JSON.stringify({type:"awf_dependency_probe",tools:pi.getAllTools().map(t=>t.name).filter(n=>n.startsWith("awf_")).sort(),blockedNetworkCalls:globalThis.__awfBlockedNetworkCalls,pid:process.pid,managedRoot:process.env.PI_MANAGED_INSTALL_ROOT||"",installerAPIBase:process.env.PI_INSTALLER_API_BASE||"",execPath:process.execPath,path:process.env.PATH})+"\n");});
}
`
