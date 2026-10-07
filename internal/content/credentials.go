package content

import (
	"crypto/sha256"
	"crypto/subtle"
)

// ValidateCredentialIsolation keeps content credentials from also granting
// AWF Host/extension authority when both modules share one HTTP listener.
func ValidateCredentialIsolation(credentials []Credential, hostSecrets ...string) error {
	for _, c := range credentials {
		h := sha256.Sum256([]byte(c.Token))
		for _, secret := range hostSecrets {
			s := sha256.Sum256([]byte(secret))
			if secret != "" && subtle.ConstantTimeCompare(h[:], s[:]) == 1 {
				return ErrInvalid
			}
		}
	}
	return nil
}
