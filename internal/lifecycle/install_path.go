package lifecycle

import (
	encodingbinary "encoding/binary"
	"errors"
	"fmt"
	"strings"
	"unicode/utf16"
	"unicode/utf8"
)

const (
	installPathREGSZ       uint32 = 1
	installPathREGExpandSZ uint32 = 2
	// Include the terminating NUL in the Windows environment-string limit.
	maxInstallPathUnits = 32767
)

type installPathValue struct {
	text string
	kind uint32
}

// The narrow seam lets portable tests exercise ordering without touching a
// registry, the test process's environment, or another user's installation.
type installPathOps struct {
	readUser   func() (installPathValue, error)
	writeUser  func(before, after installPathValue) error
	lookupEnv  func(string) (string, bool)
	getProcess func() string
	setProcess func(string) error
	broadcast  func()
}

func registerInstallPathWith(bin string, ops installPathOps) error {
	wanted, err := canonicalInstallPathBin(bin)
	if err != nil {
		return err
	}
	old, err := ops.readUser()
	if err != nil {
		return fmt.Errorf("read user PATH: %w", err)
	}
	next, err := prepareInstallPathValue(old, wanted, ops.lookupEnv)
	if err != nil {
		return err
	}
	process := ops.getProcess()
	updated := moveInstallPathFirst(process, wanted, ops.lookupEnv)
	// Validate both outputs before changing persistent state.
	if _, err := encodeInstallPathValue(installPathValue{updated, installPathREGSZ}); err != nil {
		return fmt.Errorf("prepare process PATH: %w", err)
	}
	if next != old {
		if err := ops.writeUser(old, next); err != nil {
			return fmt.Errorf("write user PATH; process PATH was not changed: %w", err)
		}
		// A failed process update must not suppress notification of a successful
		// persistent update. Broadcasting is deliberately best-effort.
		defer ops.broadcast()
	}
	if updated != process {
		if err := ops.setProcess(updated); err != nil {
			return fmt.Errorf("user PATH is registered, but process PATH could not be updated: %w", err)
		}
	}
	return nil
}

// A true result means registration would change HKCU's Path value. Preview
// never inspects or updates process PATH and never opens a writable key.
func installPathPreviewWith(bin string, read func() (installPathValue, error), lookup func(string) (string, bool)) (bool, error) {
	wanted, err := canonicalInstallPathBin(bin)
	if err != nil {
		return false, err
	}
	old, err := read()
	if err != nil {
		return false, fmt.Errorf("read user PATH: %w", err)
	}
	next, err := prepareInstallPathValue(old, wanted, lookup)
	return next != old && err == nil, err
}

func prepareInstallPathValue(old installPathValue, wanted string, lookup func(string) (string, bool)) (installPathValue, error) {
	// Reject malformed existing strings rather than silently repairing unrelated
	// entries. In particular, never replace an unsupported registry value type.
	if _, err := encodeInstallPathValue(old); err != nil {
		return installPathValue{}, fmt.Errorf("read user PATH: %w", err)
	}
	next := installPathValue{moveInstallPathFirst(old.text, wanted, lookup), old.kind}
	if _, err := encodeInstallPathValue(next); err != nil {
		return installPathValue{}, fmt.Errorf("prepare user PATH: %w", err)
	}
	return next, nil
}

// Match scripts/install.ps1's Move-AwfPathEntryFirst: normalize only for
// comparison, and retain every unrelated entry verbatim, including empty,
// relative, quoted, malformed, and duplicate unrelated entries.
func moveInstallPathFirst(value, wanted string, lookup func(string) (string, bool)) string {
	if value == "" {
		return wanted
	}
	remaining := []string{wanted}
	for _, part := range strings.Split(value, ";") {
		entry := strings.TrimSpace(part)
		if len(entry) >= 2 && entry[0] == '"' && entry[len(entry)-1] == '"' {
			entry = entry[1 : len(entry)-1]
		}
		normalized, err := canonicalInstallPath(expandInstallPathEnv(entry, lookup))
		if err != nil || !strings.EqualFold(wanted, normalized) {
			remaining = append(remaining, part)
		}
	}
	return strings.Join(remaining, ";")
}

// Windows expands percent-delimited variables once and leaves unknown names
// untouched. The native lookup is os.LookupEnv, which is case-insensitive on
// Windows; tests supply their own lookup instead of using the host environment.
func expandInstallPathEnv(value string, lookup func(string) (string, bool)) string {
	var result strings.Builder
	for {
		start := strings.IndexByte(value, '%')
		if start < 0 {
			result.WriteString(value)
			return result.String()
		}
		end := strings.IndexByte(value[start+1:], '%')
		if end < 0 {
			result.WriteString(value)
			return result.String()
		}
		end += start + 1
		result.WriteString(value[:start])
		if replacement, ok := lookup(value[start+1 : end]); ok {
			result.WriteString(replacement)
		} else {
			result.WriteString(value[start : end+1])
		}
		value = value[end+1:]
	}
}

