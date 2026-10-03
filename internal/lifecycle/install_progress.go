package lifecycle

import (
	"fmt"
	"io"
	"strings"
	"time"
)

// Fresh installation and update opt in with a console stderr. No URLs, paths,
// server text or credentials enter this display. Nil is completely quiet.
type installProgress struct {
	out     io.Writer
	current string
	line    bool
	last    time.Time
	now     func() time.Time
}

// A broken display must never change the installation result or strand an
// otherwise valid installation. Stop trying after the first output failure.
func (p *installProgress) write(text string) {
	if p.out == nil {
		return
	}
	n, err := io.WriteString(p.out, text)
	if err != nil || n != len(text) {
		p.out = nil
	}
}
func (p *installProgress) endLine() {
	if p.line {
		p.line = false
		p.write("\n")
	}
}
func (p *installProgress) stage(name string) {
	if p == nil {
		return
	}
	p.endLine()
	p.current = name
	if name == "Done" {
		p.write("AWF: Done\n")
		return
	}
	p.write("AWF: " + name + "...\n")
}
func (p *installProgress) failed() {
	if p == nil || p.current == "" {
		return
	}
	p.endLine()
	p.write("AWF: stopped during " + p.current + ".\n")
}
func (p *installProgress) download(received, total int64, finished bool) {
	if p == nil {
		return
	}
	now := time.Now()
	if p.now != nil {
		now = p.now()
	}
	if !finished && received > 0 && now.Sub(p.last) < 250*time.Millisecond {
		return
	}
	p.last = now
	status := fmt.Sprintf("%d bytes (total unknown)", received)
	if total > 0 {
		percent := int(float64(received) / float64(total) * 100)
		if percent > 99 && !finished {
			percent = 99
		}
		if percent > 100 {
			percent = 100
		}
		filled := percent / 5
		status = fmt.Sprintf("[%s%s] %3d%%  %d / %d bytes", strings.Repeat("=", filled), strings.Repeat(" ", 20-filled), percent, received, total)
	}
	p.line = true
	p.write("\rAWF: Download " + status)
	if finished {
		p.endLine()
	}
}

type installProgressReader struct {
	reader          io.Reader
	progress        *installProgress
	received, total int64
}

func (r *installProgressReader) Read(b []byte) (int, error) {
	n, err := r.reader.Read(b)
	r.received += int64(n)
	if n > 0 {
		r.progress.download(r.received, r.total, false)
	}
	return n, err
}
