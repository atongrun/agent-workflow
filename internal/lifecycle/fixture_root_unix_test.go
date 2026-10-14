//go:build !windows

package lifecycle

import "testing"

func fixtureProgramRoot(t *testing.T) string { t.Helper(); return t.TempDir() }
