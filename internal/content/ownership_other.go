//go:build !linux && !darwin

package content

import (
	"fmt"
	"os"
)

func privateFile(string) (*os.File, error) { return nil, fmt.Errorf("awf-content v1 requires Linux") }
func acquireContentLock(string) (func() error, error) {
	return nil, fmt.Errorf("awf-content v1 requires Linux")
}
func validateContentFile(os.FileInfo) error    { return fmt.Errorf("awf-content v1 requires Linux") }
func validateDataDirectory(string, bool) error { return fmt.Errorf("awf-content v1 requires Linux") }
