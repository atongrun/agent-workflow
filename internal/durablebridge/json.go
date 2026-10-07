package durablebridge

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"reflect"
	"strings"
	"unicode/utf8"
)

var ErrInvalid = errors.New("invalid Durable adapter input")
var ErrUnavailable = errors.New("Durable worker unavailable")

// Check JSON before typed decoding so duplicate keys and invalid UTF-8 cannot
// produce different authorization/fingerprint interpretations in Go and Node.
func strictJSON(data []byte, target any) error {
	if !utf8.Valid(data) {
		return ErrInvalid
	}
	d := json.NewDecoder(bytes.NewReader(data))
	d.UseNumber()
	if err := jsonValue(d, 0); err != nil {
		return ErrInvalid
	}
	if _, err := d.Token(); err != io.EOF {
		return ErrInvalid
	}
	d = json.NewDecoder(bytes.NewReader(data))
	d.UseNumber()
	var shape any
	if d.Decode(&shape) != nil || !literalFields(shape, reflect.TypeOf(target)) {
		return ErrInvalid
	}
	d = json.NewDecoder(bytes.NewReader(data))
	d.DisallowUnknownFields()
	d.UseNumber()
	if err := d.Decode(target); err != nil {
		return ErrInvalid
	}
	return nil
}

// Go's decoder accepts case-insensitive aliases. Wire fields instead use exact
// JSON tags, including embedded summary fields; opaque JSON stays opaque.
func literalFields(value any, t reflect.Type) bool {
	for t.Kind() == reflect.Pointer {
		t = t.Elem()
	}
	if t == reflect.TypeOf(json.RawMessage{}) || t.Kind() == reflect.Interface || t.Kind() == reflect.Map {
		return true
	}
	switch t.Kind() {
	case reflect.Struct:
		object, ok := value.(map[string]any)
		if !ok {
			return value == nil
		}
		fields := taggedFields(t)
		for key, v := range object {
			child, ok := fields[key]
			if !ok || !literalFields(v, child) {
				return false
			}
		}
	case reflect.Slice, reflect.Array:
		if values, ok := value.([]any); ok {
			for _, v := range values {
				if !literalFields(v, t.Elem()) {
					return false
				}
			}
		}
	}
	return true
}

func taggedFields(t reflect.Type) map[string]reflect.Type {
	fields := map[string]reflect.Type{}
	for i := 0; i < t.NumField(); i++ {
		field := t.Field(i)
		if field.PkgPath != "" {
			continue
		}
		name := strings.Split(field.Tag.Get("json"), ",")[0]
		if name == "-" {
			continue
		}
		if field.Anonymous && name == "" {
			child := field.Type
			for child.Kind() == reflect.Pointer {
				child = child.Elem()
			}
			if child.Kind() == reflect.Struct {
				for k, v := range taggedFields(child) {
					fields[k] = v
				}
				continue
			}
		}
		if name == "" {
			name = field.Name
		}
		fields[name] = field.Type
	}
	return fields
}

func marshalFrame(value any) ([]byte, error) {
	var b bytes.Buffer
	e := json.NewEncoder(&b)
	e.SetEscapeHTML(false)
	if err := e.Encode(value); err != nil {
		return nil, err
	}
	return bytes.TrimSuffix(b.Bytes(), []byte{'\n'}), nil
}

func jsonValue(d *json.Decoder, depth int) error {
	if depth > 32 {
		return ErrInvalid
	}
	t, err := d.Token()
	if err != nil {
		return err
	}
	delim, ok := t.(json.Delim)
	if !ok {
		return nil
	}
	switch delim {
	case '{':
		seen := map[string]bool{}
		for d.More() {
			key, err := d.Token()
			if err != nil {
				return err
			}
			k, ok := key.(string)
			if !ok || seen[k] {
				return ErrInvalid
			}
			seen[k] = true
			if err := jsonValue(d, depth+1); err != nil {
				return err
			}
		}
	case '[':
		for d.More() {
			if err := jsonValue(d, depth+1); err != nil {
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
