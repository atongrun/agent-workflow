package lifecycle

import (
	encodingbinary "encoding/binary"
	"fmt"
	"io"
	"strings"
)

// Only descriptor metadata is retained. Never copy callback/resource payloads,
// credential bytes, or account names into a diagnostic report.
type doctorACLMetadata struct {
	OwnerSID       string      `json:"ownerSID,omitempty"`
	CurrentUserSID string      `json:"currentUserSID,omitempty"`
	DACLState      string      `json:"daclState"`
	Control        string      `json:"control,omitempty"`
	Protected      *bool       `json:"protected,omitempty"`
	Defaulted      *bool       `json:"defaulted,omitempty"`
	Revision       *uint8      `json:"revision,omitempty"`
	ACECount       *uint16     `json:"aceCount,omitempty"`
	Entries        []doctorACE `json:"entries"`
	Complete       bool        `json:"complete"`
	Issues         []string    `json:"issues,omitempty"`
	PolicyIssues   []string    `json:"policyIssues,omitempty"`
}
type doctorACE struct {
	Index     int      `json:"index"`
	Size      uint16   `json:"size"`
	Type      uint8    `json:"type"`
	TypeName  string   `json:"typeName"`
	Flags     uint8    `json:"flags"`
	FlagNames []string `json:"flagNames"`
	Mask      string   `json:"mask,omitempty"`
	SID       string   `json:"sid,omitempty"`
	Issues    []string `json:"issues,omitempty"`
}

var doctorACETypes = []string{"ALLOW", "DENY", "AUDIT", "ALARM", "COMPOUND_RESERVED", "ALLOW_OBJECT", "DENY_OBJECT", "AUDIT_OBJECT", "ALARM_OBJECT", "ALLOW_CALLBACK", "DENY_CALLBACK", "ALLOW_CALLBACK_OBJECT", "DENY_CALLBACK_OBJECT", "AUDIT_CALLBACK", "ALARM_CALLBACK", "AUDIT_CALLBACK_OBJECT", "ALARM_CALLBACK_OBJECT", "MANDATORY_LABEL", "RESOURCE_ATTRIBUTE", "SCOPED_POLICY_ID", "PROCESS_TRUST_LABEL", "ACCESS_FILTER"}

func decodeDoctorACL(raw []byte, m *doctorACLMetadata) {
	m.Entries = []doctorACE{}
	bad := func(reason string) { m.Complete = false; m.Issues = append(m.Issues, reason) }
	if len(raw) < 8 || len(raw) > 65535 {
		bad("invalid ACL byte length")
		return
	}
	revision := raw[0]
	m.Revision = &revision
	if revision != 2 && revision != 4 {
		bad("unknown ACL revision")
	}
	size := int(encodingbinary.LittleEndian.Uint16(raw[2:4]))
	count := encodingbinary.LittleEndian.Uint16(raw[4:6])
	m.ACECount = &count
	if size < 8 || size > len(raw) {
		bad("ACL size exceeds available bytes")
		return
	}
	raw = raw[:size]
	if int(count) > (size-8)/4 {
		bad("declared ACE count cannot fit in ACL")
	}
	offset := 8
	for i := 0; i < int(count); i++ {
		if offset > len(raw)-4 {
			bad(fmt.Sprintf("ACE %d header exceeds ACL; remaining entries unknown", i))
			return
		}
		n := int(encodingbinary.LittleEndian.Uint16(raw[offset+2 : offset+4]))
		if n < 4 || n%4 != 0 || n > len(raw)-offset {
			bad(fmt.Sprintf("ACE %d type=%d flags=0x%02x size=%d has invalid bounds; remaining entries unknown", i, raw[offset], raw[offset+1], n))
			return
		}
		ace := decodeDoctorACE(i, raw[offset:offset+n])
		switch ace.Type {
		case 5, 6, 7, 8, 11, 12, 15, 16:
			if revision != 4 {
				bad(fmt.Sprintf("ACE %d object layout requires ACL revision 4", i))
			}
		}
		m.Entries = append(m.Entries, ace)
		if len(ace.Issues) > 0 {
			m.Complete = false
		}
		offset += n
	}
}
func decodeDoctorACE(index int, b []byte) doctorACE {
	e := doctorACE{Index: index, Type: b[0], Flags: b[1], Size: encodingbinary.LittleEndian.Uint16(b[2:4]), FlagNames: []string{}}
	if int(e.Type) < len(doctorACETypes) {
		e.TypeName = doctorACETypes[e.Type]
	} else {
		e.TypeName = "UNKNOWN"
	}
	for _, f := range []struct {
		bit  byte
		name string
	}{{1, "OBJECT_INHERIT"}, {2, "CONTAINER_INHERIT"}, {4, "NO_PROPAGATE"}, {8, "INHERIT_ONLY"}, {16, "INHERITED"}} {
		if e.Flags&f.bit != 0 {
			e.FlagNames = append(e.FlagNames, f.name)
		}
	}
	// The high flag bits have ACE-type-specific meanings (Windows SDK winnt.h).
	allowed := e.Type == 0 || e.Type == 5 || e.Type == 9 || e.Type == 11
	audit := e.Type == 2 || e.Type == 3 || e.Type == 7 || e.Type == 8 || e.Type == 13 || e.Type == 14 || e.Type == 15 || e.Type == 16
	for _, bit := range []byte{32, 64, 128} {
		if e.Flags&bit == 0 {
			continue
		}
		name := fmt.Sprintf("TYPE_SPECIFIC_0x%02x", bit)
		switch {
		case bit == 32 && allowed:
			name = "CRITICAL"
		case bit == 64 && audit:
			name = "SUCCESSFUL_ACCESS"
		case bit == 128 && audit:
			name = "FAILED_ACCESS"
		case bit == 64 && e.Type == 21:
			name = "TRUST_PROTECTED_FILTER"
		}
		e.FlagNames = append(e.FlagNames, name)
	}
	// Reserved/unknown layouts have no guessed mask or SID offsets.
	if e.Type == 4 || int(e.Type) >= len(doctorACETypes) {
		e.Issues = append(e.Issues, "unsupported ACE layout; mask and SID unknown")
		return e
	}
	if len(b) < 8 {
		e.Issues = append(e.Issues, "ACE mask is truncated")
		return e
	}
	e.Mask = fmt.Sprintf("0x%08x", encodingbinary.LittleEndian.Uint32(b[4:8]))
	sidOffset := 8
	switch e.Type {
	case 5, 6, 7, 8, 11, 12, 15, 16:
		if len(b) < 12 {
			e.Issues = append(e.Issues, "object ACE flags are truncated")
			return e
		}
		flags := encodingbinary.LittleEndian.Uint32(b[8:12])
		if flags&^uint32(3) != 0 {
			e.Issues = append(e.Issues, "unknown object ACE flags; SID offset unknown")
			return e
		}
		sidOffset = 12
		if flags&1 != 0 {
			sidOffset += 16
		}
		if flags&2 != 0 {
			sidOffset += 16
		}
	}
	if sidOffset > len(b) {
		e.Issues = append(e.Issues, "object ACE identifiers are truncated")
		return e
	}
	var err error
	e.SID, err = decodeDoctorSID(b[sidOffset:])
	if err != nil {
		e.Issues = append(e.Issues, err.Error())
	}
	return e
}
func decodeDoctorSID(b []byte) (string, error) {
	if len(b) < 8 || b[0] != 1 || b[1] > 15 {
		return "", fmt.Errorf("invalid or truncated SID header")
	}
	count := int(b[1])
	if len(b) < 8+4*count {
		return "", fmt.Errorf("SID subauthorities are truncated")
	}
	authority := uint64(0)
	for _, n := range b[2:8] {
		authority = (authority << 8) | uint64(n)
	}
	sid := fmt.Sprintf("S-1-%d", authority)
	if authority > 0xffffffff {
		sid = fmt.Sprintf("S-1-0x%012x", authority)
	}
	for i := 0; i < count; i++ {
		sid += fmt.Sprintf("-%d", encodingbinary.LittleEndian.Uint32(b[8+i*4:12+i*4]))
	}
	return sid, nil
}

