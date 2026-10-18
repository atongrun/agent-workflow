package durablebridge

import "testing"

func TestOnlyValidatedDurableSDKVersions(t *testing.T) {
	for _, version := range []string{"1.3.0"} {
		if !supportedDurableVersion(version) {
			t.Fatal("validated SDK rejected", version)
		}
	}
	for _, version := range []string{"", "1.0.3", "1.0.4", "1.1.0", "1.1.1", "1.2.0", "1.3.1", "2.0.0", "not-pinned"} {
		if supportedDurableVersion(version) {
			t.Fatal("unvalidated SDK accepted", version)
		}
	}
}
