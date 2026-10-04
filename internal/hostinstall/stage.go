package hostinstall

import (
	"bytes"
	"context"
	"crypto/sha256"
	"debug/elf"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"reflect"
	"time"
)

type StageError struct{ Component, Stage, Reason string }

func (e *StageError) Error() string { return fmt.Sprintf("%s %s: %s", e.Component, e.Stage, e.Reason) }

type StageReceipt struct {
	Schema            int    `json:"schema"`
	ManifestSHA256    string `json:"manifestSHA256"`
	SourceCommit      string `json:"sourceCommit"`
	ArtifactsVerified bool   `json:"artifactsVerified"`
	Installed         bool   `json:"installed"`
}

// Stage downloads and verifies artifacts in an explicit private staging parent.
// It never extracts, executes, activates or initializes anything. Pi metadata is
// staged, not npm-installed. Observer is required so later install/update callers
// cannot accidentally omit the user's progress contract.
func Stage(ctx context.Context, m Manifest, parent string, client *http.Client, observer Observer) (result string, err error) {
	if err := m.Validate(); err != nil {
		return "", err
	}
	if m.Arch != "amd64" {
		return "", errors.New("arm64 native acceptance is not complete")
	}
	if nilObserver(observer) {
		return "", errors.New("staging requires a progress observer")
	}
	if p, ok := observer.(*Progress); ok && p.Out == nil {
		return "", errors.New("staging progress has no output destination")
	}
	defer func() {
		if failure, ok := err.(*StageError); ok {
			observer.Event(ProgressEvent{Component: failure.Component, Stage: failure.Stage, State: "failed"})
		}
	}()
	if ctx.Err() != nil {
		return "", &StageError{"bundle", "stage", "staging was cancelled"}
	}
	info, err := os.Lstat(parent)
	if err != nil || !filepath.IsAbs(parent) || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 || info.Mode().Perm()&0077 != 0 {
		return "", errors.New("staging parent must be an existing private real directory")
	}
	encoded, _ := json.Marshal(m)
	sum := sha256.Sum256(encoded)
	digest := hex.EncodeToString(sum[:])
	final := filepath.Join(parent, "bundle-"+digest)
	if _, err = os.Lstat(final); err == nil {
		observer.Event(ProgressEvent{Component: "bundle", Stage: "verify", State: "started"})
		if err = verifyStage(final, m, digest); err != nil {
			return "", &StageError{"bundle", "verify", "existing stage is invalid; explicit inspection required"}
		}
		observer.Event(ProgressEvent{Component: "bundle", Stage: "verify", State: "completed"})
		return final, nil
	} else if !os.IsNotExist(err) {
		return "", errors.New("existing stage is unreadable")
	}
	work, err := os.MkdirTemp(parent, ".awf-host-stage-")
	if err != nil {
		return "", errors.New("private staging directory could not be created")
	}
	defer os.RemoveAll(work)
	c := http.Client{Timeout: 2 * time.Minute}
	if client != nil {
		c = *client
	}
	if c.Timeout <= 0 || c.Timeout > 2*time.Minute {
		c.Timeout = 2 * time.Minute
	}
	c.CheckRedirect = func(r *http.Request, via []*http.Request) error {
		if len(via) > 5 || r.URL.Scheme != "https" || r.URL.User != nil || r.URL.Fragment != "" {
			return errors.New("unsafe artifact redirect")
		}
		if len(via) == 0 || via[0].URL.Host != "github.com" {
			return errors.New("metadata and dependency redirects are refused")
		}
		switch r.URL.Host {
		case "release-assets.githubusercontent.com", "objects.githubusercontent.com":
			return nil
		}
		return errors.New("artifact redirect is outside official GitHub CDN")
	}
	if err = verifySource(ctx, &c, m, observer); err != nil {
		return "", err
	}
	for _, component := range m.Components {
		directory := filepath.Join(work, component.ID)
		if err = os.Mkdir(directory, 0700); err != nil {
			return "", &StageError{component.ID, "stage", "private stage could not be created"}
		}
		for _, artifact := range component.Artifacts {
			if err = download(ctx, &c, artifact, component.ID, directory, m.Arch, observer); err != nil {
				return "", err
			}
		}
	}
	if ctx.Err() != nil {
		return "", &StageError{"bundle", "stage", "staging was cancelled"}
	}
	observer.Event(ProgressEvent{Component: "bundle", Stage: "stage", State: "started"})
	receipt := StageReceipt{1, digest, m.SourceCommit, true, false}
	data, _ := json.Marshal(receipt)
	if err = os.WriteFile(filepath.Join(work, "stage.json"), data, 0600); err != nil {
		return "", &StageError{"bundle", "stage", "verified receipt could not be written"}
	}
	if ctx.Err() != nil {
		return "", &StageError{"bundle", "stage", "staging was cancelled"}
	}
	if err = os.Rename(work, final); err != nil {
		if e := verifyStage(final, m, digest); e == nil {
			observer.Event(ProgressEvent{Component: "bundle", Stage: "stage", State: "completed"})
			return final, nil
		}
		return "", &StageError{"bundle", "stage", "verified stage could not be committed"}
	}
	observer.Event(ProgressEvent{Component: "bundle", Stage: "stage", State: "completed"})
	return final, nil
}

