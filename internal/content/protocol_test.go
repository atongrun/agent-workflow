package content

import (
	"bytes"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"strings"
	"testing"
)

const fixtureID = "00000000-0000-4000-8000-000000000001"

func fixtureExecute() Execute {
	return Execute{Version: 1, Type: "execute", JobID: fixtureID, ExecutionID: "00000000-0000-4000-8000-000000000002", OwnerEpoch: "00000000-0000-4000-8000-000000000003", Capability: "shortpost", PayloadSchema: "shortpost.input.v1", OpaquePayload: json.RawMessage(`{"example":"fixture"}`), ModelRef: "fixture", ResourceVersions: map[string]string{"shortpost": "fixture"}}
}
func artifactFor(raw []byte) Artifact {
	sum := sha256.Sum256(raw)
	return Artifact{Schema: "shortpost.result.v1", MediaType: "application/json", Bytes: len(raw), SHA256: hex.EncodeToString(sum[:]), DataBase64: base64.StdEncoding.EncodeToString(raw)}
}
func frame(ex Execute, seq int64, kind string) Event {
	return Event{Version: 1, JobID: ex.JobID, ExecutionID: ex.ExecutionID, OwnerEpoch: ex.OwnerEpoch, Sequence: seq, Type: kind}
}
func encodeEvent(t *testing.T, e Event) []byte {
	t.Helper()
	b, err := json.Marshal(e)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

func TestInputIdentityAndBounds(t *testing.T) {
	first := `{"requestId":"` + fixtureID + `","capability":"shortpost","payloadSchema":"shortpost.input.v1","opaquePayload":{"b":2,"a":1}}`
	second := `{ "opaquePayload" : {"a":1,"b":2},"payloadSchema":"shortpost.input.v1","requestId":"` + fixtureID + `","capability":"shortpost" }`
	_, h, err := ParseInput([]byte(first))
	if err != nil {
		t.Fatal(err)
	}
	_, h2, err := ParseInput([]byte(second))
	if err != nil || h != h2 {
		t.Fatalf("normalization: %v %s %s", err, h, h2)
	}
	_, h3, err := ParseInput([]byte(strings.Replace(first, `"a":1`, `"a":1.0`, 1)))
	if err != nil || h == h3 {
		t.Fatal("number spelling must remain significant")
	}
	bad := []string{
		strings.Replace(first, `"requestId"`, `"REQUESTID"`, 1),
		strings.Replace(first, `"capability"`, `"CAPABILITY"`, 1),
		strings.Replace(first, `"capability":"shortpost"`, `"requestId":"`+newID()+`","REQUESTID":"`+fixtureID+`","capability":"shortpost"`, 1),
		strings.Replace(first, `"b":2`, `"b":2,"b":3`, 1),
		strings.Replace(first, `"b":2`, `"b":2,"\u0062":3`, 1),
		strings.Replace(first, `"capability":"shortpost"`, `"owner":"fixture-owner","capability":"shortpost"`, 1),
		strings.Replace(first, fixtureID, strings.ToUpper(fixtureID[:19])+"A"+fixtureID[20:], 1),
		strings.Replace(first, fixtureID, "00000000-0000-1000-8000-000000000001", 1),
		strings.Replace(first, `{"b":2,"a":1}`, `null`, 1),
		strings.Replace(first, `{"b":2,"a":1}`, `[]`, 1), first + `{}`,
		strings.Replace(first, `{"b":2,"a":1}`, `{"x":"`+strings.Repeat("x", MaxPayloadBytes)+`"}`, 1),
		strings.Replace(first, `{"b":2,"a":1}`, `{"x":`+strings.Repeat("[", MaxJSONDepth)+"0"+strings.Repeat("]", MaxJSONDepth)+`}`, 1),
	}
	for i, raw := range bad {
		if _, _, err := ParseInput([]byte(raw)); err == nil {
			t.Fatalf("bad input %d accepted", i)
		}
	}
	invalid := []byte(first)
	invalid[10] = 0xff
	if _, _, err := ParseInput(invalid); err == nil {
		t.Fatal("invalid UTF-8 accepted")
	}
}

func TestCredentialCompositionScopes(t *testing.T) {
	host := strings.Repeat("h", 24)
	extension := strings.Repeat("e", 24)
	for _, token := range []string{host, extension} {
		if ValidateCredentialIsolation([]Credential{{Token: token, Owner: "fixture"}}, host, extension) == nil {
			t.Fatal("credential crossed content/Host scope")
		}
	}
	if ValidateCredentialIsolation([]Credential{{Token: strings.Repeat("c", 24), Owner: "fixture"}}, host, extension) != nil {
		t.Fatal("distinct content credential rejected")
	}
}

func TestArtifactExactBytes(t *testing.T) {
	raw := []byte("{\n \"example\": \"fixture\", \"unicode\": \"🙂\"\n}")
	a := artifactFor(raw)
	b, err := VerifyArtifact(a)
	if err != nil || !bytes.Equal(b, raw) {
		t.Fatalf("exact bytes lost: %v", err)
	}
	canonical := artifactFor([]byte(`{"example":"fixture","unicode":"🙂"}`))
	if canonical.SHA256 == a.SHA256 {
		t.Fatal("re-serialization must not define artifact SHA")
	}
	cases := []Artifact{a, a, a, a, a, a}
	cases[0].SHA256 = strings.Repeat("0", 64)
	cases[1].Bytes++
	cases[2].DataBase64 = "e3\n0="
	cases[3].Schema = "other"
	cases[4] = artifactFor([]byte(`{"a":1,"a":2}`))
	cases[5] = artifactFor([]byte{'{', '"', 'x', '"', ':', '"', 0xff, '"', '}'})
	for i, c := range cases {
		if _, err := VerifyArtifact(c); err == nil {
			t.Fatalf("invalid artifact %d accepted", i)
		}
	}
}

func TestProtocolRequiresFencedNativeSettlement(t *testing.T) {
	ex := fixtureExecute()
	p := NewProtocol(ex)
	ready := frame(ex, 1, "ready")
	ready.NativeSessionRef = "fixture-session"
	art := frame(ex, 2, "artifact")
	a := artifactFor([]byte(`{ "example" : "fixture" }`))
	art.Artifact = &a
	settled := frame(ex, 3, "settled")
	settled.StopReason = "completed"
	for _, e := range []Event{ready, art, settled} {
		if err := p.Accept(encodeEvent(t, e)); err != nil {
			t.Fatal(err)
		}
	}
	r := p.Result(true, true)
	if status, _ := terminalOutcome(false, r); status != Succeeded {
		t.Fatalf("complete evidence: %s", status)
	}
	if status, _ := terminalOutcome(true, r); status != Cancelled {
		t.Fatalf("cancel must suppress result: %s", status)
	}
	if p.Accept(encodeEvent(t, settled)) == nil {
		t.Fatal("duplicate settlement accepted")
	}
	for _, field := range []string{"epoch", "execution", "job", "sequence"} {
		q := NewProtocol(ex)
		e := ready
		switch field {
		case "epoch":
			e.OwnerEpoch = newID()
		case "execution":
			e.ExecutionID = newID()
		case "job":
			e.JobID = newID()
		case "sequence":
			e.Sequence = 2
		}
		if q.Accept(encodeEvent(t, e)) == nil {
			t.Fatalf("stale %s accepted", field)
		}
	}
	q := NewProtocol(ex)
	if q.Accept(encodeEvent(t, art)) == nil {
		t.Fatal("artifact before ready accepted")
	}
	q = NewProtocol(ex)
	_ = q.Accept(encodeEvent(t, ready))
	settled.Sequence = 2
	if q.Accept(encodeEvent(t, settled)) == nil {
		t.Fatal("completed without artifact accepted")
	}
	q = NewProtocol(ex)
	_ = q.Accept(encodeEvent(t, ready))
	_ = q.Accept(encodeEvent(t, art))
	if status, _ := terminalOutcome(false, q.Result(true, true)); status != NeedsVerification {
		t.Fatal("artifact/exit without native settlement became terminal success")
	}
	if status, _ := terminalOutcome(false, Outcome{StopReason: "completed", Artifact: &a, RawArtifact: []byte(`{}`), CleanExit: true, Quiescent: true}); status != NeedsVerification {
		t.Fatal("mismatched persisted bytes accepted")
	}
	bad := strings.TrimSuffix(string(encodeEvent(t, ready)), "}") + `,"stopReason":""}`
	if NewProtocol(ex).Accept([]byte(bad)) == nil {
		t.Fatal("inapplicable empty field accepted")
	}
}

func TestCombinedFrameBoundsPreserveOpaqueInput(t *testing.T) {
	// HTML-sensitive and Unicode bytes must not inflate when the validated raw
	// input is carried to the child. Fingerprinting can normalize separately.
	for _, text := range []string{strings.Repeat("<", 60000), strings.Repeat("\u2028", 20000)} {
		body := []byte(`{"requestId":"` + fixtureID + `","capability":"shortpost","payloadSchema":"shortpost.input.v1","opaquePayload":{"example":"` + text + `"}}`)
		in, _, err := ParseInput(body)
		if err != nil {
			t.Fatal(err)
		}
		ex := fixtureExecute()
		ex.OpaquePayload = in.OpaquePayload
		ex.ModelRef = strings.Repeat("m", 256)
		ex.ResourceVersions = map[string]string{}
		for i := 0; i < 32; i++ {
			ex.ResourceVersions[strings.Repeat("k", 126)+string(rune('A'+i))] = strings.Repeat("v", 256)
		}
		b, err := marshalFrame(ex)
		if err != nil || len(b)+1 > MaxFrameBytes {
			t.Fatalf("combined execute %d: %v", len(b), err)
		}
	}
	raw := []byte(`{"example":"` + strings.Repeat("x", MaxArtifactBytes-len(`{"example":""}`)) + `"}`)
	a := artifactFor(raw)
	if _, err := VerifyArtifact(a); err != nil {
		t.Fatal(err)
	}
	e := frame(fixtureExecute(), 2, "artifact")
	e.Artifact = &a
	b, err := marshalFrame(e)
	if err != nil || len(b)+1 > MaxFrameBytes {
		t.Fatalf("combined artifact %d: %v", len(b), err)
	}
	p := fixtureProfile()
	p.ResourceVersions = map[string]string{}
	for i := 0; i < 32; i++ {
		p.ResourceVersions[strings.Repeat("\x00", 126)+string(rune('A'+i))] = strings.Repeat("\x00", 256)
	}
	if validProfile(p) == nil {
		t.Fatal("accepted profile whose escaping exceeds combined frame budget")
	}
}
