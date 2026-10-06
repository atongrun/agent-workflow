//go:build linux

package hostinstall

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"
)

// Linux has its own publisher-controlled channel. Windows go-v1 is independent.
const LinuxChannelURL = "https://raw.githubusercontent.com/atongrun/agent-workflow/awf/linux-v1/distribution/linux-host-v1.json"

func releaseManifestURL(version string) string {
	return "https://github.com/atongrun/agent-workflow/releases/download/" + version + "/linux-host-v1.json"
}

func readUpdateManifest(ctx context.Context, file, version string, client *http.Client, o Observer) (Manifest, error) {
	var m Manifest
	if file != "" && version != "" {
		return m, errors.New("choose either --manifest or --version")
	}
	if version != "" && !releasePattern.MatchString(version) {
		return m, errors.New("--version requires an exact Linux v1 release tag")
	}
	c := http.Client{Timeout: 30 * time.Second}
	if client != nil {
		c = *client
	}
	if c.Timeout <= 0 || c.Timeout > 30*time.Second {
		c.Timeout = 30 * time.Second
	}
	c.CheckRedirect = func(r *http.Request, via []*http.Request) error {
		if len(via) > 5 || r.URL.Scheme != "https" || r.URL.User != nil || r.URL.Fragment != "" ||
			via[0].URL.Host != "github.com" || (r.URL.Host != "release-assets.githubusercontent.com" && r.URL.Host != "objects.githubusercontent.com") {
			return errors.New("Linux manifest redirect refused")
		}
		return nil
	}
	if file != "" {
		f, err := os.Open(file)
		if err != nil {
			return m, errors.New("manifest unreadable")
		}
		b, err := io.ReadAll(io.LimitReader(f, MaxManifestBytes+1))
		f.Close()
		if err != nil {
			return m, errors.New("manifest unreadable")
		}
		m, err = ParseManifest(b)
		if err != nil {
			return m, err
		}
		published, err := fetchLinuxManifest(ctx, &c, releaseManifestURL(m.Version), o)
		if err != nil {
			return m, err
		}
		if manifestDigest(published) != manifestDigest(m) {
			return m, errors.New("local and immutable release manifests disagree")
		}
	} else {
		address := LinuxChannelURL
		if version != "" {
			address = releaseManifestURL(version)
		}
		var err error
		m, err = fetchLinuxManifest(ctx, &c, address, o)
		if err != nil {
			return m, err
		}
		if version != "" && m.Version != version {
			return m, errors.New("release manifest version differs from requested tag")
		}
		if version == "" {
			// A mutable channel selects an immutable release; it cannot invent new
			// payload hashes/source under an already published version.
			published, err := fetchLinuxManifest(ctx, &c, releaseManifestURL(m.Version), o)
			if err != nil {
				return m, err
			}
			if manifestDigest(published) != manifestDigest(m) {
				return m, errors.New("Linux channel and immutable release manifest disagree")
			}
		}
	}
	if err := verifySource(ctx, &c, m, o); err != nil {
		return m, err
	}
	return m, nil
}

func approveLinuxPreview(version string, allowed, yes bool, in io.Reader, out io.Writer) (bool, error) {
	if allowed || !strings.Contains(version, "-rc.") {
		return allowed, nil
	}
	if yes {
		return false, errors.New("Linux preview requires --allow-prerelease or an earlier explicit linux-host-v1 preview approval")
	}
	fmt.Fprintf(out, "AWF %s is a Linux preview. Allow this and future linux-host-v1 previews? [y/N] ", version)
	var answer string
	if _, err := fmt.Fscanln(in, &answer); err != nil || (answer != "y" && answer != "Y") {
		return false, errors.New("Linux preview declined; no programs changed")
	}
	return true, nil
}

func fetchLinuxManifest(ctx context.Context, c *http.Client, address string, o Observer) (m Manifest, err error) {
	defer func() {
		if err != nil {
			o.Event(ProgressEvent{Component: "linux-channel", Stage: "download", State: "failed"})
		}
	}()
	o.Event(ProgressEvent{Component: "linux-channel", Stage: "download", State: "started"})
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, address, nil)
	response, err := c.Do(req)
	if err != nil {
		return m, errors.New("official Linux update metadata unavailable; no programs changed")
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK || response.ContentLength > MaxManifestBytes {
		return m, errors.New("official Linux update metadata refused; no programs changed")
	}
	b, err := io.ReadAll(io.LimitReader(response.Body, MaxManifestBytes+1))
	if err != nil {
		return m, errors.New("official Linux update metadata unreadable; no programs changed")
	}
	o.Event(ProgressEvent{Component: "linux-channel", Stage: "download", State: "progress", Bytes: int64(len(b)), Total: response.ContentLength})
	m, err = ParseManifest(b)
	if err != nil {
		return m, err
	}
	o.Event(ProgressEvent{Component: "linux-channel", Stage: "download", State: "completed"})
	return m, nil
}

func validateUpdateTarget(next, installed Manifest) error {
	if next.OS != installed.OS || next.Arch != installed.Arch || next.LibC != installed.LibC {
		return errors.New("Linux update platform differs from this installation")
	}
	comparison := compareLinuxVersions(next.Version, installed.Version)
	if comparison < 0 {
		return errors.New("Linux update refuses a version downgrade")
	}
	if comparison == 0 && manifestDigest(next) != manifestDigest(installed) {
		return errors.New("same Linux version has different source or payload; inspect publisher metadata")
	}
	return nil
}

// Inputs have already passed the exact v1 manifest version grammar. Comparing
// canonical decimal strings avoids integer overflow in publisher metadata.
func compareLinuxVersions(left, right string) int {
	l, lrc, _ := strings.Cut(strings.TrimPrefix(left, "v1."), "-rc.")
	r, rrc, _ := strings.Cut(strings.TrimPrefix(right, "v1."), "-rc.")
	decimal := func(a, b string) int {
		if len(a) < len(b) {
			return -1
		}
		if len(a) > len(b) {
			return 1
		}
		return strings.Compare(a, b)
	}
	lparts, rparts := strings.Split(l, "."), strings.Split(r, ".")
	for i := range lparts {
		if order := decimal(lparts[i], rparts[i]); order != 0 {
			return order
		}
	}
	if lrc == "" && rrc != "" {
		return 1
	}
	if lrc != "" && rrc == "" {
		return -1
	}
	return decimal(lrc, rrc)
}
