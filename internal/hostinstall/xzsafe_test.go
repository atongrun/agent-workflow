package hostinstall

import (
	"bytes"
	"context"
	"encoding/binary"
	"hash/crc32"
	"io"
	"os"
	"path/filepath"
	"testing"

	"github.com/ulikunitz/xz"
)

type xzRecord struct{ unpadded, unpacked uint64 }

func multiBlockXZ(t *testing.T) ([]byte, []byte) {
	t.Helper()
	payload := bytes.Repeat([]byte("bounded multi-block stream\n"), 6000)
	var buf bytes.Buffer
	w, err := (xz.WriterConfig{BlockSize: 1 << 16}).NewWriter(&buf)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = w.Write(payload); err != nil {
		t.Fatal(err)
	}
	if err = w.Close(); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes(), payload
}
func fixtureXZRecords(t *testing.T, data []byte) (int, []xzRecord) {
	t.Helper()
	footer := data[len(data)-12:]
	size := (int(binary.LittleEndian.Uint32(footer[4:8])) + 1) * 4
	start := len(data) - 12 - size
	index := data[start : len(data)-12-4]
	pos := 1
	count, err := xzVLI(index, &pos)
	if err != nil {
		t.Fatal(err)
	}
	var records []xzRecord
	for i := uint64(0); i < count; i++ {
		a, e := xzVLI(index, &pos)
		if e != nil {
			t.Fatal(e)
		}
		b, e := xzVLI(index, &pos)
		if e != nil {
			t.Fatal(e)
		}
		records = append(records, xzRecord{a, b})
	}
	return start, records
}
func replaceXZIndex(t *testing.T, data []byte, records []xzRecord) []byte {
	t.Helper()
	start, _ := fixtureXZRecords(t, data)
	index := []byte{0}
	index = binary.AppendUvarint(index, uint64(len(records)))
	for _, r := range records {
		index = binary.AppendUvarint(index, r.unpadded)
		index = binary.AppendUvarint(index, r.unpacked)
	}
	for len(index)%4 != 0 {
		index = append(index, 0)
	}
	index = binary.LittleEndian.AppendUint32(index, crc32.ChecksumIEEE(index))
	footer := append([]byte(nil), data[len(data)-12:]...)
	binary.LittleEndian.PutUint32(footer[4:8], uint32(len(index)/4-1))
	binary.LittleEndian.PutUint32(footer[:4], crc32.ChecksumIEEE(footer[4:10]))
	out := append([]byte(nil), data[:start]...)
	out = append(out, index...)
	return append(out, footer...)
}
func preflightFixtureXZ(t *testing.T, data []byte) error {
	t.Helper()
	name := filepath.Join(t.TempDir(), "fixture.xz")
	if err := os.WriteFile(name, data, 0600); err != nil {
		t.Fatal(err)
	}
	f, err := os.Open(name)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	return preflightXZ(context.Background(), f, int64(len(data)))
}
func TestXZPreflightValidMultipleBlocksAndLyingIndex(t *testing.T) {
	data, payload := multiBlockXZ(t)
	_, records := fixtureXZRecords(t, data)
	if len(records) < 2 {
		t.Fatal("fixture did not produce multiple blocks")
	}
	if err := preflightFixtureXZ(t, data); err != nil {
		t.Fatal("valid multi-block XZ refused", err)
	}
	r, err := (xz.ReaderConfig{SingleStream: true}).NewReader(bytes.NewReader(data))
	if err != nil {
		t.Fatal(err)
	}
	actual, err := io.ReadAll(r)
	if err != nil || !bytes.Equal(actual, payload) {
		t.Fatal("valid fixture decode", err)
	}
	// Hide all real block boundaries in one forged index record. Both index and
	// footer have valid CRCs. First header remains safe, while the second asks for
	// a 4GiB dictionary. Header-only index preflight would miss this allocation.
	hostile := append([]byte(nil), data...)
	second := 12 + int((records[0].unpadded+3)&^3)
	n := (int(hostile[second]) + 1) * 4
	if hostile[second+1] != 0 {
		t.Fatal("fixture header has optional size fields")
	}
	hostile[second+4] = 40
	binary.LittleEndian.PutUint32(hostile[second+n-4:], crc32.ChecksumIEEE(hostile[second:second+n-4]))
	combined := xzRecord{}
	for i, r := range records {
		combined.unpacked += r.unpacked
		if i == len(records)-1 {
			combined.unpadded += r.unpadded
		} else {
			combined.unpadded += (r.unpadded + 3) &^ 3
		}
	}
	hostile = replaceXZIndex(t, hostile, []xzRecord{combined})
	if err := preflightFixtureXZ(t, hostile); err == nil {
		t.Fatal("lying index hid an excessive dictionary")
	}
	oversized := append([]xzRecord(nil), records...)
	oversized[0].unpacked = uint64(maxExpandedBytes) + 1
	if err := preflightFixtureXZ(t, replaceXZIndex(t, data, oversized)); err == nil {
		t.Fatal("excessive expanded index accepted")
	}
}
func TestLZMA2ChunkBudgetAndCancellation(t *testing.T) {
	// Four uncompressed one-byte chunks plus an end marker.
	data := []byte{1, 0, 0, 'a', 2, 0, 0, 'b', 2, 0, 0, 'c', 2, 0, 0, 'd', 0}
	name := filepath.Join(t.TempDir(), "chunks")
	if err := os.WriteFile(name, data, 0600); err != nil {
		t.Fatal(err)
	}
	f, err := os.Open(name)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	budget := 5
	if err = preflightLZMA2(context.Background(), f, 0, int64(len(data)), 4, &budget); err != nil {
		t.Fatal("valid chunk scan", err)
	}
	budget = 4
	if err = preflightLZMA2(context.Background(), f, 0, int64(len(data)), 4, &budget); err == nil {
		t.Fatal("chunk budget bypassed")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	budget = 5
	if err = preflightLZMA2(ctx, f, 0, int64(len(data)), 4, &budget); err == nil {
		t.Fatal("cancelled preflight proceeded")
	}
}
