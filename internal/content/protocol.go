package content

import (
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"unicode/utf8"
)

var ErrProtocol = errors.New("bridge_protocol")

type Protocol struct {
	ex       Execute
	next     int64
	ready    bool
	settled  bool
	hadError bool
	result   Outcome
}

func NewProtocol(ex Execute) *Protocol { return &Protocol{ex: ex, next: 1} }

func (p *Protocol) Accept(raw []byte) error {
	var e Event
	if len(raw)+1 > MaxFrameBytes || strictJSON(raw, &e) != nil || p.settled || e.Version != 1 || e.JobID != p.ex.JobID || e.ExecutionID != p.ex.ExecutionID || e.OwnerEpoch != p.ex.OwnerEpoch || e.Sequence != p.next {
		return ErrProtocol
	}
	var fields map[string]json.RawMessage
	if json.Unmarshal(raw, &fields) != nil {
		return ErrProtocol
	}
	allowed := map[string]bool{"version": true, "jobId": true, "executionId": true, "ownerEpoch": true, "sequence": true, "type": true}
	switch e.Type {
	case "ready":
		allowed["nativeSessionRef"] = true
	case "artifact":
		allowed["artifact"] = true
	case "settled":
		allowed["stopReason"] = true
	case "error":
		allowed["errorCode"] = true
	}
	for k := range fields {
		if !allowed[k] {
			return ErrProtocol
		}
	}
	switch e.Type {
	case "ready":
		if p.ready || e.NativeSessionRef == "" || len(e.NativeSessionRef) > 512 || !utf8.ValidString(e.NativeSessionRef) || e.Artifact != nil || e.StopReason != "" || e.ErrorCode != "" {
			return ErrProtocol
		}
		p.ready = true
		p.result.SessionRef = e.NativeSessionRef
	case "artifact":
		if !p.ready || p.hadError || p.result.Artifact != nil || e.Artifact == nil || e.NativeSessionRef != "" || e.StopReason != "" || e.ErrorCode != "" {
			return ErrProtocol
		}
		raw, err := VerifyArtifact(*e.Artifact)
		if err != nil {
			return err
		}
		p.result.Artifact = e.Artifact
		p.result.RawArtifact = raw
	case "error":
		if !p.ready || p.hadError || e.Artifact != nil || e.NativeSessionRef != "" || e.StopReason != "" || (e.ErrorCode != "execution_failed" && e.ErrorCode != "invalid_input") {
			return ErrProtocol
		}
		p.hadError = true
		p.result.ErrorCode = e.ErrorCode
	case "settled":
		if !p.ready || e.Artifact != nil || e.NativeSessionRef != "" || e.ErrorCode != "" || (e.StopReason != "completed" && e.StopReason != "aborted" && e.StopReason != "failed") || (p.hadError && e.StopReason != "failed") {
			return ErrProtocol
		}
		if e.StopReason == "completed" && p.result.Artifact == nil {
			return ErrProtocol
		}
		p.settled = true
		p.result.StopReason = e.StopReason
	default:
		return ErrProtocol
	}
	p.next++
	return nil
}

func (p *Protocol) Result(cleanExit, quiescent bool) Outcome {
	r := p.result
	r.CleanExit = cleanExit
	r.Quiescent = quiescent
	if !p.settled && r.ErrorCode == "" {
		r.ErrorCode = "missing_settlement"
	}
	return r
}

func VerifyArtifact(a Artifact) ([]byte, error) {
	if a.Schema != "shortpost.result.v1" || a.MediaType != "application/json" || a.Bytes < 1 || a.Bytes > MaxArtifactBytes || len(a.SHA256) != 64 || len(a.DataBase64) > base64.StdEncoding.EncodedLen(MaxArtifactBytes) {
		return nil, ErrProtocol
	}
	b, err := base64.StdEncoding.Strict().DecodeString(a.DataBase64)
	if err != nil || base64.StdEncoding.EncodeToString(b) != a.DataBase64 || len(b) != a.Bytes || !utf8.Valid(b) || !object(b) {
		return nil, ErrProtocol
	}
	sum := sha256.Sum256(b)
	if hex.EncodeToString(sum[:]) != a.SHA256 {
		return nil, ErrProtocol
	}
	var v any
	if strictJSON(b, &v) != nil {
		return nil, ErrProtocol
	}
	return b, nil
}
