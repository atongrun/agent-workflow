//go:build !linux

package hostinstall

import (
	"errors"
	"os"
)

func fixtureLock(*os.Root) (*os.File, error) { return nil, errors.New("fixture apply requires Linux") }
