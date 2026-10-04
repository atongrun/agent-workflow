package core

import (
	"errors"
	"regexp"
	"time"
)

// Maintenance is durable admission fencing, not permission to install software
// or proof that systemd has stopped every native process. No automatic expiry.
type Maintenance struct {
	Revision             int        `json:"revision"`
	Phase                string     `json:"phase"`
	OwnerRequestID       string     `json:"ownerRequestId,omitempty"`
	TargetManifestSHA256 string     `json:"targetManifestSHA256,omitempty"`
	DrainTasks           []string   `json:"drainTasks,omitempty"`
	BeganAt              *time.Time `json:"beganAt,omitempty"`
}

var ErrMaintenanceSealed = errors.New("Host maintenance is sealed; only explicit owner release may change state")
var maintenanceDigest = regexp.MustCompile(`^[0-9a-f]{64}$`)
var maintenanceRequest = regexp.MustCompile(`^[A-Za-z0-9._:-]{1,128}$`)

func ValidateMaintenance(m *Maintenance) error {
	if m == nil {
		return nil
	}
	if m.Revision < 1 {
		return errors.New("invalid persisted maintenance revision")
	}
	switch m.Phase {
	case "open":
		if m.OwnerRequestID != "" || m.TargetManifestSHA256 != "" || len(m.DrainTasks) > 0 || m.BeganAt != nil {
			return errors.New("invalid open maintenance state")
		}
	case "draining", "sealed":
		if !maintenanceRequest.MatchString(m.OwnerRequestID) || !maintenanceDigest.MatchString(m.TargetManifestSHA256) || m.BeganAt == nil {
			return errors.New("invalid maintenance lease")
		}
		seen := map[string]bool{}
		for _, id := range m.DrainTasks {
			if !maintenanceRequest.MatchString(id) || seen[id] {
				return errors.New("invalid maintenance drain identity")
			}
			seen[id] = true
		}
	default:
		return errors.New("unsupported persisted maintenance phase")
	}
	return nil
}