func nilObserver(o Observer) bool {
	if o == nil {
		return true
	}
	v := reflect.ValueOf(o)
	switch v.Kind() {
	case reflect.Pointer, reflect.Func, reflect.Map, reflect.Slice, reflect.Chan, reflect.Interface:
		return v.IsNil()
	}
	return false
}

func verifySource(ctx context.Context, c *http.Client, m Manifest, observer Observer) error {
	observer.Event(ProgressEvent{Component: "awf-host", Stage: "source", State: "started"})
	address := "https://api.github.com/repos/atongrun/agent-workflow/git/ref/tags/" + m.Version
	for i := 0; i < 3; i++ {
		if ctx.Err() != nil {
			return &StageError{"awf-host", "source", "source verification was cancelled"}
		}
		req, _ := http.NewRequestWithContext(ctx, "GET", address, nil)
		response, err := c.Do(req)
		if err != nil {
			return &StageError{"awf-host", "source", "official source lookup failed"}
		}
		data, readErr := io.ReadAll(io.LimitReader(response.Body, (1<<20)+1))
		response.Body.Close()
		if response.StatusCode != 200 || readErr != nil || len(data) > 1<<20 {
			return &StageError{"awf-host", "source", "official source lookup failed"}
		}
		var object struct{ Object struct{ Type, SHA string } }
		if uniqueJSON(data) != nil || json.Unmarshal(data, &object) != nil {
			return &StageError{"awf-host", "source", "official tag could not be verified"}
		}
		kind, sha := object.Object.Type, object.Object.SHA
		if kind == "commit" && sha == m.SourceCommit {
			observer.Event(ProgressEvent{Component: "awf-host", Stage: "source", State: "completed"})
			return nil
		}
		if kind != "tag" || !commitPattern.MatchString(sha) {
			return &StageError{"awf-host", "source", "tag and manifest source disagree"}
		}
		address = "https://api.github.com/repos/atongrun/agent-workflow/git/tags/" + sha
	}
	return &StageError{"awf-host", "source", "tag chain exceeds verification limit"}
}

