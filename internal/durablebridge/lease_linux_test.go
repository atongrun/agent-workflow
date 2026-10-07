//go:build linux

package durablebridge

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

func TestLeaseSurvivesParentDescriptorCloseFixture(t *testing.T) {
	path := filepath.Join(t.TempDir(), ".awf-owner.lock")
	lease, err := acquireLeaseFile(path)
	if err != nil {
		t.Fatal(err)
	}
	defer lease.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, os.Args[0], "-test.run=^TestLeaseChildFixture$")
	cmd.Env = []string{"AWF_LEASE_FIXTURE=1"}
	cmd.ExtraFiles = []*os.File{lease.File()}
	out, err := cmd.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	in, err := cmd.StdinPipe()
	if err != nil {
		t.Fatal(err)
	}
	defer in.Close()
	if err = cmd.Start(); err != nil {
		t.Fatal(err)
	}
	defer func() { _ = cmd.Process.Kill(); _ = cmd.Wait() }()
	if ready, err := bufio.NewReader(out).ReadString('\n'); err != nil || ready != "held\n" {
		t.Fatalf("child did not inherit the lease: %q %v", ready, err)
	}
	if err := lease.Close(); err != nil {
		t.Fatal(err)
	}
	if second, err := acquireLeaseFile(path); !errors.Is(err, ErrStorageOwned) {
		if second != nil {
			second.Close()
		}
		t.Fatalf("parent close released a live child's lease: %v", err)
	}
	if err := in.Close(); err != nil {
		t.Fatal(err)
	}
	if err := cmd.Wait(); err != nil {
		t.Fatal(err)
	}
	second, err := acquireLeaseFile(path)
	if err != nil {
		t.Fatalf("dead child retained lease: %v", err)
	}
	second.Close()
}

func TestLeaseChildFixture(t *testing.T) {
	if os.Getenv("AWF_LEASE_FIXTURE") != "1" {
		t.Skip("subprocess fixture")
	}
	f := os.NewFile(3, "owner")
	if _, err := f.Stat(); err != nil {
		os.Exit(2)
	}
	fmt.Println("held")
	_, _ = bufio.NewReader(os.Stdin).ReadByte()
	f.Close()
	os.Exit(0)
}

func TestLeaseRejectsUnsafeFileFixture(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "owner")
	if err := os.WriteFile(path, nil, 0600); err != nil {
		t.Fatal(err)
	}
	alias := filepath.Join(root, "alias")
	if err := os.Link(path, alias); err != nil {
		t.Fatal(err)
	}
	if lease, err := acquireLeaseFile(path); err == nil {
		lease.Close()
		t.Fatal("hard link accepted")
	}
	os.Remove(alias)
	if err := os.Symlink(path, alias); err != nil {
		t.Fatal(err)
	}
	if lease, err := acquireLeaseFile(alias); err == nil {
		lease.Close()
		t.Fatal("symlink accepted")
	}
	if err := os.Chmod(path, 0644); err != nil {
		t.Fatal(err)
	}
	if lease, err := acquireLeaseFile(path); err == nil {
		lease.Close()
		t.Fatal("public owner lease accepted")
	}
}

func TestProductionDirectoryTrust(t *testing.T) {
	dir := t.TempDir()
	if err := os.Chmod(dir, 0700); err != nil {
		t.Fatal(err)
	}
	if err := validateDirectory(dir); err != nil {
		t.Skipf("executor ancestry unsuitable for native production ownership acceptance: %v", err)
	}
	lease, err := AcquireStorageLease(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer lease.Close()
	if _, err := AcquireStorageLease(dir); !errors.Is(err, ErrStorageOwned) {
		t.Fatal(err)
	}
	if err := os.Chmod(dir, 0755); err != nil {
		t.Fatal(err)
	}
	if lease, err := AcquireStorageLease(dir); err == nil {
		lease.Close()
		t.Fatal("public directory accepted")
	}
}

func TestLeaseRequiresCanonicalDirectory(t *testing.T) {
	for _, dir := range []string{".", "/", "/tmp/../tmp", "/tmp//durable", "/tmp/durable/"} {
		if lease, err := AcquireStorageLease(dir); err == nil {
			lease.Close()
			t.Fatalf("noncanonical directory accepted: %q", dir)
		}
	}
}
