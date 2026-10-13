//go:build !linux

package host

import (
	"errors"
	"net"
)

func validateProviderPeer(net.Conn) error { return errors.New("private provider peer requires Linux") }

func validateProviderSocket(string) error {
	return errors.New("private provider broker requires Linux")
}
