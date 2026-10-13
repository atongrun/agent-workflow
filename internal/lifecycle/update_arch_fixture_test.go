package lifecycle

import (
	"context"
	"os"
	"path/filepath"
	"testing"
)

func TestUpdaterFixtureStagesBothSupportedArchitectures(t *testing.T) {
	for _, arch := range []string{"amd64", "arm64"} {
		t.Run(arch, func(t *testing.T) {
			count := 0
			client := freshFixtureClientForArch(t, "v1.2.3", arch, false, &count)
			target, err := resolveReleaseTarget(context.Background(), client, "v1.2.3", arch)
			if err != nil {
				t.Fatal(err)
			}
			root := privateReleaseRoot(t)
			version, err := stageSelectedRelease(context.Background(), client, root, target, arch, "", true, "v1.2.3")
			if err != nil {
				t.Fatal(err)
			}
			if version != "v1.2.3" || count < 4 {
				t.Fatalf("architecture %s did not verify/download/stage release: %s %d", arch, version, count)
			}
			if _, err := os.Stat(filepath.Join(root, "versions", version, "awf.exe")); err != nil {
				t.Fatal(err)
			}
		})
	}
}
