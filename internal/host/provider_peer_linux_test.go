//go:build linux

package host

import (
	"net"
	"os"
	"path/filepath"
	"testing"
)

func TestProviderPeerKernelIdentity(t *testing.T) {
	path := filepath.Join(t.TempDir(), "peer.sock")
	listener, e := net.Listen("unix", path)
	if e != nil {
		t.Fatal(e)
	}
	defer listener.Close()
	accepted := make(chan net.Conn, 1)
	go func() {
		c, e := listener.Accept()
		if e == nil {
			accepted <- c
		}
	}()
	connection, e := net.Dial("unix", path)
	if e != nil {
		t.Fatal(e)
	}
	defer connection.Close()
	server := <-accepted
	defer server.Close()
	err := validateProviderPeer(connection)
	if os.Geteuid() == 0 && err != nil {
		t.Fatal("kernel root peer refused", err)
	}
	if os.Geteuid() != 0 && err == nil {
		t.Fatal("non-root fake peer accepted")
	}
}

func TestProviderSocketRejectsWritableAncestry(t *testing.T) {
	// A caller-owned socket under /tmp must never be accepted as root broker.
	path := filepath.Join(t.TempDir(), "fake.sock")
	listener, e := net.Listen("unix", path)
	if e != nil {
		t.Fatal(e)
	}
	defer listener.Close()
	os.Chmod(path, 0600)
	if validateProviderSocket(path) == nil {
		t.Fatal("socket outside protected /run accepted")
	}
}
