package lifecycle

import "testing"

// Model the ordinary profile inheritance that production accepts, rather than
// depending on an SSH process's unrelated Temp-directory ACL.
func fixtureProgramRoot(t *testing.T) string { t.Helper(); return ordinaryPermissionFixtureRoot(t) }
