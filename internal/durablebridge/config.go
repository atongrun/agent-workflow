package durablebridge

import (
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type Credential struct {
	Owner    string `json:"owner"`
	TokenEnv string `json:"tokenEnv"`
}

type Command struct {
	Executable string            `json:"executable"`
	Args       []string          `json:"args"`
	Env        map[string]string `json:"env"`
}

type Config struct {
	StorageDir      string       `json:"storageDir"`
	RuntimeDir      string       `json:"runtimeDir"`
	PiAgentDir      string       `json:"piAgentDir"`
	Worker          Command      `json:"worker"`
	Credentials     []Credential `json:"credentials"`
	StartupSeconds  int          `json:"startupSeconds,omitempty"`
	ShutdownSeconds int          `json:"shutdownSeconds,omitempty"`
	RequestSeconds  int          `json:"requestSeconds,omitempty"`
}

func LoadConfig(path string) (Config, error) {
	var cfg Config
	if !filepath.IsAbs(path) || filepath.Clean(path) != path || path == "/" || strings.ContainsRune(path, 0) {
		return cfg, ErrInvalid
	}
	f, err := openConfigFile(path)
	if err != nil {
		return cfg, err
	}
	defer f.Close()
	return readConfig(f)
}

func readConfig(input io.Reader) (Config, error) {
	var cfg Config
	b, err := io.ReadAll(io.LimitReader(input, 65537))
	if err != nil || len(b) > 65536 || strictJSON(b, &cfg) != nil {
		return cfg, ErrInvalid
	}
	return cfg.normalized()
}

func (c Config) normalized() (Config, error) {
	for _, path := range []string{c.StorageDir, c.RuntimeDir, c.PiAgentDir, c.Worker.Executable} {
		if !filepath.IsAbs(path) || filepath.Clean(path) != path || path == "/" || strings.ContainsRune(path, 0) {
			return c, ErrInvalid
		}
	}
	if c.StorageDir == c.RuntimeDir || c.StorageDir == c.PiAgentDir || c.RuntimeDir == c.PiAgentDir {
		return c, ErrInvalid
	}
	if c.StartupSeconds == 0 {
		c.StartupSeconds = 15
	}
	if c.ShutdownSeconds == 0 {
		c.ShutdownSeconds = 10
	}
	if c.RequestSeconds == 0 {
		c.RequestSeconds = 30
	}
	if c.StartupSeconds < 1 || c.StartupSeconds > 120 || c.ShutdownSeconds < 1 || c.ShutdownSeconds > 60 || c.RequestSeconds < 1 || c.RequestSeconds > 120 || len(c.Worker.Args) > 64 || len(c.Worker.Env) > 128 {
		return c, ErrInvalid
	}
	for _, arg := range c.Worker.Args {
		if len(arg) > 4096 || strings.ContainsRune(arg, 0) {
			return c, ErrInvalid
		}
	}
	for k, v := range c.Worker.Env {
		if k == "" || len(k) > 128 || len(v) > 16384 || strings.ContainsAny(k, "=\x00") || strings.ContainsRune(v, 0) || strings.HasPrefix(k, "AWF_DURABLE_") || k == "PI_CODING_AGENT_DIR" {
			return c, ErrInvalid
		}
	}
	if len(c.Credentials) < 1 || len(c.Credentials) > 256 {
		return c, ErrInvalid
	}
	return c, nil
}

func (c Config) RequestTimeout() time.Duration { return time.Duration(c.RequestSeconds) * time.Second }

func validateWorkerSecrets(command Command, credentials []Credential, protected []string) error {
	for _, cred := range credentials {
		protected = append(protected, os.Getenv(cred.TokenEnv))
	}
	for _, v := range command.Env {
		for _, secret := range protected {
			if secret != "" && strings.Contains(v, secret) {
				return ErrInvalid
			}
		}
	}
	for _, arg := range command.Args {
		for _, secret := range protected {
			if secret != "" && strings.Contains(arg, secret) {
				return ErrInvalid
			}
		}
	}
	return nil
}
