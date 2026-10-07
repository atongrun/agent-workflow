// Package durablebridge adapts a single native Pi Durable worker to GoHost.
// It does not own agent tasks, checkpoints or recovery state.
package durablebridge

import (
	"errors"
	"os"
)

var (
	ErrStorageOwned = errors.New("Durable storage already has an owner")
	ErrUnsupported  = errors.New("Durable process ownership requires Linux")
)

// StorageLease is an OS ownership boundary, not an agent execution record.
// The operator must give each native storage directory one canonical pathname.
// Neither Go nor the worker may replace or unlink its lock file.
type StorageLease struct{ file *os.File }

// File may be passed to a child through exec.Cmd.ExtraFiles. The child must keep
// that descriptor open until native storage is closed. Close only drops this
// process's descriptor; it deliberately does not unlock a child's shared lease.
func (l *StorageLease) File() *os.File { return l.file }
func (l *StorageLease) Close() error   { return l.file.Close() }
