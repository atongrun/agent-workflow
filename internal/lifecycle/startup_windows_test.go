package lifecycle

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"
)

func windowsStartupFixture(t *testing.T) (string, Startup) {
	t.Helper()
	root := privatePermissionFixtureRoot(t)
	pending := Startup{LaunchID: strings.Repeat("a", 64), Version: "v1.2.3"}
	if err := createStartup(root, pending); err != nil {
		t.Fatal(err)
	}
	return root, pending
}

func TestWindowsStartupCleanupRetriesTransientConflicts(t *testing.T) {
	for _, kind := range []string{"reader", "lock"} {
		t.Run(kind, func(t *testing.T) {
			root, pending := windowsStartupFixture(t)
			var held *os.File
			var err error
			want := syscall.Errno(32) // ERROR_SHARING_VIOLATION
			if kind == "reader" {
				held, err = os.Open(startupPath(root))
			} else {
				held, err = lockFile(filepath.Join(root, "startup.lock"))
				want = syscall.Errno(33) // ERROR_LOCK_VIOLATION
			}
			if err != nil {
				t.Fatal(err)
			}
			defer held.Close()
			// Confirm the native fixture actually blocks one cleanup attempt.
			if err = clearStartupOnce(root, pending.LaunchID); !errors.Is(err, want) {
				t.Fatalf("held %s did not produce its native conflict: %v", kind, err)
			}
			released := make(chan error, 1)
			go func() {
				time.Sleep(100 * time.Millisecond)
				released <- held.Close()
			}()
			err = clearStartup(root, pending.LaunchID)
			if closeErr := <-released; closeErr != nil {
				t.Fatal(closeErr)
			}
			if err != nil {
				t.Fatalf("transient %s conflict was not recovered: %v", kind, err)
			}
			if err = noPendingStartup(root); err != nil {
				t.Fatal(err)
			}
		})
	}
}

func TestWindowsStartupCleanupRetryRechecksIdentity(t *testing.T) {
	root, pending := windowsStartupFixture(t)
	held, err := lockFile(filepath.Join(root, "startup.lock"))
	if err != nil {
		t.Fatal(err)
	}
	defer held.Close()
	if err = clearStartupOnce(root, pending.LaunchID); !errors.Is(err, syscall.Errno(33)) {
		t.Fatalf("fixture did not hold startup lock: %v", err)
	}
	next := Startup{LaunchID: strings.Repeat("b", 64), Version: "v1.2.4"}
	changed := make(chan error, 1)
	go func() {
		time.Sleep(100 * time.Millisecond)
		writeErr := writePrivateJSON(startupPath(root), next)
		closeErr := held.Close()
		if writeErr != nil {
			changed <- writeErr
		} else {
			changed <- closeErr
		}
	}()
	err = clearStartup(root, pending.LaunchID)
	if changeErr := <-changed; changeErr != nil {
		t.Fatal(changeErr)
	}
	if err == nil || !strings.Contains(err.Error(), "identity changed") {
		t.Fatalf("old cleanup did not refuse the replacement identity: %v", err)
	}
	if got, err := readStartup(root); err != nil || got != next {
		t.Fatalf("replacement intent changed: %v", err)
	}
}

func TestWindowsStartupCleanupPersistentConflictStaysClosed(t *testing.T) {
	root, pending := windowsStartupFixture(t)
	held, err := lockFile(filepath.Join(root, "startup.lock"))
	if err != nil {
		t.Fatal(err)
	}
	defer held.Close()
	if err = clearStartup(root, pending.LaunchID); !errors.Is(err, syscall.Errno(33)) {
		t.Fatalf("persistent lock conflict was not returned: %v", err)
	}
	if got, err := readStartup(root); err != nil || got != pending {
		t.Fatalf("unresolved intent changed: %v", err)
	}
}

func TestWindowsStartupCleanupDoesNotRetryOtherErrors(t *testing.T) {
	for _, err := range []error{nil, syscall.ERROR_ACCESS_DENIED, os.ErrNotExist, errors.New("identity changed")} {
		if isTransientStartupCleanupError(err) {
			t.Fatalf("non-transient error classified for retry: %v", err)
		}
	}
}
