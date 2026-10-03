//go:build !windows

package lifecycle

import "errors"

func nativeFreshInstallOps() freshInstallOps {
	return freshInstallOps{context: func() error { return errors.New("awf install requires native Windows") }}
}