func download(ctx context.Context, c *http.Client, a Artifact, id, directory, arch string, o Observer) (err error) {
	stage := "download"
	o.Event(ProgressEvent{Component: id, Stage: stage, State: "started"})
	req, _ := http.NewRequestWithContext(ctx, "GET", a.URL, nil)
	response, e := c.Do(req)
	if e != nil {
		return &StageError{id, stage, "official artifact request failed"}
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		return &StageError{id, stage, "official artifact request failed"}
	}
	if response.ContentLength > 0 && response.ContentLength != a.Bytes {
		return &StageError{id, stage, "artifact length differs from manifest"}
	}
	path := filepath.Join(directory, a.Name)
	file, e := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if e != nil {
		return &StageError{id, stage, "private artifact file could not be created"}
	}
	hash := sha256.New()
	reader := io.LimitReader(response.Body, a.Bytes+1)
	buffer := make([]byte, 64<<10)
	var count int64
	total := response.ContentLength
	if total < 0 {
		total = 0
	}
	for {
		if ctx.Err() != nil {
			file.Close()
			return &StageError{id, stage, "artifact download was cancelled"}
		}
		n, readErr := reader.Read(buffer)
		if n > 0 {
			count += int64(n)
			if count > a.Bytes {
				file.Close()
				return &StageError{id, stage, "artifact exceeds manifest size"}
			}
			if _, e = file.Write(buffer[:n]); e != nil {
				file.Close()
				return &StageError{id, stage, "artifact write failed"}
			}
			_, _ = hash.Write(buffer[:n])
			o.Event(ProgressEvent{Component: id, Stage: stage, State: "progress", Bytes: count, Total: total})
		}
		if readErr == io.EOF {
			break
		}
		if readErr != nil {
			file.Close()
			return &StageError{id, stage, "artifact stream failed"}
		}
	}
	if e = file.Close(); e != nil || count != a.Bytes {
		return &StageError{id, stage, "artifact stream is incomplete"}
	}
	o.Event(ProgressEvent{Component: id, Stage: stage, State: "completed", Bytes: count, Total: total})
	stage = "verify"
	o.Event(ProgressEvent{Component: id, Stage: stage, State: "started"})
	if hex.EncodeToString(hash.Sum(nil)) != a.SHA256 {
		return &StageError{id, stage, "artifact SHA-256 differs from manifest"}
	}
	if e = verifyFormat(path, a, arch); e != nil {
		return &StageError{id, stage, "artifact format or architecture is invalid"}
	}
	o.Event(ProgressEvent{Component: id, Stage: stage, State: "completed"})
	return nil
}
func verifyFormat(path string, a Artifact, arch string) error {
	switch a.Format {
	case "elf":
		f, err := elf.Open(path)
		if err != nil {
			return err
		}
		defer f.Close()
		machine := elf.EM_X86_64
		if arch == "arm64" {
			machine = elf.EM_AARCH64
		}
		if f.Class != elf.ELFCLASS64 || f.Machine != machine || f.ByteOrder.String() != "LittleEndian" || (f.Type != elf.ET_EXEC && f.Type != elf.ET_DYN) {
			return errors.New("wrong ELF target")
		}
	case "json":
		if a.Bytes > 4<<20 {
			return errors.New("package metadata exceeds limit")
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		var object map[string]json.RawMessage
		if json.Unmarshal(data, &object) != nil || object == nil {
			return errors.New("invalid package metadata")
		}
	}
	return nil // Archives remain hashed opaque artifacts: extraction is a later slice.
}
func verifyStage(root string, m Manifest, digest string) error {
	info, err := os.Lstat(root)
	if err != nil || !info.IsDir() || info.Mode().Perm()&0077 != 0 {
		return errors.New("invalid stage directory")
	}
	receiptPath := filepath.Join(root, "stage.json")
	info, err = os.Lstat(receiptPath)
	if err != nil || !info.Mode().IsRegular() || info.Size() > 4096 || info.Mode().Perm()&0077 != 0 {
		return errors.New("invalid stage receipt file")
	}
	rootEntries, err := os.ReadDir(root)
	if err != nil || len(rootEntries) != len(m.Components)+1 {
		return errors.New("unexpected stage contents")
	}
	data, err := os.ReadFile(receiptPath)
	if err != nil || len(data) > 4096 {
		return errors.New("invalid stage receipt")
	}
	var receipt StageReceipt
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if uniqueJSON(data) != nil || decoder.Decode(&receipt) != nil || receipt != (StageReceipt{1, digest, m.SourceCommit, true, false}) {
		return errors.New("invalid stage receipt")
	}
	for _, component := range m.Components {
		dir := filepath.Join(root, component.ID)
		info, err = os.Lstat(dir)
		if err != nil || !info.IsDir() {
			return errors.New("invalid component directory")
		}
		entries, e := os.ReadDir(dir)
		if e != nil || len(entries) != len(component.Artifacts) {
			return errors.New("unexpected component contents")
		}
		for _, artifact := range component.Artifacts {
			path := filepath.Join(dir, artifact.Name)
			info, err = os.Lstat(path)
			if err != nil || !info.Mode().IsRegular() || info.Size() != artifact.Bytes || info.Mode().Perm()&0077 != 0 {
				return errors.New("invalid staged artifact")
			}
			file, err := os.Open(path)
			if err != nil {
				return err
			}
			hash := sha256.New()
			_, err = io.Copy(hash, io.LimitReader(file, artifact.Bytes+1))
			file.Close()
			if err != nil || hex.EncodeToString(hash.Sum(nil)) != artifact.SHA256 {
				return errors.New("staged artifact changed")
			}
			if err = verifyFormat(path, artifact, m.Arch); err != nil {
				return err
			}
		}
	}
	return nil
}
