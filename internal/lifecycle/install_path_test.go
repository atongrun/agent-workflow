package lifecycle

import (
	"errors"
	"reflect"
	"strings"
	"testing"
)

const installPathTestBin = `C:\Users\Test\AppData\Local\AWF\bin`

func installPathTestLookup(name string) (string, bool) {
	values := map[string]string{
		"localappdata": `C:\Users\Test\AppData\Local`,
		"awf_bin":      installPathTestBin,
		"nested":       `%AWF_BIN%`,
		"empty":        "",
	}
	v, ok := values[strings.ToLower(name)]
	return v, ok
}

func TestMoveInstallPathFirstPreservesUnrelatedEntries(t *testing.T) {
	bin := installPathTestBin
	for _, tc := range []struct{ name, input, want string }{
		{"empty", "", bin},
		{"already-first", bin + `;C:\Tools`, bin + `;C:\Tools`},
		{"move", `C:\Tools;` + bin + `;D:\Other`, bin + `;C:\Tools;D:\Other`},
		{"all-duplicates", bin + ";" + strings.ToLower(bin) + `\;` + `"` + bin + `"`, bin},
		{"quoted-and-whitespace", `  "` + bin + `\"  ;  "D:\Other Tools"  `, bin + `;  "D:\Other Tools"  `},
		{"normalized-only-exact", `c:/users/Test/AppData/Local/AWF/./other/../bin/;` + bin + `-old;` + bin + `\child;C:\Tools;C:\Tools`, bin + ";" + bin + `-old;` + bin + `\child;C:\Tools;C:\Tools`},
		{"extended-prefix", `\\?\` + bin + `;C:\Tools`, bin + `;C:\Tools`},
		{"environment", `%LOCALAPPDATA%\AWF\bin;%awf_bin%;%MISSING%\bin;%NESTED%;%EMPTY%`, bin + `;%MISSING%\bin;%NESTED%;%EMPTY%`},
		{"empty-entries", `;` + bin + `;;C:\Tools;`, bin + `;;;C:\Tools;`},
		{"all-empty", ";", bin + ";;"},
		{"relative-invalid-retained", `.;AWF\bin;C:AWF\bin;"bad;C:\bad*\bin;C:\bad.\bin`, bin + `;.;AWF\bin;C:AWF\bin;"bad;C:\bad*\bin;C:\bad.\bin`},
		{"other-profile", `C:\Users\Other\AppData\Local\AWF\bin`, bin + `;C:\Users\Other\AppData\Local\AWF\bin`},
		{"unrelated-variable-text", `%USERPROFILE%\Tools;  d:/other/../Tools/  `, bin + `;%USERPROFILE%\Tools;  d:/other/../Tools/  `},
	} {
		t.Run(tc.name, func(t *testing.T) {
			got := moveInstallPathFirst(tc.input, bin, installPathTestLookup)
			if got != tc.want {
				t.Fatalf("got %q, want %q", got, tc.want)
			}
			if again := moveInstallPathFirst(got, bin, installPathTestLookup); again != got {
				t.Fatalf("not idempotent: first %q; second %q", got, again)
			}
		})
	}
}

func TestCanonicalInstallPathLexicalWindowsRules(t *testing.T) {
	for _, tc := range []struct{ input, want string }{
		{`C:/Users/Test/AWF/./other/../bin//`, `C:\Users\Test\AWF\bin`},
		{`C:\..\..\bin`, `C:\bin`},
		{`C:\.\..\`, `C:\`},
		{`\\?\C:\AWF\bin`, `C:\AWF\bin`},
		{`\\?\uNc\Server\Share\AWF\..\bin\`, `\\Server\Share\bin`},
		{`\\Server\Share\..\..\`, `\\Server\Share`},
		{`C:\用户\AWF\bin`, `C:\用户\AWF\bin`},
	} {
		got, err := canonicalInstallPathBin(tc.input)
		if err != nil || got != tc.want {
			t.Errorf("canonical(%q) = %q, %v; want %q", tc.input, got, err, tc.want)
		}
	}
	for _, input := range []string{
		"", " ", `AWF\bin`, `C:bin`, `\bin`, `"C:\bin"`, `\\Server`, `\\\Share`,
		`\\.\Share\bin`, `\\Server\..\bin`, `C:\bad.\bin`, `C:\bad \bin`,
		`C:\bad*\bin`, `C:\bad:stream`, "C:\\bad\x00\\bin", `C:\AWF;other\bin`,
		`\\?\GLOBALROOT\Device\HarddiskVolume1\bin`, string([]byte{'C', ':', '\\', 0xff}),
	} {
		if got, err := canonicalInstallPathBin(input); err == nil {
			t.Errorf("accepted invalid bin %q as %q", input, got)
		}
	}
	unc := `\\Server\Share\AWF\bin`
	if got := moveInstallPathFirst(`\\?\UNC\server\share\awf\bin;\\Server\Other\AWF\bin`, unc, installPathTestLookup); got != unc+`;\\Server\Other\AWF\bin` {
		t.Fatalf("UNC matching changed an unrelated share: %q", got)
	}
}

func TestInstallPathValueEncodingPreservesTypeAndText(t *testing.T) {
	for _, kind := range []uint32{installPathREGSZ, installPathREGExpandSZ} {
		for _, text := range []string{"", `C:\用户\🚀; %LOCALAPPDATA%\Tools;`, strings.Repeat("x", maxInstallPathUnits-1)} {
			value := installPathValue{text, kind}
			data, err := encodeInstallPathValue(value)
			if err != nil {
				t.Fatal(err)
			}
			if len(data) < 2 || data[len(data)-1] != 0 || data[len(data)-2] != 0 {
				t.Fatal("encoded registry string is not terminated")
			}
			for _, stored := range [][]byte{data, data[:len(data)-2]} {
				decoded, err := decodeInstallPathValue(kind, stored)
				if err != nil || decoded != value {
					t.Fatalf("decode(%d bytes) = %#v, %v; want %#v", len(stored), decoded, err, value)
				}
			}
		}
	}
	for _, value := range []installPathValue{
		{"anything", 7}, {"a\x00b", installPathREGSZ}, {string([]byte{0xff}), installPathREGSZ},
		{strings.Repeat("x", maxInstallPathUnits), installPathREGSZ},
		{strings.Repeat("🚀", maxInstallPathUnits/2+1), installPathREGExpandSZ},
	} {
		if _, err := encodeInstallPathValue(value); err == nil {
			t.Errorf("accepted invalid registry value kind=%d, bytes=%d", value.kind, len(value.text))
		}
	}
	for _, data := range [][]byte{
		{0}, {0, 0, 0, 0}, {0, 0xd8}, {0, 0xdc}, {0, 0xd8, 'a', 0},
		{'a', 0, 0, 0, 'b', 0}, make([]byte, maxInstallPathUnits*2+2),
	} {
		if _, err := decodeInstallPathValue(installPathREGSZ, data); err == nil {
			t.Errorf("accepted malformed registry data (%d bytes)", len(data))
		}
	}
	if _, err := decodeInstallPathValue(4, []byte{'x', 0}); err == nil {
		t.Fatal("accepted non-string registry type")
	}
}

type installPathFixture struct {
	user                          installPathValue
	process                       string
	readErr, writeErr, processErr error
	calls                         []string
}

func (f *installPathFixture) ops() installPathOps {
	return installPathOps{
		readUser: func() (installPathValue, error) {
			f.calls = append(f.calls, "read-user")
			return f.user, f.readErr
		},
		writeUser: func(before, after installPathValue) error {
			f.calls = append(f.calls, "write-user")
			if before != f.user {
				return errors.New("unexpected previous user PATH")
			}
			if f.writeErr == nil {
				f.user = after
			}
			return f.writeErr
		},
		lookupEnv: installPathTestLookup,
		getProcess: func() string {
			f.calls = append(f.calls, "get-process")
			return f.process
		},
		setProcess: func(value string) error {
			f.calls = append(f.calls, "set-process")
			if f.processErr == nil {
				f.process = value
			}
			return f.processErr
		},
		broadcast: func() { f.calls = append(f.calls, "broadcast") },
	}
}

func TestRegisterInstallPathPreservesTypeAndOrdersUpdates(t *testing.T) {
	for _, kind := range []uint32{installPathREGSZ, installPathREGExpandSZ} {
		f := installPathFixture{
			user:    installPathValue{`%USERPROFILE%\Tools;` + strings.ToLower(installPathTestBin), kind},
			process: `C:\Windows\System32;C:\Tools`,
		}
		if err := registerInstallPathWith(installPathTestBin, f.ops()); err != nil {
			t.Fatal(err)
		}
		if want := installPathTestBin + `;%USERPROFILE%\Tools`; f.user.text != want || f.user.kind != kind {
			t.Fatalf("user PATH = %#v; want %q and original type %d", f.user, want, kind)
		}
		if f.process != installPathTestBin+`;C:\Windows\System32;C:\Tools` {
			t.Fatalf("process PATH = %q", f.process)
		}
		wantCalls := []string{"read-user", "get-process", "write-user", "set-process", "broadcast"}
		if !reflect.DeepEqual(f.calls, wantCalls) {
			t.Fatalf("calls = %v, want %v", f.calls, wantCalls)
		}
		f.calls = nil
		if err := registerInstallPathWith(installPathTestBin, f.ops()); err != nil {
			t.Fatal(err)
		}
		if want := []string{"read-user", "get-process"}; !reflect.DeepEqual(f.calls, want) {
			t.Fatalf("idempotent registration mutated state: %v", f.calls)
		}
	}
}

func TestRegisterInstallPathFailuresDoNotClaimRollback(t *testing.T) {
	failure := errors.New("fixture failure")
	for _, tc := range []struct {
		name  string
		setup func(*installPathFixture)
		calls []string
		want  string
	}{
		{"read", func(f *installPathFixture) { f.readErr = failure }, []string{"read-user"}, "read user PATH"},
		{"type", func(f *installPathFixture) { f.user.kind = 7 }, []string{"read-user"}, "registry type"},
		{"bad-user-text", func(f *installPathFixture) { f.user.text = "bad\x00value" }, []string{"read-user"}, "embedded NUL"},
		{"oversized-result", func(f *installPathFixture) { f.user.text = strings.Repeat("x", maxInstallPathUnits-1) }, []string{"read-user"}, "prepare user PATH"},
		{"bad-process-text", func(f *installPathFixture) { f.process = "bad\x00value" }, []string{"read-user", "get-process"}, "prepare process PATH"},
		{"oversized-process", func(f *installPathFixture) { f.process = strings.Repeat("x", maxInstallPathUnits-1) }, []string{"read-user", "get-process"}, "prepare process PATH"},
		{"write", func(f *installPathFixture) { f.writeErr = failure }, []string{"read-user", "get-process", "write-user"}, "process PATH was not changed"},
		{"process", func(f *installPathFixture) { f.processErr = failure }, []string{"read-user", "get-process", "write-user", "set-process", "broadcast"}, "user PATH is registered"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			f := installPathFixture{user: installPathValue{`C:\Tools`, installPathREGExpandSZ}, process: `C:\Windows`}
			tc.setup(&f)
			beforeUser, beforeProcess := f.user, f.process
			err := registerInstallPathWith(installPathTestBin, f.ops())
			if err == nil || !strings.Contains(err.Error(), tc.want) {
				t.Fatalf("error = %v, want %q", err, tc.want)
			}
			if !reflect.DeepEqual(f.calls, tc.calls) {
				t.Fatalf("calls = %v, want %v", f.calls, tc.calls)
			}
			if f.process != beforeProcess {
				t.Fatal("failed registration modified process PATH")
			}
			if tc.name != "process" && f.user != beforeUser {
				t.Fatal("failed registration modified user PATH")
			}
			if tc.name == "process" && f.user == beforeUser {
				t.Fatal("successful registry write was incorrectly rolled back")
			}
		})
	}
	f := installPathFixture{}
	if err := registerInstallPathWith(`relative\bin`, f.ops()); err == nil || len(f.calls) != 0 {
		t.Fatalf("invalid bin invoked operations: %v, %v", err, f.calls)
	}
}

func TestRegisterInstallPathUpdatesProcessWhenUserAlreadyRegistered(t *testing.T) {
	f := installPathFixture{user: installPathValue{installPathTestBin, installPathREGSZ}, process: `C:\Windows`}
	if err := registerInstallPathWith(installPathTestBin, f.ops()); err != nil {
		t.Fatal(err)
	}
	if want := []string{"read-user", "get-process", "set-process"}; !reflect.DeepEqual(f.calls, want) {
		t.Fatalf("calls = %v, want %v", f.calls, want)
	}
	if f.process != installPathTestBin+`;C:\Windows` {
		t.Fatalf("process PATH = %q", f.process)
	}
}

func TestInstallPathPreviewIsReadOnly(t *testing.T) {
	for _, text := range []string{"", `C:\Tools`, installPathTestBin, installPathTestBin + ";" + installPathTestBin} {
		f := installPathFixture{user: installPathValue{text, installPathREGExpandSZ}}
		ops := f.ops()
		changed, err := installPathPreviewWith(installPathTestBin, ops.readUser, ops.lookupEnv)
		if err != nil || changed != (text != installPathTestBin) {
			t.Fatalf("preview(%q) = %v, %v", text, changed, err)
		}
		if !reflect.DeepEqual(f.calls, []string{"read-user"}) || f.user.text != text {
			t.Fatalf("preview changed state: %#v", f)
		}
	}
	f := installPathFixture{readErr: errors.New("cannot read")}
	ops := f.ops()
	if changed, err := installPathPreviewWith(installPathTestBin, ops.readUser, ops.lookupEnv); err == nil || changed {
		t.Fatalf("failed preview = %v, %v", changed, err)
	}
	f.calls = nil
	if changed, err := installPathPreviewWith(`relative\bin`, ops.readUser, ops.lookupEnv); err == nil || changed || len(f.calls) != 0 {
		t.Fatalf("invalid preview = %v, %v; calls %v", changed, err, f.calls)
	}
}

func TestRegisterInstallPathRejectsPercentBeforeAnyOperations(t *testing.T) {
	for _, bin := range []string{
		`C:\Users\%LOCALAPPDATA%\AppData\Local\AWF\bin`,
		`C:\Users\50%\AppData\Local\AWF\bin`,
		`C:\Users\%%\AppData\Local\AWF\bin`,
	} {
		// These remain valid Windows filesystem paths. Only PATH registration
		// rejects them, so an installation with --no-path remains possible.
		if _, err := canonicalInstallPath(bin); err != nil {
			t.Fatalf("percent-containing filesystem path rejected: %v", err)
		}
		for _, kind := range []uint32{installPathREGSZ, installPathREGExpandSZ} {
			f := installPathFixture{user: installPathValue{`C:\Tools`, kind}, process: `C:\Windows`}
			beforeUser, beforeProcess := f.user, f.process
			ops := f.ops()
			if err := registerInstallPathWith(bin, ops); err == nil || !strings.Contains(err.Error(), "contains '%'") {
				t.Fatalf("registration(%q) = %v; want percent rejection", bin, err)
			}
			if changed, err := installPathPreviewWith(bin, ops.readUser, ops.lookupEnv); err == nil || changed || !strings.Contains(err.Error(), "contains '%'") {
				t.Fatalf("preview(%q) = %v, %v; want percent rejection", bin, changed, err)
			}
			if len(f.calls) != 0 || f.user != beforeUser || f.process != beforeProcess {
				t.Fatalf("percent-containing bin invoked registry or process operations: %#v", f)
			}
		}
	}
}
