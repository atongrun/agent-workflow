//go:build !windows

package lifecycle

import "io"

// Managed lifecycle dispatch is Windows-only; pipes and test readers must not
// acquire interactive consent on another platform.
func interactiveUpdateInput(io.Reader) bool { return false }