func canonicalInstallPathBin(bin string) (string, error) {
	if strings.ContainsRune(bin, ';') {
		return "", errors.New("AWF bin path cannot contain a PATH separator")
	}
	// Percent signs are valid in Windows filenames, but inserting them into a
	// REG_EXPAND_SZ value can redirect the entry when a future process expands
	// environment variables. There is no safe universal percent escape for PATH.
	// This restriction applies only to registration, not --no-path installation.
	if strings.ContainsRune(bin, '%') {
		return "", errors.New("AWF bin path contains '%' and cannot be registered safely in Windows PATH")
	}
	wanted, err := canonicalInstallPath(bin)
	if err != nil {
		return "", fmt.Errorf("invalid AWF bin path: %w", err)
	}
	return wanted, nil
}

// Pure lexical normalization, independent of the host OS and filesystem. Do
// not resolve short names or links, which could hide a different installation.
func canonicalInstallPath(value string) (string, error) {
	if strings.TrimSpace(value) == "" || !utf8.ValidString(value) {
		return "", errors.New("empty or invalid Windows path")
	}
	value = strings.ReplaceAll(value, "/", `\`)
	if len(value) >= 8 && strings.EqualFold(value[:8], `\\?\UNC\`) {
		value = `\\` + value[8:]
	} else {
		value = strings.TrimPrefix(value, `\\?\`)
	}
	drive := len(value) >= 3 && ((value[0] >= 'A' && value[0] <= 'Z') || (value[0] >= 'a' && value[0] <= 'z')) && value[1:3] == `:\`
	var root string
	var parts, validate []string
	if drive {
		root, parts = value[:3], strings.Split(value[3:], `\`)
		validate = parts
	} else {
		if !strings.HasPrefix(value, `\\`) {
			return "", errors.New("path must be an absolute Windows drive or UNC path")
		}
		unc := strings.Split(value[2:], `\`)
		if len(unc) < 2 || unc[0] == "" || unc[1] == "" || unc[0] == "." || unc[0] == ".." || unc[1] == "." || unc[1] == ".." {
			return "", errors.New("UNC path must name a server and share")
		}
		root, parts, validate = `\\`+unc[0]+`\`+unc[1]+`\`, unc[2:], unc
	}
	for _, part := range validate {
		if part == "" || part == "." || part == ".." {
			continue
		}
		if strings.HasSuffix(part, ".") || strings.HasSuffix(part, " ") || strings.ContainsAny(part, `\"<>|:*?`) || strings.ContainsFunc(part, func(r rune) bool { return r < 32 }) {
			return "", errors.New("path contains an ambiguous Windows component")
		}
	}
	segments := make([]string, 0, len(parts))
	for _, part := range parts {
		switch part {
		case "", ".":
		case "..":
			if len(segments) != 0 {
				segments = segments[:len(segments)-1]
			}
		default:
			segments = append(segments, part)
		}
	}
	full := root + strings.Join(segments, `\`)
	if drive && len(segments) == 0 {
		return full, nil
	}
	return strings.TrimRight(full, `\`), nil
}

func encodeInstallPathValue(value installPathValue) ([]byte, error) {
	if value.kind != installPathREGSZ && value.kind != installPathREGExpandSZ {
		return nil, errors.New("user PATH must have registry type REG_SZ or REG_EXPAND_SZ")
	}
	if !utf8.ValidString(value.text) || strings.ContainsRune(value.text, 0) {
		return nil, errors.New("PATH contains invalid text or an embedded NUL")
	}
	units := utf16.Encode([]rune(value.text))
	if len(units) >= maxInstallPathUnits {
		return nil, errors.New("PATH exceeds the Windows environment-string limit")
	}
	data := make([]byte, (len(units)+1)*2)
	for i, unit := range units {
		encodingbinary.LittleEndian.PutUint16(data[i*2:], unit)
	}
	return data, nil
}

func decodeInstallPathValue(kind uint32, data []byte) (installPathValue, error) {
	if len(data)%2 != 0 || len(data) > maxInstallPathUnits*2 {
		return installPathValue{}, errors.New("user PATH has an invalid UTF-16 size")
	}
	units := make([]uint16, len(data)/2)
	for i := range units {
		units[i] = encodingbinary.LittleEndian.Uint16(data[i*2:])
	}
	// RegQueryValueExW does not guarantee that stored strings are terminated.
	if len(units) > 0 && units[len(units)-1] == 0 {
		units = units[:len(units)-1]
	}
	for i := 0; i < len(units); i++ {
		unit := units[i]
		if unit >= 0xd800 && unit <= 0xdbff {
			if i+1 >= len(units) || units[i+1] < 0xdc00 || units[i+1] > 0xdfff {
				return installPathValue{}, errors.New("user PATH has invalid UTF-16 text")
			}
			i++
		} else if unit >= 0xdc00 && unit <= 0xdfff {
			return installPathValue{}, errors.New("user PATH has invalid UTF-16 text")
		}
	}
	value := installPathValue{string(utf16.Decode(units)), kind}
	if _, err := encodeInstallPathValue(value); err != nil {
		return installPathValue{}, err
	}
	return value, nil
}
