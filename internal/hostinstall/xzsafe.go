package hostinstall

import (
	"bytes"
	"context"
	"encoding/binary"
	"errors"
	"hash/crc32"
	"io"
	"os"
)

// xz.ReaderConfig.DictCap is a minimum, not an allocation limit. Preflight the
// single stream's complete index and every block header before constructing a
// decoder. Only one LZMA2 filter with <=64MiB dictionary is accepted. The pinned
// decoder subsequently validates compressed data, index consistency and checksums.
func preflightXZ(ctx context.Context, f *os.File, size int64) error {
	bad := errors.New("unsupported or excessive XZ structure")
	if size < 32 {
		return bad
	}
	header := make([]byte, 12)
	footer := make([]byte, 12)
	if _, e := f.ReadAt(header, 0); e != nil {
		return bad
	}
	if _, e := f.ReadAt(footer, size-12); e != nil {
		return bad
	}
	if !bytes.Equal(header[:6], []byte{0xfd, '7', 'z', 'X', 'Z', 0}) || !bytes.Equal(footer[10:], []byte{'Y', 'Z'}) || !bytes.Equal(header[6:8], footer[8:10]) || header[6] != 0 || header[7] > 15 || crc32.ChecksumIEEE(header[6:8]) != binary.LittleEndian.Uint32(header[8:]) || crc32.ChecksumIEEE(footer[4:10]) != binary.LittleEndian.Uint32(footer[:4]) {
		return bad
	}
	indexSize := (int64(binary.LittleEndian.Uint32(footer[4:8])) + 1) * 4
	if indexSize < 8 || indexSize > 1<<20 || indexSize > size-24 {
		return bad
	}
	indexOffset := size - 12 - indexSize
	index := make([]byte, indexSize)
	if _, e := f.ReadAt(index, indexOffset); e != nil {
		return bad
	}
	if index[0] != 0 || crc32.ChecksumIEEE(index[:len(index)-4]) != binary.LittleEndian.Uint32(index[len(index)-4:]) {
		return bad
	}
	cursor := 1
	count, e := xzVLI(index[:len(index)-4], &cursor)
	if e != nil || count < 1 || count > maxArchiveEntries {
		return bad
	}
	checkBytes := map[byte]int64{0: 0, 1: 4, 4: 8, 10: 32}
	checkSize, ok := checkBytes[header[7]]
	if !ok {
		return bad
	}
	offset := int64(12)
	expanded := uint64(0)
	chunkBudget := 65536
	for i := uint64(0); i < count; i++ {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		unpadded, e := xzVLI(index[:len(index)-4], &cursor)
		if e != nil || unpadded < 8 || unpadded > uint64(size) {
			return bad
		}
		unpacked, e := xzVLI(index[:len(index)-4], &cursor)
		if e != nil || unpacked > uint64(maxExpandedBytes)-expanded {
			return bad
		}
		expanded += unpacked
		padded := (int64(unpadded) + 3) &^ 3
		if offset+padded > indexOffset {
			return bad
		}
		first := []byte{0}
		if _, e = f.ReadAt(first, offset); e != nil || first[0] == 0 {
			return bad
		}
		blockSize := (int(first[0]) + 1) * 4
		if int64(blockSize) >= int64(unpadded) {
			return bad
		}
		block := make([]byte, blockSize)
		if _, e = f.ReadAt(block, offset); e != nil {
			return bad
		}
		if crc32.ChecksumIEEE(block[:len(block)-4]) != binary.LittleEndian.Uint32(block[len(block)-4:]) || block[1]&0x3f != 0 {
			return bad
		}
		pos := 2
		if block[1]&0x40 != 0 {
			if _, e = xzVLI(block[:len(block)-4], &pos); e != nil {
				return bad
			}
		}
		if block[1]&0x80 != 0 {
			if _, e = xzVLI(block[:len(block)-4], &pos); e != nil {
				return bad
			}
		}
		id, e := xzVLI(block[:len(block)-4], &pos)
		if e != nil || id != 0x21 {
			return bad
		}
		props, e := xzVLI(block[:len(block)-4], &pos)
		if e != nil || props != 1 || pos >= len(block)-4 || block[pos] > 28 {
			return bad
		}
		pos++
		for _, b := range block[pos : len(block)-4] {
			if b != 0 {
				return bad
			}
		}
		compressedSize := int64(unpadded) - int64(blockSize) - checkSize
		if compressedSize < 1 || preflightLZMA2(ctx, f, offset+int64(blockSize), compressedSize, unpacked, &chunkBudget) != nil {
			return bad
		}
		offset += padded
	}
	if offset != indexOffset {
		return bad
	}
	for _, b := range index[cursor : len(index)-4] {
		if b != 0 {
			return bad
		}
	}
	return nil
}
func xzVLI(data []byte, pos *int) (uint64, error) {
	var v uint64
	for i := 0; i < 9; i++ {
		if *pos >= len(data) {
			return 0, io.ErrUnexpectedEOF
		}
		b := data[*pos]
		*pos++
		v |= uint64(b&0x7f) << uint(7*i)
		if b&0x80 == 0 {
			if i > 0 && b == 0 {
				return 0, errors.New("noncanonical XZ integer")
			}
			return v, nil
		}
	}
	return 0, errors.New("excessive XZ integer")
}

// Validate LZMA2 chunk boundaries without decompression. This binds actual
// block end markers to the index: a lying index cannot hide an unexamined next
// block header that asks the decoder for an excessive dictionary.
func preflightLZMA2(ctx context.Context, f *os.File, offset, size int64, unpacked uint64, budget *int) error {
	end := offset + size
	var expanded uint64
	bad := errors.New("invalid LZMA2 chunk boundaries")
	for *budget > 0 {
		*budget--
		if ctx.Err() != nil {
			return ctx.Err()
		}
		if offset >= end {
			return bad
		}
		control := []byte{0}
		if _, err := f.ReadAt(control, offset); err != nil {
			return bad
		}
		offset++
		c := control[0]
		if c == 0 {
			if offset != end || expanded != unpacked {
				return bad
			}
			return nil
		}
		var packed, plain uint64
		if c == 1 || c == 2 {
			header := make([]byte, 2)
			if offset+2 > end {
				return bad
			}
			if _, err := f.ReadAt(header, offset); err != nil {
				return bad
			}
			offset += 2
			plain = uint64(binary.BigEndian.Uint16(header)) + 1
			packed = plain
		} else if c >= 128 {
			header := make([]byte, 4)
			if offset+4 > end {
				return bad
			}
			if _, err := f.ReadAt(header, offset); err != nil {
				return bad
			}
			offset += 4
			plain = (uint64(c&31)<<16 | uint64(binary.BigEndian.Uint16(header[:2]))) + 1
			packed = uint64(binary.BigEndian.Uint16(header[2:])) + 1
			if c >= 192 {
				offset++
			}
		} else {
			return bad
		}
		if plain > unpacked-expanded || int64(packed) > end-offset {
			return bad
		}
		expanded += plain
		offset += int64(packed)
	}
	return bad
}
