"""
bitreader.py — faithful reimplementation of UE5.6 bit-level serialization
primitives used by the TYR replay format.

ALL behavior here is sourced from the engine files in /UE, read line by line:

  * Bit ordering (LSB-first within a byte):
      UE/BitReader.cpp  FBitReader::ReadBit       -> Shift(LocalPos&7) = 1<<(LocalPos&7)
      UE/BitReader.cpp  FBitReader::SerializeBits -> appBitsCpy / Shift()
      UE/BitWriter.cpp  FBitWriter::WriteBit      -> Buffer[Num>>3] |= GShift[Num&7]
      UE/BitWriter.cpp  GShift/NOTE: bit 0 of the stream == bit 0 of the byte (LSB)
    -> CORRECTION vs Phase-00 scaffold: the scaffold read MSB-first. That is
       WRONG for UE5.6 and would silently corrupt every downstream phase. Bit 0
       is the LSB of each byte; read_bits() reassembles LSB-first (first bit
       read -> bit 0 of the returned integer), matching SerializeInt.

  * SerializeInt (range-compacted, ceil(log2(MaxValue)) bits):
      UE/BitReader.cpp  FBitReader::SerializeInt
      UE/BitWriter.cpp  FBitWriter::SerializeInt

  * SerializeIntPacked (7-bit payload + 1-bit continuation LSB, NOT
    byte-aligned — straddles byte boundaries at the current bit position):
      UE/BitReader.cpp  FBitReader::SerializeIntPacked   (bit-position aware)
      UE/BitWriter.cpp  FBitWriter::SerializeIntPacked
      UE/Archive.cpp    FArchive::SerializeIntPacked       (byte-aligned variant,
                                                            same 7/1 encoding)

  * SerializeIntPacked64 (same scheme, 64-bit, up to 10 bytes):
      UE/Archive.cpp    FArchive::SerializeIntPacked64
      UE/NetworkGuid.h  FNetworkGUID::operator<< uses SerializeIntPacked64,
                        static flag = (ObjectId & 1),
                        CreateFromIndex(NetIndex << 1 | bIsStatic)

  * FString (int32 length; 0 = empty; negative = UTF-16 code units;
    length includes null terminator for the ANSI case):
      Empirically confirmed byte-exact across all 10 samples by
      tools/header.py (Phase 02). The UE5.6 FString::Serialize operator is
      not present in the curated /UE subset, so this implementation is
      validated by the Phase-02 byte-exact consumption assertion rather than
      by reading the operator<< directly. See docs note in README.

  * Network FName (UPackageMap::StaticSerializeName, CoreNet.cpp:306):
      1 bit  bHardcoded
        if 1: SerializeIntPacked NameIndex -> EName (hardcoded names carry no Number)
        else:  FString + int32 Number  -> FName(String, Number)
      (Version gating: EngineNetVer < ChannelNames used SerializeInt; TYR is
       at HISTORY_USE_CUSTOM_VERSION=19 >= ChannelNames, so SerializeIntPacked.)

This module is import-safe (no project path magic) so tests can live beside it.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import List, Optional, Union, Tuple


# ---------------------------------------------------------------------------
# Bit-level traces (debugging aid; preserved from Phase 00 scaffold)
# ---------------------------------------------------------------------------
@dataclass
class TraceEntry:
    kind: str
    byte_off: int
    bit_off: int
    n_bits: int
    value: object
    note: str = ""


class BitReaderError(Exception):
    pass


class BitWriterError(Exception):
    pass


# ===========================================================================
# BitReader — LSB-first, absolute bit-position tracking
# ===========================================================================
class BitReader:
    def __init__(self, data: bytes, size_in_bits: Optional[int] = None):
        self._data = bytes(data)
        self._num_bytes = len(self._data)
        self._num_bits = self._num_bytes * 8 if size_in_bits is None else int(size_in_bits)
        self._pos = 0  # absolute bit position from start of stream
        self._error = False
        self._trace_on = False
        self._trace: List[TraceEntry] = []

    # ---- state ---------------------------------------------------------
    def tell_bits(self) -> int:
        return self._pos

    def tell_bytes(self) -> int:
        return self._pos // 8

    def seek_bits(self, pos: int) -> None:
        self._pos = pos
        self._error = False

    def remaining_bits(self) -> int:
        return max(0, self._num_bits - self._pos)

    def remaining_bytes(self) -> int:
        return self.remaining_bits() // 8

    def is_error(self) -> bool:
        return self._error

    def byte_aligned(self) -> bool:
        return (self._pos & 7) == 0

    def read_align(self) -> None:
        # Mirror FBitReader::EatByteAlign: skip to next byte boundary.
        if self._pos & 7:
            self._pos = (self._pos + 7) & (~0x07)

    def at_end(self) -> bool:
        return self._error or self._pos >= self._num_bits

    # ---- trace ---------------------------------------------------------
    def set_trace(self, on: bool) -> None:
        self._trace_on = on
        if not on:
            self._trace.clear()

    def get_trace(self) -> List[TraceEntry]:
        return list(self._trace)

    def print_trace(self, limit: Optional[int] = None) -> None:
        entries = self._trace if limit is None else self._trace[-limit:]
        for e in entries:
            v = e.value
            if isinstance(v, (bytes, bytearray)):
                v = v.hex()
            print(f"[{e.kind:>12}] byte={e.byte_off:>8} bit={e.bit_off:>8} "
                  f"n={e.n_bits:>4} value={v!r} {e.note}")

    def _log(self, kind: str, n_bits: int, value: object, note: str = "") -> None:
        if self._trace_on:
            self._trace.append(
                TraceEntry(kind, self._pos - n_bits, self._pos - n_bits, n_bits, value, note)
            )

    # ---- core bit reads (LSB-first within each byte) -------------------
    def read_bit(self) -> int:
        if self._pos >= self._num_bits:
            self._error = True
            raise BitReaderError(f"read past end: pos={self._pos} >= num_bits={self._num_bits}")
        # Bit 0 of the stream == bit 0 (LSB) of the byte.
        mask = 1 << (self._pos & 7)
        bit = 1 if (self._data[self._pos >> 3] & mask) else 0
        self._pos += 1
        self._log("bit", 1, bit)
        return bit

    def read_bits(self, n: int) -> int:
        """Read n bits, reassembled LSB-first (first bit read -> bit 0)."""
        if n > 64:
            raise ValueError("read_bits supports at most 64 bits into an int")
        value = 0
        for i in range(n):
            value |= self.read_bit() << i
        return value

    def read_bytes(self, n: int) -> bytes:
        if not self.byte_aligned():
            raise BitReaderError(f"read_bytes requires byte alignment, pos={self._pos}")
        if self._pos + n * 8 > self._num_bits:
            self._error = True
            raise BitReaderError(
                f"read_bytes past end: need {n} bytes at pos={self._pos} (num_bits={self._num_bits})"
            )
        start = self._pos >> 3
        out = self._data[start:start + n]
        self._pos += n * 8
        self._log("bytes", n * 8, out)
        return out

    # ---- SerializeBits (MSB-first *within the destination buffer*) ------
    # Mirrors FBitReader::SerializeBits: copies LengthBits raw into Dest,
    # preserving bit order (bit 0 of the stream -> bit 0 of Dest[0]).
    def serialize_bits(self, n: int) -> bytes:
        nbytes = (n + 7) // 8
        out = bytearray(nbytes)
        for i in range(n):
            if self.read_bit():
                out[i >> 3] |= 1 << (i & 7)
        self._log("serialize_bits", n, bytes(out))
        return bytes(out)

    def serialize(self, n_bytes: int) -> bytes:
        return self.read_bytes(n_bytes)

    # ---- SerializeInt (range-compacted) --------------------------------
    # Source: UE/BitReader.cpp FBitReader::SerializeInt.
    # Reads ceil(log2(ValueMax)) bits, LSB-first; OutValue < ValueMax.
    def serialize_int(self, value_max: int) -> int:
        if value_max < 2:
            # No bits needed; value is forced to 0. (SerializeInt requires Max>=2,
            # but guard so callers don't crash on degenerate ranges.)
            return 0
        start_pos = self._pos
        value = 0
        local_pos = self._pos
        local_num = self._num_bits
        mask = 1
        while (value + mask) < value_max and mask:
            if local_pos >= local_num:
                self._error = True
                break
            if self._data[local_pos >> 3] & (1 << (local_pos & 7)):
                value |= mask
            local_pos += 1
            mask <<= 1
        self._pos = local_pos
        self._log("int", local_pos - start_pos, value, note=f"max={value_max}")
        return value

    def read_int(self, value_max: int) -> int:
        return self.serialize_int(value_max)

    # ---- SerializeIntPacked (NOT byte-aligned) -------------------------
    # Source: UE/BitReader.cpp FBitReader::SerializeIntPacked.
    # Continuation bit is the LSB of each 8-bit group; payload is the upper 7
    # bits; groups combine little-endian (group0 << 0, group1 << 7, ...).
    # Reads at the CURRENT bit position and may straddle byte boundaries.
    def serialize_int_packed(self) -> int:
        if self.is_error():
            return 0
        src = self._data
        src_idx = self._pos >> 3
        bit_count_used = self._pos & 7
        bit_count_left = 8 - (self._pos & 7)
        src_mask_byte0 = (1 << bit_count_left) - 1
        src_mask_byte1 = (1 << bit_count_used) - 1
        next_src_index = 1 if bit_count_used != 0 else 0

        value = 0
        for _ in range(5):
            if self._pos + 8 > self._num_bits:
                self._error = True
                break
            self._pos += 8
            if src_idx >= len(src):
                self._error = True
                break
            byte = ((src[src_idx] >> bit_count_used) & src_mask_byte0) | \
                   ((src[src_idx + next_src_index] & src_mask_byte1) << (bit_count_left & 7))
            next_indicator = byte & 1
            byte_as_word = byte >> 1
            value = (byte_as_word << (7 * _)) | value
            src_idx += 1
            if not next_indicator:
                break
        self._log("int_packed", 0, value, note="bit-position aware")
        return value

    # ---- SerializeIntPacked64 (NOT byte-aligned) -----------------------
    # Source: UE/Archive.cpp FArchive::SerializeIntPacked64 (same encoding,
    # 64-bit accumulator, up to 10 groups).
    def serialize_int_packed64(self) -> int:
        if self.is_error():
            return 0
        value = 0
        for cnt in range(10):
            if self._pos + 8 > self._num_bits:
                self._error = True
                break
            byte = self.read_bits(8)  # uses current bit position
            more = byte & 1
            byte >>= 1
            value |= (byte << (7 * cnt))
            if not more:
                break
        self._log("int_packed64", 0, value, note="bit-position aware, 64-bit")
        return value

    # ---- FString -------------------------------------------------------
    # Scheme confirmed byte-exact vs Phase-02 header.py across all 10 samples.
    # int32 length: 0 empty; >0 ANSI (len bytes incl. null); <0 UTF-16
    # (abs(len) code units, 2 bytes each).
    def read_fstring(self) -> str:
        import struct as _struct
        length = _struct.unpack_from("<i", self.read_bytes(4))[0]
        if length == 0:
            return ""
        if length < 0:
            n = -length
            raw = self.read_bytes(n * 2)
            return raw.decode("utf-16-le", errors="replace")
        raw = self.read_bytes(length)
        return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")

    # ---- Network FName (UPackageMap::StaticSerializeName) --------------
    # 1-bit bHardcoded; if set -> SerializeIntPacked EName index (no Number);
    # else -> FString + int32 Number. Returns a dict descriptor; resolving the
    # EName index to a string is the name-table work of Phase 04.
    def read_fname(self) -> dict:
        b_hardcoded = self.read_bit()
        if b_hardcoded:
            idx = self.serialize_int_packed()
            return {"kind": "hardcoded", "name_index": idx, "number": 0}
        self.read_align()  # UE eats byte alignment before the FString
        name = self.read_fstring()
        number = struct.unpack_from("<i", self.read_bytes(4))[0]
        return {"kind": "string", "name": name, "number": number}

    # ---- FNetworkGUID --------------------------------------------------
    # Source: UE/NetworkGuid.h. ObjectId via SerializeIntPacked64;
    # static flag = (ObjectId & 1); IsValid = ObjectId > 0.
    def read_network_guid(self) -> dict:
        object_id = self.serialize_int_packed64()
        return {
            "object_id": object_id,
            "is_static": bool(object_id & 1),
            "is_valid": object_id > 0,
            "is_dynamic": (object_id > 0) and not (object_id & 1),
        }

    # ---- convenience fixed-width ---------------------------------------
    def read_uint16(self) -> int:
        return struct.unpack("<H", self.read_bytes(2))[0]

    def read_uint32(self) -> int:
        return struct.unpack("<I", self.read_bytes(4))[0]

    def read_uint64(self) -> int:
        return struct.unpack("<Q", self.read_bytes(8))[0]

    def read_int32(self) -> int:
        return struct.unpack("<i", self.read_bytes(4))[0]


# ===========================================================================
# BitWriter — LSB-first, matching FBitWriter, used for round-trip tests
# ===========================================================================
class BitWriter:
    def __init__(self, max_bits: int = 0, allow_resize: bool = True):
        self._max_bits = max_bits if max_bits else (1 << 30)
        self._buf = bytearray((self._max_bits + 7) // 8)
        self._num = 0  # bits written
        self._error = False
        self._allow_resize = allow_resize

    def tell_bits(self) -> int:
        return self._num

    def tell_bytes(self) -> int:
        return (self._num + 7) // 8

    def byte_aligned(self) -> bool:
        return (self._num & 7) == 0

    def is_error(self) -> bool:
        return self._error

    def _grow(self, need_bits: int) -> bool:
        if self._num + need_bits <= self._max_bits:
            return True
        if not self._allow_resize:
            self._error = True
            return False
        new_max = max(self._max_bits << 1, self._num + need_bits)
        self._buf.extend(b"\x00" * (((new_max + 7) // 8) - len(self._buf)))
        self._max_bits = new_max
        return True

    def write_bit(self, bit: int) -> None:
        if not self._grow(1):
            return
        if bit:
            self._buf[self._num >> 3] |= 1 << (self._num & 7)
        self._num += 1

    def write_bits(self, value: int, n: int) -> None:
        for i in range(n):
            self.write_bit((value >> i) & 1)

    def write_bytes(self, data: bytes) -> None:
        if not self.byte_aligned():
            raise BitWriterError(f"write_bytes requires alignment, pos={self._num}")
        if not self._grow(len(data) * 8):
            return
        start = self._num >> 3
        self._buf[start:start + len(data)] = data
        self._num += len(data) * 8

    def write_align(self) -> None:
        # Mirror FBitWriter::WriteAlign: pad to next byte boundary.
        self._num = (self._num + 7) & (~0x07)

    def serialize_int(self, value: int, value_max: int) -> None:
        # Mirror FBitWriter::SerializeInt.
        import math
        length_bits = max(1, (value_max - 1).bit_length()) if value_max >= 2 else 0
        write_value = value if value < value_max else value_max - 1
        if not self._grow(length_bits):
            return
        for i in range(length_bits):
            if write_value & (1 << i):
                self._buf[self._num >> 3] |= 1 << (self._num & 7)
            self._num += 1

    def serialize_int_packed(self, value: int) -> None:
        # Mirror FBitWriter::SerializeIntPacked (bit-position aware).
        v = value
        bytes_as_words = []
        while True:
            next_indicator = 1 if (v & ~0x7F) != 0 else 0
            byte_as_word = ((v & 0x7F) << 1) | next_indicator
            bytes_as_words.append(byte_as_word)
            v >>= 7
            if not next_indicator:
                break
        byte_count = len(bytes_as_words)
        bit_used = self._num & 7
        bit_left = 8 - (self._num & 7)
        # When byte-aligned (bit_used==0), mask0 must keep all bits of the
        # destination byte (1<<0 - 1 == 0 would wipe it), so treat as 0xFF.
        mask0 = 0xFF if bit_used == 0 else ((1 << bit_used) - 1)
        mask1 = 0xFF ^ mask0
        straddles = bit_used != 0
        if not self._grow(byte_count * 8):
            return
        dest = self._num >> 3
        self._num += byte_count * 8
        for bw in bytes_as_words:
            self._buf[dest] = (self._buf[dest] & mask0) | ((bw << bit_used) & 0xFF)
            dest += 1
            if straddles:
                self._buf[dest] = (self._buf[dest] & mask1) | ((bw >> bit_left) & 0xFF)

    def serialize_int_packed64(self, value: int) -> None:
        # Mirror FArchive::SerializeIntPacked64 encoder.
        v = value
        if v == 0:
            self.serialize_int_packed(0)
            return
        self.serialize_int_packed(v)  # identical encoding, same 7/1 scheme

    def write_fstring(self, s: str) -> None:
        if s == "":
            self.write_bytes(struct.pack("<i", 0))
            return
        # Try UTF-8 (ANSI path). Prefer the same encoding the reader expects:
        # positive length => single-byte UTF-8 incl. null terminator.
        encoded = s.encode("utf-8")
        # length includes the null terminator (matches UE FString::Serialize).
        self.write_bytes(struct.pack("<i", len(encoded) + 1))
        self.write_bytes(encoded)
        self.write_bytes(b"\x00")

    def write_fname(self, name: str, number: int = 0, hardcoded_index: Optional[int] = None) -> None:
        if hardcoded_index is not None:
            self.write_bit(1)
            self.serialize_int_packed(hardcoded_index)
        else:
            self.write_bit(0)
            self.write_align()  # UE eats byte alignment before the FString
            self.write_fstring(name)
            self.write_bytes(struct.pack("<i", number))

    def write_network_guid(self, object_id: int) -> None:
        self.serialize_int_packed64(object_id)

    def getvalue(self) -> bytes:
        return bytes(self._buf[: (self._num + 7) // 8])


# ===========================================================================
# Module self-test (smoke): bit order + SerializeIntPacked hand vectors
# ===========================================================================
if __name__ == "__main__":
    # Byte 0b0011_0011 (0x33) read LSB-first -> bits [1,1,0,0,1,1,0,0]
    br = BitReader(bytes([0b00110011]))
    seq = [br.read_bit() for _ in range(8)]
    assert seq == [1, 1, 0, 0, 1, 1, 0, 0], seq
    print("bit-order (LSB-first) smoke test ok")

    # SerializeIntPacked hand vectors (from the source algorithm).
    for v, enc in [(0, bytes([0x00])), (127, bytes([0xFE])),
                   (128, bytes([0x01, 0x02])), (16384, bytes([0x01, 0x01, 0x02]))]:
        br = BitReader(enc)
        got = br.serialize_int_packed()
        assert got == v, f"{v} != {got} (enc {enc.hex()})"
    print("serialize_int_packed hand-vector smoke test ok")

    # Round-trip a few values through BitWriter.
    for v in [0, 1, 127, 128, 16384, 1234567]:
        bw = BitWriter()
        bw.serialize_int_packed(v)
        br = BitReader(bw.getvalue())
        assert br.serialize_int_packed() == v, v
    print("serialize_int_packed writer round-trip smoke test ok")