// Private-data findings share the exact policy used by lifecycle validation.
func summarizeDoctorACL(m *doctorACLMetadata) (string, string) {
	m.PolicyIssues = permissionPolicyIssues(m, privatePermissionRole)
	if !m.Complete {
		return "unknown", "ACL metadata is incomplete; observed rules and policy issues follow"
	}
	if len(m.PolicyIssues) > 0 {
		return "mismatch", "ACL metadata observed; current-user/SYSTEM-only policy is not satisfied"
	}
	return "private", "ACL metadata observed; current-user/SYSTEM-only policy is satisfied"
}

// Program ACLs protect code integrity; only secret/state paths require privacy.
func summarizeDoctorACLRole(m *doctorACLMetadata, role permissionRole) (string, string) {
	if role == privatePermissionRole {
		return summarizeDoctorACL(m)
	}
	m.PolicyIssues = permissionPolicyIssues(m, role)
	if !m.Complete {
		return "unknown", "program ACL metadata is incomplete; observed rules follow"
	}
	if len(m.PolicyIssues) != 0 {
		return "mismatch", "program ACL permits unsafe modification or lacks current-user access"
	}
	return "protected", "program ACL permits user/SYSTEM/Administrators writes and inherited read-only access; no ACL was changed"
}

func renderDoctorACL(out io.Writer, m *doctorACLMetadata) {
	boolText := func(p *bool) string {
		if p == nil {
			return "unknown"
		}
		return fmt.Sprint(*p)
	}
	fmt.Fprintf(out, "  owner=%q currentUser=%q DACL=%s protected=%s defaulted=%s control=%s complete=%t\n", m.OwnerSID, m.CurrentUserSID, m.DACLState, boolText(m.Protected), boolText(m.Defaulted), m.Control, m.Complete)
	if m.ACECount != nil {
		fmt.Fprintf(out, "  ACE count=%d; observed=%d\n", *m.ACECount, len(m.Entries))
	}
	for _, e := range m.Entries {
		mask, sid := e.Mask, e.SID
		if mask == "" {
			mask = "unknown"
		}
		if sid == "" {
			sid = "unknown"
		}
		fmt.Fprintf(out, "  ACE[%d] type=%s(%d) size=%d mask=%s flags=0x%02x[%s] SID=%q\n", e.Index, e.TypeName, e.Type, e.Size, mask, e.Flags, strings.Join(e.FlagNames, ","), sid)
		for _, s := range e.Issues {
			fmt.Fprintf(out, "    unknown: %q\n", s)
		}
	}
	for _, s := range m.Issues {
		fmt.Fprintf(out, "  unknown: %q\n", s)
	}
	for _, s := range m.PolicyIssues {
		fmt.Fprintf(out, "  policy: %q\n", s)
	}
}
