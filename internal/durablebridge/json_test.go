package durablebridge

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"math"
	"math/rand"
	"os/exec"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestPrivateRewriteFingerprintReference(t *testing.T) {
	const payload = `{"operation":"rewrite","input":{"idea":"公开改写素材","content":"公开合成正文","instruction":"保留事实"},"retainedSources":[],"source":{"generationId":"00000000-0000-4000-8000-000000000011","candidateId":"00000000-0000-4000-8000-000000000012","version":1.0}}`
	const expected = `{"capability":"shortpost","opaquePayload":{"input":{"content":"公开合成正文","idea":"公开改写素材","instruction":"保留事实"},"operation":"rewrite","retainedSources":[],"source":{"candidateId":"00000000-0000-4000-8000-000000000012","generationId":"00000000-0000-4000-8000-000000000011","version":1}},"payloadSchema":"shortpost.input.v1"}`
	var input any
	if err := strictJSON([]byte(payload), &input); err != nil {
		t.Fatal(err)
	}
	canonical, err := canonicalJSON(map[string]any{"capability": "shortpost", "payloadSchema": "shortpost.input.v1", "opaquePayload": input})
	if err != nil || string(canonical) != expected {
		t.Fatal(err, string(canonical))
	}
	digest := sha256.Sum256(canonical)
	if hex.EncodeToString(digest[:]) != "e2e0a6c3f2eecdde0f105e99c5a24eb029c42dc1c54893ed86b5c7f22d96f03b" {
		t.Fatal("PRIVATE reference fingerprint mismatch")
	}
}

