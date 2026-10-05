//go:build !linux

package hostinstall

import (
	"context"
	"io"
)

func HandleNative(context.Context, []string, io.Reader, io.Writer, io.Writer) (bool, error) {
	return false, nil
}
