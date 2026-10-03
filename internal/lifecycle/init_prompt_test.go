package lifecycle

import (
	"bytes"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func assertInitDidNotSave(t *testing.T, root string) {
	t.Helper()
	if _, err := os.Stat(root); !os.IsNotExist(err) {
		t.Fatalf("incomplete init changed installation: %v", err)
	}
}

func TestInitWithoutFlagsReviewsAndSavesChosenValues(t *testing.T) {
	for _, remote := range []bool{false, true} {
		name := "loopback defaults"
		if remote {
			name = "explicit remote values"
		}
		t.Run(name, func(t *testing.T) {
			root, c, _ := lifecycleConfigFixture(t)
			t.Setenv("PATH", t.TempDir())
			project, listen, sources := "", "", ""
			if remote {
				project, listen, sources = "chosen-project", "192.0.2.10:7071", "198.51.100.20,2001:db8::20"
			}
			answers := strings.Join([]string{project, c.Node.Projects["acceptance"], c.OpenCodeBinary, listen, sources, "", "yes", ""}, "\n") + "\n"
			var out bytes.Buffer
			if err := initialize(root, nil, strings.NewReader(answers), &out); err != nil {
				t.Fatal(err)
			}
			got, err := loadConfig(root)
			if err != nil {
				t.Fatal(err)
			}
			if remote {
				c.Node.Projects = map[string]string{project: c.Node.Projects["acceptance"]}
				c.Node.ListenAddress = listen
				c.Node.AllowedSourceIPs = strings.Split(sources, ",")
			}
			if !reflect.DeepEqual(got, c) {
				t.Fatalf("saved configuration differs from reviewed answers:\ngot %#v\nwant %#v", got, c)
			}
			last := -1
			for _, prompt := range []string{
				"Project ID shared with the control Host [acceptance]",
				"Existing dedicated workspace (absolute path) (required)",
				"Native OpenCode .exe (absolute path) (required)",
				"Exact node listen IP:port [127.0.0.1:7071]",
				"Exact control Host source IPs (comma-separated; blank permits loopback only)",
				"Start AWF automatically when you sign in as this Windows user? [y/N]",
				"Save this exact configuration? [y/N]",
				"Pair this node with an existing control Host now? [y/N]",
				"Pairing skipped",
			} {
				next := strings.Index(out.String(), prompt)
				if next < 0 || next <= last {
					t.Fatalf("missing or out-of-order prompt %q: %s", prompt, out.String())
				}
				last = next
			}
			if _, err := os.Stat(c.CredentialFile); !os.IsNotExist(err) {
				t.Fatalf("default-off pairing created a credential: %v", err)
			}
		})
	}
}

func TestInitOffersDetectedNativeOpenCodeAsExplicitDefault(t *testing.T) {
	root, c, _ := lifecycleConfigFixture(t)
	dir := t.TempDir()
	binary := filepath.Join(dir, "opencode.exe")
	if err := os.WriteFile(binary, []byte("MZ inert fixture, never executed"), 0700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir)
	var out bytes.Buffer
	answers := strings.Join([]string{"", c.Node.Projects["acceptance"], "", "", "", "n", "y", "n"}, "\n") + "\n"
	if err := initialize(root, nil, strings.NewReader(answers), &out); err != nil {
		t.Fatal(err)
	}
	got, err := loadConfig(root)
	if err != nil || got.OpenCodeBinary != binary {
		t.Fatalf("detected path = %q, error = %v", got.OpenCodeBinary, err)
	}
	if !strings.Contains(out.String(), "Native OpenCode .exe (absolute path) ["+binary+"]: ") {
		t.Fatalf("detected path was not offered for acceptance: %s", out.String())
	}
}

func TestNativeOpenCodeDetectionRejectsWrappersAndDirectories(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("PATH", dir)
	for _, name := range []string{"opencode", "opencode.cmd", "opencode.ps1"} {
		if err := os.WriteFile(filepath.Join(dir, name), []byte("inert wrapper fixture, never executed"), 0700); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.Mkdir(filepath.Join(dir, "opencode.exe"), 0700); err != nil {
		t.Fatal(err)
	}
	if got := detectedNativeOpenCode(); got != "" {
		t.Fatalf("detected a non-native executable: %q", got)
	}
}

func TestInitMissingRequiredAnswersDoNotUseWorkingDirectory(t *testing.T) {
	for _, field := range []string{"workspace", "opencode"} {
		t.Run(field, func(t *testing.T) {
			root, c, _ := lifecycleConfigFixture(t)
			t.Setenv("PATH", t.TempDir())
			answers := "\n\n"
			if field == "opencode" {
				answers = "\n" + c.Node.Projects["acceptance"] + "\n\n"
			}
			var out bytes.Buffer
			err := initialize(root, nil, strings.NewReader(answers), &out)
			if err == nil || !strings.Contains(err.Error(), "is required") || !strings.Contains(out.String(), "(required)") {
				t.Fatalf("missing required field was not explained: %v; %s", err, out.String())
			}
			assertInitDidNotSave(t, root)
		})
	}
}

func TestInitPromptEOFBeforeSaveDoesNotChangeInstallation(t *testing.T) {
	for stage := 0; stage < 7; stage++ {
		for _, partial := range []bool{false, true} {
			root, c, _ := lifecycleConfigFixture(t)
			t.Setenv("PATH", t.TempDir())
			answers := []string{"acceptance", c.Node.Projects["acceptance"], c.OpenCodeBinary, "127.0.0.1:7071", "", "no", "yes"}
			input := ""
			for _, answer := range answers[:stage] {
				input += answer + "\n"
			}
			if partial {
				input += answers[stage]
			}
			var out bytes.Buffer
			if err := initialize(root, nil, strings.NewReader(input), &out); err == nil {
				t.Fatalf("accepted EOF at stage %d (partial answer %t)", stage, partial)
			}
			assertInitDidNotSave(t, root)
		}
	}
}

func TestInitPartialFlagsPromptOnlyForMissingValues(t *testing.T) {
	root, c, _ := lifecycleConfigFixture(t)
	t.Setenv("PATH", t.TempDir())
	args := []string{"--project", "explicit-project", "--workspace", c.Node.Projects["acceptance"], "--listen", "192.0.2.10:7071", "--allow-source", "198.51.100.20"}
	var out bytes.Buffer
	if err := initialize(root, args, strings.NewReader(c.OpenCodeBinary+"\nn\ny\nn\n"), &out); err != nil {
		t.Fatal(err)
	}
	got, err := loadConfig(root)
	if err != nil {
		t.Fatal(err)
	}
	if got.OpenCodeBinary != c.OpenCodeBinary || got.Node.Projects["explicit-project"] != c.Node.Projects["acceptance"] || got.Node.ListenAddress != "192.0.2.10:7071" || !reflect.DeepEqual(got.Node.AllowedSourceIPs, []string{"198.51.100.20"}) {
		t.Fatalf("explicit values changed: %#v", got)
	}
	for _, unwanted := range []string{"Project ID shared", "Existing dedicated workspace", "Exact node listen", "Exact control Host source"} {
		if strings.Contains(out.String(), unwanted) {
			t.Fatalf("explicit flag was prompted again: %q", unwanted)
		}
	}
}

func TestInitInvalidExplicitFlagsAreNotReplaced(t *testing.T) {
	for _, field := range []string{"project", "workspace", "opencode", "listen", "allow-source", "credential-file"} {
		t.Run(field, func(t *testing.T) {
			root, c, _ := lifecycleConfigFixture(t)
			t.Setenv("PATH", t.TempDir())
			values := map[string]string{"project": "acceptance", "workspace": c.Node.Projects["acceptance"], "opencode": c.OpenCodeBinary, "listen": "127.0.0.1:7071", "allow-source": "", "credential-file": c.CredentialFile}
			values[field] = ""
			if field == "allow-source" {
				values[field] = "192.0.2.0/24"
			}
			missing := "workspace"
			answer := c.Node.Projects["acceptance"]
			if field == "workspace" {
				missing, answer = "opencode", c.OpenCodeBinary
			}
			args := []string{}
			for _, name := range []string{"project", "workspace", "opencode", "listen", "allow-source", "credential-file"} {
				if name != missing {
					args = append(args, "--"+name, values[name])
				}
			}
			var out bytes.Buffer
			if err := initialize(root, args, strings.NewReader(answer+"\nn\ny\nn\n"), &out); err == nil {
				t.Fatalf("invalid explicit --%s was accepted or replaced", field)
			}
			if strings.Contains(out.String(), "Save this exact configuration?") {
				t.Fatal("invalid configuration reached save review")
			}
			assertInitDidNotSave(t, root)
		})
	}
}

func TestInitPromptRetainsListenerAndSourceValidation(t *testing.T) {
	for _, tc := range []struct{ listen, sources string }{
		{"192.0.2.10:7071", ""},
		{"0.0.0.0:7071", "192.0.2.20"},
		{"[::]:7071", "192.0.2.20"},
		{"localhost:7071", ""},
		{"127.0.0.1:0", ""},
		{"192.0.2.10:7071", "192.0.2.0/24"},
		{"192.0.2.10:7071", "control.example"},
		{"192.0.2.10:7071", "0.0.0.0"},
	} {
		root, c, _ := lifecycleConfigFixture(t)
		t.Setenv("PATH", t.TempDir())
		answers := strings.Join([]string{"acceptance", c.Node.Projects["acceptance"], c.OpenCodeBinary, tc.listen, tc.sources, "n", "y", "n"}, "\n") + "\n"
		var out bytes.Buffer
		if err := initialize(root, nil, strings.NewReader(answers), &out); err == nil {
			t.Fatalf("accepted unsafe listener/source answers: %+v", tc)
		}
		assertInitDidNotSave(t, root)
	}
}

func TestInitPromptAndOptionalPairingShareInputReader(t *testing.T) {
	root, c, _ := lifecycleConfigFixture(t)
	t.Setenv("PATH", t.TempDir())
	// The invalid SSH alias fails target validation before any native operation.
	answers := strings.Join([]string{"", c.Node.Projects["acceptance"], c.OpenCodeBinary, "", "", "n", "yes", "yes", "-unsafe-host", "/private/node.env"}, "\n") + "\n"
	var out bytes.Buffer
	err := initialize(root, nil, strings.NewReader(answers), &out)
	if err == nil || !strings.Contains(err.Error(), "SSH host must be a preconfigured alias") {
		t.Fatalf("pairing did not receive the buffered answers: %v; %s", err, out.String())
	}
	if _, err := loadConfig(root); err != nil {
		t.Fatalf("optional pairing failure lost saved configuration: %v", err)
	}
	if _, err := os.Stat(c.CredentialFile); !os.IsNotExist(err) {
		t.Fatalf("invalid pairing created a credential: %v", err)
	}
}

func TestInitWithoutFlagsPreservesExistingIdentity(t *testing.T) {
	root, c, _ := lifecycleConfigFixture(t)
	t.Setenv("PATH", t.TempDir())
	if err := privateRoot(root); err != nil {
		t.Fatal(err)
	}
	if _, err := managedDirectory(root, "credentials", "windows-node"); err != nil {
		t.Fatal(err)
	}
	identity := []byte("inert existing encrypted identity")
	mustWriteFixture(t, c.CredentialFile, identity)
	answers := strings.Join([]string{"", c.Node.Projects["acceptance"], c.OpenCodeBinary, "", "", "n", "yes", "yes"}, "\n") + "\n"
	var out bytes.Buffer
	if err := initialize(root, nil, strings.NewReader(answers), &out); err != nil {
		t.Fatal(err)
	}
	got, err := os.ReadFile(c.CredentialFile)
	if err != nil || !bytes.Equal(got, identity) || strings.Contains(out.String(), "Pair this node") || !strings.Contains(out.String(), "Existing local credential preserved") {
		t.Fatalf("existing identity was not preserved: %v; %s", err, out.String())
	}
	out.Reset()
	if err := initialize(root, nil, strings.NewReader(answers), &out); err == nil || !strings.Contains(err.Error(), "already initialized") || out.Len() != 0 {
		t.Fatalf("repeat init reached prompts: %v; %s", err, out.String())
	}
}