func TestPrivateGenerateFingerprintExactTSBytes(t *testing.T) {
	const opaqueBase64 = "eyJvcGVyYXRpb24iOiJnZW5lcmF0ZSIsImlucHV0Ijp7ImlkZWEiOiLlhazlvIDlkIjmiJA8Jj7kuK3mlofigKjigKnkuI7lrZfpnaJcXHUyMDI4IiwidHlwZSI6ImV4cGVyaWVuY2UifSwicmV0YWluZWRTb3VyY2VzIjpbXX0="
	const canonicalBase64 = "eyJjYXBhYmlsaXR5Ijoic2hvcnRwb3N0Iiwib3BhcXVlUGF5bG9hZCI6eyJpbnB1dCI6eyJpZGVhIjoi5YWs5byA5ZCI5oiQPCY+5Lit5paH4oCo4oCp5LiO5a2X6Z2iXFx1MjAyOCIsInR5cGUiOiJleHBlcmllbmNlIn0sIm9wZXJhdGlvbiI6ImdlbmVyYXRlIiwicmV0YWluZWRTb3VyY2VzIjpbXX0sInBheWxvYWRTY2hlbWEiOiJzaG9ydHBvc3QuaW5wdXQudjEifQ=="
	opaque, err := base64.StdEncoding.DecodeString(opaqueBase64)
	if err != nil || len(opaque) != 128 {
		t.Fatal(err, len(opaque))
	}
	opaqueHash := sha256.Sum256(opaque)
	if hex.EncodeToString(opaqueHash[:]) != "0b283fe9b8787144c094b688fd804cb69c1d1fb700df23592984ae789ecef027" {
		t.Fatal("supplied opaque byte vector changed")
	}
	expected, err := base64.StdEncoding.DecodeString(canonicalBase64)
	if err != nil || len(expected) != 208 {
		t.Fatal(err, len(expected))
	}
	var payload any
	if err := strictJSON(opaque, &payload); err != nil {
		t.Fatal(err)
	}
	idea := payload.(map[string]any)["input"].(map[string]any)["idea"].(string)
	if strings.Count(idea, `\`) != 1 || !strings.Contains(idea, "\u2028\u2029") {
		t.Fatal("TS fixture Unicode/backslash decoded incorrectly")
	}
	actual, err := canonicalJSON(map[string]any{"capability": "shortpost", "payloadSchema": "shortpost.input.v1", "opaquePayload": payload})
	if err != nil || string(actual) != string(expected) {
		t.Fatal(err, string(actual))
	}
	hash := sha256.Sum256(actual)
	if hex.EncodeToString(hash[:]) != "f937a1e281bff96e82ef02a5c873587e6a5d6781010a85b9f07d6396a7e4afe2" {
		t.Fatal("TS fingerprint bytes mismatch")
	}
}

func TestJSONStringifyNumbersAgainstNode(t *testing.T) {
	node, err := exec.LookPath("node")
	if err != nil {
		t.Skip("Node scalar reference unavailable; pinned vectors still run")
	}
	random := rand.New(rand.NewSource(42))
	numbers := make([]string, 0, 512)
	for len(numbers) < cap(numbers) {
		value := math.Float64frombits(random.Uint64())
		text := strconv.FormatFloat(value, 'g', -1, 64)
		if _, err := jsNumber(json.Number(text)); err == nil {
			numbers = append(numbers, text)
		}
	}
	raw := []byte("[" + strings.Join(numbers, ",") + "]")
	var values any
	if err := strictJSON(raw, &values); err != nil {
		t.Fatal(err)
	}
	actual, err := canonicalJSON(values)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	command := exec.CommandContext(ctx, node, "-e", `let input='';process.stdin.setEncoding('utf8');process.stdin.on('data',s=>input+=s);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(input))));`)
	command.Stdin = strings.NewReader(string(raw))
	expected, err := command.Output()
	if err != nil {
		t.Fatal(err)
	}
	if string(actual) != string(expected) {
		t.Fatal("Go numeric encoding differs from Node JSON.stringify")
	}
}

func TestJSONStringifyScalarsAndUTF16KeyOrder(t *testing.T) {
	for _, test := range []struct{ input, expected string }{
		{`[1.0,-0,1e6,1e-6,1e-7,5e-324,0.100000000000000005,9007199254740991]`, `[1,0,1000000,0.000001,1e-7,5e-324,0.1,9007199254740991]`},
		{`{"z":"<&>\n\u2028\u2029","a":"\\u2028"}`, "{\"a\":\"\\\\u2028\",\"z\":\"<&>\\n\u2028\u2029\"}"},
		{`{"\ue000":1,"\ud800\udc00":2}`, "{\"\U00010000\":2,\"\ue000\":1}"},
		{`[{"z":1,"a":2},3,2]`, `[{"a":2,"z":1},3,2]`},
		{`{"2":2,"10":10}`, `{"10":10,"2":2}`},
	} {
		var value any
		if err := strictJSON([]byte(test.input), &value); err != nil {
			t.Fatal(test.input, err)
		}
		encoded, err := canonicalJSON(value)
		if err != nil || string(encoded) != test.expected {
			t.Fatal(test.input, string(encoded), test.expected, err)
		}
		frame, err := marshalFrame(json.RawMessage(test.input))
		if err != nil || string(frame) != test.expected {
			t.Fatal("worker frame re-encoded canonical input", string(frame), err)
		}
	}
}

func TestStrictJSONRejectsSurrogatesUnsafeNumbersAndDuplicateKeys(t *testing.T) {
	for _, input := range []string{`"\ud800"`, `"\udc00"`, `"\ud800\ud800"`, `"\ud800x"`, `9007199254740992`, `-9007199254740992`, `1e30`, `1e309`, `{"a":1,"\u0061":2}`, string([]byte{'"', 0xff, '"'})} {
		var value any
		if strictJSON([]byte(input), &value) == nil {
			t.Fatal("unsafe JSON accepted", input)
		}
	}
	for _, input := range []string{`"\\ud800"`, `"\ud83d\ude00"`, `0.25`, `1e-20`, `{"a":null}`} {
		var value any
		if err := strictJSON([]byte(input), &value); err != nil {
			t.Fatal("valid JSON rejected", input, err)
		}
	}
}

func TestCompletePublicAndWorkerFrameLimits(t *testing.T) {
	if MaxRequestBytes != 131072 || MaxWorkerRequestBytes != 131072 || MaxInputBytes != 65536 || MaxResultBytes != 65536 || MaxCursorBytes != 2048 {
		t.Fatal("wire bounds drifted")
	}
	for _, count := range []int{31, 32, 33} {
		var value any
		err := strictJSON([]byte(strings.Repeat("[", count)+"0"+strings.Repeat("]", count)), &value)
		if (err == nil) != (count <= 32) {
			t.Fatal("PRIVATE root-zero depth boundary", count, err)
		}
	}
}
