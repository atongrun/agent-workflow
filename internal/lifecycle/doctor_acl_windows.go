package lifecycle

import (
	"fmt"
	"syscall"
	"unsafe"
)

func inspectDoctorACL(path string) doctorACLMetadata {
	m := doctorACLMetadata{DACLState: "unknown", Entries: []doctorACE{}, Complete: true}
	fail := func(reason string) { m.Complete = false; m.Issues = append(m.Issues, reason) }
	// TOKEN_QUERY only. Do not invoke os/user.Current: it also resolves account
	// names/profiles and may temporarily alter thread impersonation in Go 1.27.
	if token, err := syscall.OpenCurrentProcessToken(); err != nil {
		fail("current process SID query unavailable")
	} else {
		if user, err := token.GetTokenUser(); err != nil {
			fail("current process SID query unavailable")
		} else if sid, err := user.User.Sid.String(); err != nil {
			fail("current process SID conversion failed")
		} else {
			m.CurrentUserSID = sid
		}
		token.Close()
	}
	p, err := syscall.UTF16PtrFromString(path)
	if err != nil {
		fail("path cannot be queried")
		return m
	}
	var sd, dacl unsafe.Pointer
	var owner *syscall.SID
	api := syscall.NewLazyDLL("advapi32.dll")
	status, _, _ := api.NewProc("GetNamedSecurityInfoW").Call(uintptr(unsafe.Pointer(p)), 1, 5, uintptr(unsafe.Pointer(&owner)), 0, uintptr(unsafe.Pointer(&dacl)), 0, uintptr(unsafe.Pointer(&sd)))
	if status != 0 {
		fail(fmt.Sprintf("security descriptor query returned Windows error %d", status))
		return m
	}
	if sd == nil {
		fail("security descriptor query returned no descriptor")
		return m
	}
	defer syscall.LocalFree(syscall.Handle(uintptr(sd)))
	if owner == nil {
		fail("owner SID absent")
	} else if sid, err := owner.String(); err != nil {
		fail("owner SID conversion failed")
	} else {
		m.OwnerSID = sid
	}
	var control uint16
	var revision uint32
	ok, _, _ := api.NewProc("GetSecurityDescriptorControl").Call(uintptr(sd), uintptr(unsafe.Pointer(&control)), uintptr(unsafe.Pointer(&revision)))
	controlKnown := ok != 0
	if !controlKnown {
		fail("security descriptor control query failed")
	} else {
		protected := control&0x1000 != 0
		m.Protected = &protected
		m.Control = fmt.Sprintf("0x%04x", control)
	}
	var present, defaulted int32
	ok, _, _ = api.NewProc("GetSecurityDescriptorDacl").Call(uintptr(sd), uintptr(unsafe.Pointer(&present)), uintptr(unsafe.Pointer(&dacl)), uintptr(unsafe.Pointer(&defaulted)))
	if ok == 0 {
		fail("DACL presence query failed")
		return m
	}
	if present == 0 {
		m.DACLState = "absent"
		return m
	}
	d := defaulted != 0
	m.Defaulted = &d
	if dacl == nil {
		m.DACLState = "null"
		return m
	}
	m.DACLState = "present"
	// GetNamedSecurityInfo returns one allocated self-relative descriptor. Bound
	// the ACL region against that allocation before copying any native bytes.
	length, _, _ := api.NewProc("GetSecurityDescriptorLength").Call(uintptr(sd))
	if length < 20 || length > 1<<20 || uintptr(dacl) < uintptr(sd) || uintptr(dacl)-uintptr(sd) > length-8 {
		fail("DACL allocation bounds unavailable")
		return m
	}
	// Validate self-relative storage independently even if the control API
	// failed, so that failure does not erase otherwise readable ACE metadata.
	if *(*uint16)(unsafe.Add(sd, 2))&0x8000 == 0 {
		fail("descriptor storage is not self-relative")
		return m
	}
	size := uintptr(*(*uint16)(unsafe.Add(dacl, 2)))
	if size < 8 || size > 65535 || size > length-(uintptr(dacl)-uintptr(sd)) {
		fail("DACL exceeds descriptor bounds")
		return m
	}
	raw := append([]byte(nil), unsafe.Slice((*byte)(dacl), int(size))...)
	decodeDoctorACL(raw, &m)
	return m
}
