//go:build !linux

package durablebridge

func AcquireStorageLease(string) (*StorageLease, error) { return nil, ErrUnsupported }
