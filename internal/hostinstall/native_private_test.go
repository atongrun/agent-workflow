//go:build linux

package hostinstall

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// Developer-only, precompiled private acceptance runner. No production command
// bypasses public release/tag verification. Default tests never enter this path.
var privateNativeInput = flag.String("awf-private-native-input", "", "approved private offline input directory beneath /tmp")
var privateNativeManifest = flag.String("awf-private-native-manifest-sha256", "", "independently approved exact manifest SHA256")
var privateNativeInstall = flag.Bool("awf-private-native-install", false, "explicitly authorized real fixed-path native installation")

func loadPrivateNativeInput(dir, expected string, identity buildIdentity) (Manifest, RuntimeInput, error) {
	var m Manifest
	var in RuntimeInput
	bad := errors.New("private native input ownership, bytes or candidate identity mismatch")
	if !digestPattern.MatchString(expected) || validateSandbox(dir) != nil {
		return m, in, bad
	}
	root, err := os.OpenRoot(dir)
	if err != nil {
		return m, in, bad
	}
	defer root.Close()
	var entries int
	var size int64
	// Even unused cache entries must be private regular files, never links. The
	// installed closure still rehashes each selected SHA512 body against its URL.
	err = fs.WalkDir(root.FS(), ".", func(name string, entry fs.DirEntry, err error) error {
		if err != nil {
			return bad
		}
		info, err := root.Lstat(name)
		if err != nil || requireFixtureOwner(info) != nil || info.Mode().Perm()&0077 != 0 || info.Mode()&(os.ModeSymlink|os.ModeSetuid|os.ModeSetgid) != 0 || (!info.IsDir() && !info.Mode().IsRegular()) {
			return bad
		}
		entries++
		size += info.Size()
		if entries > maxRuntimeEntries || size > MaxBundleBytes {
			return bad
		}
		return nil
	})
	if err != nil {
		return m, in, bad
	}
	read := func(name string, limit int64) ([]byte, error) {
		f, err := root.Open(name)
		if err != nil {
			return nil, bad
		}
		defer f.Close()
		b, err := io.ReadAll(io.LimitReader(f, limit+1))
		if err != nil || int64(len(b)) > limit {
			return nil, bad
		}
		return b, nil
	}
	b, err := read("manifest.json", MaxManifestBytes)
	if err != nil || hashData(b) != expected {
		return m, in, bad
	}
	m, err = ParseManifest(b)
	if err != nil || !auditedRuntimeManifest(m) || identity != (buildIdentity{1, m.Version, m.SourceCommit, "linux", "amd64", "v1"}) {
		return m, in, bad
	}
	if err := verifyStage(filepath.Join(dir, "stage"), m, manifestDigest(m)); err != nil {
		return m, in, bad
	}
	in.CacheDirectory = filepath.Join(dir, "cache")
	for name, digest := range supplementalPins {
		b, err := read("supplemental/registry-"+name+".json", 4<<20)
		if err != nil || !pinHash(b, digest) {
			return m, in, bad
		}
		in.Supplemental = append(in.Supplemental, RegistryMetadata{Data: b, SHA256: digest})
	}
	return m, in, nil
}

func TestPrivateNativeAcceptance(t *testing.T) {
	if *privateNativeInput == "" {
		t.Skip("private candidate input and explicit manifest approval not supplied")
	}
	m, in, err := loadPrivateNativeInput(*privateNativeInput, *privateNativeManifest, NativeBuildIdentity())
	if err != nil {
		t.Fatal(err)
	}
	o := &Progress{Out: os.Stdout}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()
	var a *nativeAdapter
	if *privateNativeInstall {
		// Retain the public adapter's real root/platform/executable/fresh/unit/port
		// guards; there is no synthetic account, command or filesystem injection.
		a, err = openNative(o)
		if err != nil {
			t.Fatal(err)
		}
		defer a.root.Close()
		if err := a.fresh(); err != nil {
			t.Fatal(err)
		}
		lock, err := a.lock()
		if err != nil {
			t.Fatal(err)
		}
		defer lock.Close()
	}
	work, err := os.MkdirTemp("/tmp", "awf-private-native-runtime-")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(work)
	r, err := ApplyRuntimeFixture(ctx, m, filepath.Join(*privateNativeInput, "stage"), work, o, in)
	if err != nil {
		t.Fatal(err)
	}
	if a == nil {
		fmt.Fprintln(os.Stdout, "Private candidate runtime prepared only; no native installation, init or activation performed.")
		return
	}
	generation := filepath.Join(work, "releases", "layout-2-"+manifestDigest(m)+"-"+runtimeInputDigest(in))
	if err := a.installPrepared(ctx, m, generation, r); err != nil {
		t.Fatal(err)
	}
	if _, err := a.installed(ctx); err != nil {
		t.Fatal(err)
	}
	fmt.Fprintln(os.Stdout, "Private candidate programs installed; services have not started. Public bootstrap and native acceptance remain unverified.")
}

func TestPrivateNativeInputRefusesUnapprovedOrUnsafeInputs(t *testing.T) {
	dir := privateParent(t)
	for _, expected := range []string{"", "guessed", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"} {
		if _, _, err := loadPrivateNativeInput(dir, expected, NativeBuildIdentity()); err == nil {
			t.Fatal("unapproved or missing manifest admitted")
		}
	}
	if err := os.Symlink("/etc/passwd", filepath.Join(dir, "manifest.json")); err != nil {
		t.Fatal(err)
	}
	if _, _, err := loadPrivateNativeInput(dir, hashData(nil), NativeBuildIdentity()); err == nil {
		t.Fatal("linked private input admitted")
	}
	if err := os.Remove(filepath.Join(dir, "manifest.json")); err != nil {
		t.Fatal(err)
	}
	m, _ := manifestFixture()
	raw, _ := json.Marshal(m)
	if err := os.WriteFile(filepath.Join(dir, "manifest.json"), raw, 0600); err != nil {
		t.Fatal(err)
	}
	wrong := buildIdentity{1, m.Version, m.SourceCommit, "linux", "amd64", "v1"}
	wrong.SourceCommit = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
	if _, _, err := loadPrivateNativeInput(dir, hashData(raw), wrong); err == nil {
		t.Fatal("different or unaudited candidate admitted")
	}
}
