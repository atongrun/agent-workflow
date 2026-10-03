package lifecycle

import (
	"bytes"
	encodingbinary "encoding/binary"
	"encoding/json"
	"strings"
	"testing"
)

func doctorSIDFixture(parts ...uint32) []byte {
	b := make([]byte, 8+4*len(parts))
	b[0] = 1
	b[1] = byte(len(parts))
	b[7] = 5
	for i, n := range parts {
		encodingbinary.LittleEndian.PutUint32(b[8+i*4:], n)
	}
	return b
}
func doctorACEFixture(kind, flags byte, mask uint32, sid []byte) []byte {
	b := make([]byte, 8+len(sid))
	b[0] = kind
	b[1] = flags
	encodingbinary.LittleEndian.PutUint16(b[2:4], uint16(len(b)))
	encodingbinary.LittleEndian.PutUint32(b[4:8], mask)
	copy(b[8:], sid)
	return b
}
func doctorACLFixture(entries ...[]byte) []byte {
	b := make([]byte, 8)
	b[0] = 2
	encodingbinary.LittleEndian.PutUint16(b[4:6], uint16(len(entries)))
	for _, e := range entries {
		b = append(b, e...)
	}
	encodingbinary.LittleEndian.PutUint16(b[2:4], uint16(len(b)))
	return b
}
func parsedDoctorACL(raw []byte) doctorACLMetadata {
	m := doctorACLMetadata{OwnerSID: "S-1-5-21-1001", CurrentUserSID: "S-1-5-21-1001", DACLState: "present", Complete: true}
	decodeDoctorACL(raw, &m)
	return m
}
func TestDoctorACLAggregatesEveryRuleAndIssue(t *testing.T) {
	own := doctorSIDFixture(21, 1001)
	system := doctorSIDFixture(18)
	admin := doctorSIDFixture(32, 544)
	sandbox := doctorSIDFixture(21, 1004)
	m := parsedDoctorACL(doctorACLFixture(doctorACEFixture(1, 0, 0x1200a9, sandbox), doctorACEFixture(0, 0x13, 0x1f01ff, admin), doctorACEFixture(0, 3, 0x1f01ff, own), doctorACEFixture(0, 3, 0x1f01ff, system)))
	status, _ := summarizeDoctorACL(&m)
	if status != "mismatch" || !m.Complete || len(m.Entries) != 4 || len(m.PolicyIssues) < 4 {
		t.Fatalf("incomplete aggregation: %+v", m)
	}
	if m.Entries[0].SID != "S-1-5-21-1004" || m.Entries[1].Mask != "0x001f01ff" || m.Entries[3].SID != "S-1-5-18" {
		t.Fatal(m)
	}
	if !strings.Contains(strings.Join(m.Entries[1].FlagNames, ","), "INHERITED") {
		t.Fatal("inheritance missing")
	}
	var out bytes.Buffer
	renderDoctorACL(&out, &m)
	for _, want := range []string{"ACE[0]", "ACE[1]", "ACE[2]", "ACE[3]", "S-1-5-32-544", "S-1-5-21-1004"} {
		if !strings.Contains(out.String(), want) {
			t.Fatal("missing human metadata", want)
		}
	}
}
func TestDoctorACLDoesNotTightenInheritedPolicy(t *testing.T) {
	m := parsedDoctorACL(doctorACLFixture(doctorACEFixture(0, 0x13, 0x1f01ff, doctorSIDFixture(21, 1001)), doctorACEFixture(0, 0x13, 0x10000000, doctorSIDFixture(18))))
	protected := false
	m.Protected = &protected
	if status, _ := summarizeDoctorACL(&m); status != "private" {
		t.Fatal(status, m)
	}
}
func TestDoctorACLUnknownEntriesPreserveLaterRules(t *testing.T) {
	unknown := []byte{255, 16, 4, 0}
	badSID := doctorACEFixture(0, 0, 0x1f01ff, []byte{1, 15, 0, 0, 0, 0, 0, 5})
	last := doctorACEFixture(0, 0, 0x1f01ff, doctorSIDFixture(18))
	m := parsedDoctorACL(doctorACLFixture(unknown, badSID, last))
	status, _ := summarizeDoctorACL(&m)
	if status != "unknown" || m.Complete || len(m.Entries) != 3 || m.Entries[2].SID != "S-1-5-18" {
		t.Fatal(m)
	}
	if m.Entries[0].Mask != "" || m.Entries[0].SID != "" {
		t.Fatal("guessed unknown layout")
	}
}
func TestDoctorACLStructuralBounds(t *testing.T) {
	valid := doctorACLFixture(doctorACEFixture(0, 0, 0x1f01ff, doctorSIDFixture(18)))
	cases := [][]byte{nil, {2, 0, 8}, append([]byte{}, valid...)}
	cases[2][10] = 0
	cases[2][11] = 0
	odd := append([]byte{}, valid...)
	odd[10] = 5
	cases = append(cases, odd)
	over := append([]byte{}, valid...)
	over[2] = 255
	cases = append(cases, over)
	for _, b := range cases {
		m := parsedDoctorACL(b)
		if m.Complete {
			t.Fatal("malformed ACL complete", b)
		}
	}
}
func TestDoctorACLObjectSIDOffsetsAndNoPayload(t *testing.T) {
	for flags := uint32(0); flags < 4; flags++ {
		offset := 12
		if flags&1 != 0 {
			offset += 16
		}
		if flags&2 != 0 {
			offset += 16
		}
		sid := doctorSIDFixture(18)
		e := make([]byte, offset+len(sid))
		e[0] = 5
		encodingbinary.LittleEndian.PutUint16(e[2:4], uint16(len(e)))
		encodingbinary.LittleEndian.PutUint32(e[4:8], 0x1f01ff)
		encodingbinary.LittleEndian.PutUint32(e[8:12], flags)
		copy(e[offset:], sid)
		raw := doctorACLFixture(e)
		raw[0] = 4
		m := parsedDoctorACL(raw)
		if !m.Complete || m.Entries[0].SID != "S-1-5-18" {
			t.Fatal(flags, m)
		}
	}
	e := doctorACEFixture(9, 0, 0x1f01ff, doctorSIDFixture(18))
	e = append(e, []byte("SECRET_CALLBACK_DATA")...)
	for len(e)%4 != 0 {
		e = append(e, 0)
	}
	encodingbinary.LittleEndian.PutUint16(e[2:4], uint16(len(e)))
	m := parsedDoctorACL(doctorACLFixture(e))
	b, _ := json.Marshal(m)
	if strings.Contains(string(b), "SECRET") {
		t.Fatal("opaque payload leaked")
	}
}
func TestDoctorACLAbsentNullEmptyAndUnknownOwner(t *testing.T) {
	for _, state := range []string{"absent", "null", "present"} {
		m := parsedDoctorACL(doctorACLFixture())
		m.DACLState = state
		status, _ := summarizeDoctorACL(&m)
		if status != "mismatch" {
			t.Fatal(state, m)
		}
	}
	m := parsedDoctorACL(doctorACLFixture(doctorACEFixture(0, 0, 0x1f01ff, doctorSIDFixture(18))))
	m.OwnerSID = ""
	m.CurrentUserSID = ""
	status, _ := summarizeDoctorACL(&m)
	if status != "unknown" || len(m.Entries) != 1 || m.Entries[0].SID != "S-1-5-18" {
		t.Fatal("identity failure lost ACL", m)
	}
}
func TestDoctorSIDAuthorityByteOrder(t *testing.T) {
	b := doctorSIDFixture(0x11223344)
	copy(b[2:8], []byte{1, 2, 3, 4, 5, 6})
	sid, err := decodeDoctorSID(b)
	if err != nil || sid != "S-1-0x010203040506-287454020" {
		t.Fatal(sid, err)
	}
}
func FuzzDoctorACLMetadata(f *testing.F) {
	f.Add(doctorACLFixture(doctorACEFixture(0, 0, 0x1f01ff, doctorSIDFixture(18))))
	f.Add([]byte{2, 0, 0, 0})
	f.Fuzz(func(t *testing.T, b []byte) {
		if len(b) > 65535 {
			return
		}
		m := parsedDoctorACL(b)
		summarizeDoctorACL(&m)
		var out bytes.Buffer
		renderDoctorACL(&out, &m)
	})
}

