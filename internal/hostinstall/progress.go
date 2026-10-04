package hostinstall

import (
	"fmt"
	"io"
	"strings"
)

type ProgressEvent struct {
	Component string `json:"component"`
	Stage     string `json:"stage"`
	State     string `json:"state"`
	Bytes     int64  `json:"bytes,omitempty"`
	Total     int64  `json:"total,omitempty"`
}
type Observer interface{ Event(ProgressEvent) }

// Progress renders real observations only. Output errors disable display, never
// change installation decisions. Callers explicitly choose TTY; pipes get no ANSI.
type Progress struct {
	Out      io.Writer
	TTY      bool
	disabled bool
	line     bool
	width    int
}

func (p *Progress) Event(e ProgressEvent) {
	if p == nil || p.Out == nil || p.disabled {
		return
	}
	text := fmt.Sprintf("AWF %s %s: %s", e.Component, e.Stage, e.State)
	if e.Stage == "download" && e.State == "progress" {
		text = fmt.Sprintf("AWF %s download: %d bytes (total unknown)", e.Component, e.Bytes)
		if e.Total > 0 {
			percent := 100 * float64(e.Bytes) / float64(e.Total)
			if percent < 0 {
				percent = 0
			}
			if percent > 100 {
				percent = 100
			}
			text = fmt.Sprintf("AWF %s download: %d/%d bytes %.1f%%", e.Component, e.Bytes, e.Total, percent)
			if p.TTY {
				filled := int(percent / 5)
				text = fmt.Sprintf("AWF %s download [%s%s] %d/%d bytes %.1f%%", e.Component, strings.Repeat("=", filled), strings.Repeat(" ", 20-filled), e.Bytes, e.Total, percent)
			}
		}
	} else if e.State == "progress" {
		text = fmt.Sprintf("AWF %s %s: %d bytes observed", e.Component, e.Stage, e.Bytes)
	}
	prefix, suffix := "", "\n"
	if p.TTY && e.State == "progress" {
		prefix, suffix = "\r", ""
		p.line = true
	} else if p.line {
		prefix = "\r"
		p.line = false
	}
	if p.TTY {
		width := len(text)
		if p.width > width {
			text += strings.Repeat(" ", p.width-width)
		}
		p.width = width
		if !p.line {
			p.width = 0
		}
	}
	if _, err := fmt.Fprint(p.Out, prefix, text, suffix); err != nil {
		p.disabled = true
	}
}
