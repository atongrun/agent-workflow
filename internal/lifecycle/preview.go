package lifecycle

import (
	"bufio"
	"errors"
	"fmt"
	"io"
	"strings"
)

func approveChannelPreview(selection ChannelSelection, version string, explicit bool, in io.Reader, out io.Writer, interactive bool) (ChannelSelection, error) {
	if explicit {
		selection.PreviewApproved = true
	}
	if !prereleaseVersion(version) || selection.PreviewApproved {
		return selection, nil
	}
	if !interactive || in == nil {
		return selection, errors.New("the go-v1 channel currently selects a preview release; rerun interactively to confirm, or use awf update --allow-prerelease to approve previews for this channel")
	}
	fmt.Fprintf(out, "The go-v1 channel selects preview %s. Preview releases may be unstable. Allow this preview and future previews on go-v1? [y/N]: ", version)
	// Bound the answer; a piped stream can never authorize this console-only path.
	answer, err := bufio.NewReader(io.LimitReader(in, 128)).ReadString('\n')
	if err != nil || !(strings.EqualFold(strings.TrimSpace(answer), "y") || strings.EqualFold(strings.TrimSpace(answer), "yes")) {
		return selection, errors.New("preview update cancelled; no installed version or preview approval was changed")
	}
	selection.PreviewApproved = true
	return selection, nil
}
