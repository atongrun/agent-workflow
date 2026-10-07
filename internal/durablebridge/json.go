package durablebridge

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"math"
	"reflect"
	"sort"
	"strconv"
	"strings"
	"unicode/utf16"
	"unicode/utf8"
)

var ErrInvalid = errors.New("invalid Durable adapter input")
var ErrUnavailable = errors.New("Durable worker unavailable")

// Check JSON before typed decoding so duplicate keys and invalid UTF-8 cannot
// produce different authorization/fingerprint interpretations in Go and Node.
func strictJSON(data []byte, target any) error {
	if !utf8.Valid(data) || !validSurrogates(data) {
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
	// Optional native numeric IDs may be omitted, but never explicitly null.
	if value == nil && t.Kind() == reflect.Pointer && t.Elem().Kind() == reflect.Uint64 {
		return false
	}
	for t.Kind() == reflect.Pointer {
		t = t.Elem()
	}
	if t == reflect.TypeOf(json.RawMessage{}) || t.Kind() == reflect.Interface || t.Kind() == reflect.Map {
		return true
	}
	switch t.Kind() {
	case reflect.String:
		_, ok := value.(string)
		return ok
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
	encoded, err := json.Marshal(value)
	if err != nil {
		return nil, err
	}
	var decoded any
	d := json.NewDecoder(bytes.NewReader(encoded))
	d.UseNumber()
	if err := d.Decode(&decoded); err != nil {
		return nil, err
	}
	return canonicalJSON(decoded)
}

func jsonValue(d *json.Decoder, depth int) error {
	t, err := d.Token()
	if err != nil {
		return err
	}
	delim, ok := t.(json.Delim)
	if !ok {
		if number, ok := t.(json.Number); ok {
			if _, err := jsNumber(number); err != nil {
				return err
			}
		}
		return nil
	}
	// PRIVATE starts the root at zero and applies the limit to containers.
	// A scalar leaf at depth 32 is valid; a container at depth 32 is not.
	if depth >= 32 {
		return ErrInvalid
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

// Validate escapes before encoding/json can replace isolated UTF-16 surrogates.
func validSurrogates(data []byte) bool {
	inString := false
	for i := 0; i < len(data); i++ {
		if data[i] == '"' {
			inString = !inString
			continue
		}
		if !inString || data[i] != '\\' {
			continue
		}
		i++
		if i >= len(data) {
			return false
		}
		if data[i] != 'u' {
			continue
		}
		if i+4 >= len(data) {
			return false
		}
		code, err := strconv.ParseUint(string(data[i+1:i+5]), 16, 16)
		if err != nil {
			return false
		}
		i += 4
		if code >= 0xdc00 && code <= 0xdfff {
			return false
		}
		if code < 0xd800 || code > 0xdbff {
			continue
		}
		if i+6 >= len(data) || data[i+1] != '\\' || data[i+2] != 'u' {
			return false
		}
		low, err := strconv.ParseUint(string(data[i+3:i+7]), 16, 16)
		if err != nil || low < 0xdc00 || low > 0xdfff {
			return false
		}
		i += 6
	}
	return true
}

func jsNumber(number json.Number) (string, error) {
	n, err := number.Float64()
	if err != nil || math.IsNaN(n) || math.IsInf(n, 0) || (math.Trunc(n) == n && math.Abs(n) > float64(MaxNativeID)) {
		return "", ErrInvalid
	}
	if n == 0 {
		return "0", nil
	}
	if math.Abs(n) >= 1e-6 {
		return strconv.FormatFloat(n, 'f', -1, 64), nil
	}
	text := strconv.FormatFloat(n, 'e', -1, 64)
	parts := strings.Split(text, "e")
	exponent, _ := strconv.Atoi(parts[1])
	return parts[0] + "e" + strconv.Itoa(exponent), nil
}

// Canonical JSON uses recursively sorted keys and JSON.stringify scalar rules.
// This encoder writes real U+2028/U+2029 and never rewrites literal backslashes.
func canonicalJSON(value any) ([]byte, error) {
	var out bytes.Buffer
	var write func(any) error
	writeString := func(value string) error {
		if !utf8.ValidString(value) {
			return ErrInvalid
		}
		out.WriteByte('"')
		for _, r := range value {
			switch r {
			case '"', '\\':
				out.WriteByte('\\')
				out.WriteRune(r)
			case '\b':
				out.WriteString(`\b`)
			case '\f':
				out.WriteString(`\f`)
			case '\n':
				out.WriteString(`\n`)
			case '\r':
				out.WriteString(`\r`)
			case '\t':
				out.WriteString(`\t`)
			default:
				if r < 0x20 {
					out.WriteString(`\u00`)
					out.WriteByte("0123456789abcdef"[r>>4])
					out.WriteByte("0123456789abcdef"[r&15])
				} else {
					out.WriteRune(r)
				}
			}
		}
		out.WriteByte('"')
		return nil
	}
	write = func(v any) error {
		switch v := v.(type) {
		case nil:
			out.WriteString("null")
		case bool:
			out.WriteString(strconv.FormatBool(v))
		case json.Number:
			number, err := jsNumber(v)
			if err != nil {
				return err
			}
			out.WriteString(number)
		case string:
			return writeString(v)
		case []any:
			out.WriteByte('[')
			for i, item := range v {
				if i > 0 {
					out.WriteByte(',')
				}
				if err := write(item); err != nil {
					return err
				}
			}
			out.WriteByte(']')
		case map[string]any:
			keys := make([]string, 0, len(v))
			for key := range v {
				keys = append(keys, key)
			}
			// JavaScript sorts UTF-16 code units, rather than UTF-8/rune order.
			sort.Slice(keys, func(i, j int) bool { return utf16Less(keys[i], keys[j]) })
			out.WriteByte('{')
			for i, key := range keys {
				if i > 0 {
					out.WriteByte(',')
				}
				if err := writeString(key); err != nil {
					return err
				}
				out.WriteByte(':')
				if err := write(v[key]); err != nil {
					return err
				}
			}
			out.WriteByte('}')
		default:
			return ErrInvalid
		}
		return nil
	}
	if err := write(value); err != nil {
		return nil, err
	}
	return out.Bytes(), nil
}

func utf16Less(a, b string) bool {
	aa, bb := utf16.Encode([]rune(a)), utf16.Encode([]rune(b))
	for i := 0; i < len(aa) && i < len(bb); i++ {
		if aa[i] != bb[i] {
			return aa[i] < bb[i]
		}
	}
	return len(aa) < len(bb)
}
