package content

import (
	"io"
	"net"
	"os"
	"path/filepath"
)

// Config contains only operator-owned generic execution and authentication
// settings. Keep files containing credentials outside the repository.
type Config struct {
	DataDir     string        `json:"dataDir"`
	Credentials []Credential  `json:"credentials"`
	Bridge      ProcessRunner `json:"bridge"`
	Profile     Profile       `json:"profile"`
	QueueLimit  int           `json:"queueLimit"`
}

func LoadConfig(path string) (Config, error) {
	var c Config
	f, err := os.Open(path)
	if err != nil {
		return c, err
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 {
		return c, ErrInvalid
	}
	b, err := io.ReadAll(io.LimitReader(f, MaxBodyBytes+1))
	if err != nil || len(b) > MaxBodyBytes || strictJSON(b, &c) != nil {
		return c, ErrInvalid
	}
	if c.QueueLimit == 0 {
		c.QueueLimit = 64
	}
	if c.Profile.TimeoutSeconds == 0 {
		c.Profile.TimeoutSeconds = 300
	}
	if !filepath.IsAbs(c.DataDir) || c.Bridge.Validate() != nil || validProfile(c.Profile) != nil || c.QueueLimit < 1 || c.QueueLimit > 1024 {
		return c, ErrInvalid
	}
	return c, nil
}

// ValidLoopbackListen is used by the isolated development entry point only.
// Embedded content uses the Host listener without opening another port.
func ValidLoopbackListen(addr string) bool {
	host, port, err := net.SplitHostPort(addr)
	if err != nil || port == "" {
		return false
	}
	if host == "localhost" {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}
