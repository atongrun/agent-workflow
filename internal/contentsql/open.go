// Package contentsql registers the pinned CGO-free driver at the application
// composition boundary. Generic contract and protocol tests need no driver.
package contentsql

import (
	"github.com/atongrun/agent-workflow/internal/content"
	_ "modernc.org/sqlite"
)

func Open(dir string) (*content.Store, error) { return content.OpenStore(dir) }