func TestDoctorACLTypeSpecificFlags(t *testing.T) {
	for _, tc := range []struct {
		kind, flags  byte
		want, absent string
	}{{21, 64, "TRUST_PROTECTED_FILTER", "SUCCESSFUL_ACCESS"}, {2, 192, "SUCCESSFUL_ACCESS,FAILED_ACCESS", "TRUST_PROTECTED_FILTER"}, {0, 32, "CRITICAL", "TYPE_SPECIFIC"}, {1, 32, "TYPE_SPECIFIC_0x20", "CRITICAL"}} {
		m := parsedDoctorACL(doctorACLFixture(doctorACEFixture(tc.kind, tc.flags, 0x1f01ff, doctorSIDFixture(18))))
		names := strings.Join(m.Entries[0].FlagNames, ",")
		if !strings.Contains(names, tc.want) || strings.Contains(names, tc.absent) {
			t.Fatal(tc, names)
		}
	}
}

func TestDoctorProgramAndPrivateRolesDiffer(t *testing.T) {
	m := parsedDoctorACL(doctorACLFixture(
		doctorACEFixture(0, 0x13, 0x1f01ff, doctorSIDFixture(21, 1001)),
		doctorACEFixture(0, 0x13, 0x1f01ff, doctorSIDFixture(18)),
		doctorACEFixture(0, 0x13, 0x1f01ff, doctorSIDFixture(32, 544)),
		doctorACEFixture(0, 0x13, 0x1200a9, doctorSIDFixture(32, 545))))
	if status, _ := summarizeDoctorACLRole(&m, programPermissionRole); status != "protected" {
		t.Fatal(status, m)
	}
	if status, _ := summarizeDoctorACLRole(&m, privatePermissionRole); status != "mismatch" {
		t.Fatal(status, m)
	}
}
