package content

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"reflect"
	"strings"
	"unicode/utf8"
)

// strictJSON rejects duplicate keys, excessive depth, trailing values and
// invalid UTF-8 before decoding to a typed envelope.
func strictJSON(raw []byte, dst any) error {
	if !utf8.Valid(raw) {
		return ErrInvalid
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	if err := walkJSON(d, 0); err != nil {
		return ErrInvalid
	}
	if _, err := d.Token(); err != io.EOF {
		return ErrInvalid
	}
	t := reflect.TypeOf(dst)
	if t == nil || t.Kind() != reflect.Pointer || literalFields(raw, t.Elem()) != nil {
		return ErrInvalid
	}
	d = json.NewDecoder(bytes.NewReader(raw))
	d.DisallowUnknownFields()
	if err := d.Decode(dst); err != nil {
		return ErrInvalid
	}
	return nil
}

// encoding/json accepts case-insensitive aliases for struct fields. Wire
// envelopes use exact spelling; RawMessage/map business keys remain opaque.
func literalFields(raw []byte, t reflect.Type) error {
	for t.Kind() == reflect.Pointer {
		t = t.Elem()
	}
	if t == reflect.TypeOf(json.RawMessage{}) {
		return nil
	}
	switch t.Kind() {
	case reflect.Struct:
		var values map[string]json.RawMessage
		if json.Unmarshal(raw, &values) != nil {
			return ErrInvalid
		}
		fields := map[string]reflect.Type{}
		for i := 0; i < t.NumField(); i++ {
			f := t.Field(i)
			tag := strings.Split(f.Tag.Get("json"), ",")[0]
			if tag != "" && tag != "-" {
				fields[tag] = f.Type
			}
		}
		for k, v := range values {
			field, ok := fields[k]
			if !ok || literalFields(v, field) != nil {
				return ErrInvalid
			}
		}
	case reflect.Slice:
		var values []json.RawMessage
		if json.Unmarshal(raw, &values) != nil {
			return ErrInvalid
		}
		for _, v := range values {
			if literalFields(v, t.Elem()) != nil {
				return ErrInvalid
			}
		}
	}
	return nil
}

func walkJSON(d *json.Decoder, depth int) error {
	t, err := d.Token()
	if err != nil {
		return err
	}
	delim, ok := t.(json.Delim)
	if !ok {
		return nil
	}
	depth++
	if depth > MaxJSONDepth {
		return ErrInvalid
	}
	switch delim {
	case '{':
		seen := map[string]bool{}
		for d.More() {
			k, err := d.Token()
			if err != nil {
				return err
			}
			s, ok := k.(string)
			if !ok || seen[s] {
				return ErrInvalid
			}
			seen[s] = true
			if err := walkJSON(d, depth); err != nil {
				return err
			}
		}
	case '[':
		for d.More() {
			if err := walkJSON(d, depth); err != nil {
				return err
			}
		}
	default:
		return ErrInvalid
	}
	end, err := d.Token()
	if err != nil {
		return err
	}
	if (delim == '{' && end != json.Delim('}')) || (delim == '[' && end != json.Delim(']')) {
		return ErrInvalid
	}
	return nil
}

func object(raw []byte) bool {
	raw = bytes.TrimSpace(raw)
	return len(raw) > 1 && raw[0] == '{'
}

func ParseInput(raw []byte) (Input, string, error) {
	var in Input
	if len(raw) > MaxBodyBytes || strictJSON(raw, &in) != nil || !validID(in.RequestID) || in.Capability != "shortpost" || in.PayloadSchema != "shortpost.input.v1" || !object(in.OpaquePayload) || len(in.OpaquePayload) > MaxPayloadBytes {
		return Input{}, "", ErrInvalid
	}
	var v any
	d := json.NewDecoder(bytes.NewReader(in.OpaquePayload))
	d.UseNumber()
	if err := d.Decode(&v); err != nil {
		return Input{}, "", ErrInvalid
	}
	canonical, err := json.Marshal(v)
	if err != nil {
		return Input{}, "", ErrInvalid
	}
	fingerprintInput := in
	fingerprintInput.OpaquePayload = canonical
	b, err := json.Marshal(fingerprintInput)
	if err != nil {
		return Input{}, "", ErrInvalid
	}
	sum := sha256.Sum256(b)
	return in, hex.EncodeToString(sum[:]), nil
}

func marshalFrame(v any) ([]byte, error) {
	var b bytes.Buffer
	e := json.NewEncoder(&b)
	e.SetEscapeHTML(false)
	if err := e.Encode(v); err != nil {
		return nil, err
	}
	return bytes.TrimSuffix(b.Bytes(), []byte{'\n'}), nil
}

func validProfile(p Profile) error {
	if p.ModelRef == "" || len(p.ModelRef) > 256 || p.TimeoutSeconds < 1 || p.TimeoutSeconds > 900 || len(p.ResourceVersions) > 32 {
		return fmt.Errorf("invalid execution profile")
	}
	for k, v := range p.ResourceVersions {
		if k == "" || len(k) > 128 || v == "" || len(v) > 256 || !utf8.ValidString(k) || !utf8.ValidString(v) {
			return fmt.Errorf("invalid resource version")
		}
	}
	// Reserve the maximum opaque input and fixed identity/deadline fields before
	// admitting configuration. Byte lengths alone do not bound JSON escaping.
	ex := Execute{Version: 1, Type: "execute", JobID: strings.Repeat("0", 36), ExecutionID: strings.Repeat("0", 36), OwnerEpoch: strings.Repeat("0", 36), Capability: "shortpost", PayloadSchema: "shortpost.input.v1", OpaquePayload: json.RawMessage(`{}`), ModelRef: p.ModelRef, ResourceVersions: p.ResourceVersions, DeadlineAt: strings.Repeat("0", 35)}
	b, err := marshalFrame(ex)
	if err != nil || len(b)+MaxPayloadBytes-2+1 > MaxFrameBytes {
		return fmt.Errorf("execution profile exceeds frame budget")
	}
	return nil
}
