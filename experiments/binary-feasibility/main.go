// Command awf-launcher is a CI-only feasibility prototype.
package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
)

type releaseManifest struct {
	Format  string `json:"format"`
	Version string `json:"version"`
	App     string `json:"app"`
	SHA256  string `json:"sha256"`
}

func fail(message string) {
	fmt.Fprintln(os.Stderr, "awf-launcher:", message)
	os.Exit(78)
}

func digest(path string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	hash := sha256.New()
	if _, err := io.Copy(hash, file); err != nil {
		return "", err
	}
	return hex.EncodeToString(hash.Sum(nil)), nil
}

func main() {
	executable, err := os.Executable()
	if err != nil {
		fail("launcher identity is unavailable")
	}
	root := filepath.Dir(executable)
	raw, err := os.ReadFile(filepath.Join(root, "release.json"))
	if err != nil {
		fail("release manifest is unavailable")
	}
	var manifest releaseManifest
	if json.Unmarshal(raw, &manifest) != nil || manifest.Format != "awf.binary-release.v1" {
		fail("release manifest is invalid")
	}
	if manifest.Version == "" || manifest.App == "" || filepath.Base(manifest.App) != manifest.App {
		fail("release manifest identity is invalid")
	}
	if len(manifest.SHA256) != 64 {
		fail("release manifest checksum is invalid")
	}
	app := filepath.Join(root, manifest.App)
	observed, err := digest(app)
	if err != nil || observed != manifest.SHA256 {
		fail("versioned app checksum mismatch")
	}
	command := exec.Command(app, os.Args[1:]...)
	command.Stdin = os.Stdin
	command.Stdout = os.Stdout
	command.Stderr = os.Stderr
	if err := command.Run(); err != nil {
		if exit, ok := err.(*exec.ExitError); ok {
			os.Exit(exit.ExitCode())
		}
		fail("versioned app could not be executed")
	}
}
