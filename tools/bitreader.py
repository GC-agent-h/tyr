"""
BitReader — a faithful reimplementation of UE5.6 FBitReader bit semantics,
with built-in trace logging for debugging the TYR replay format.

Bit ordering (matches Unreal's FBitReader):
  * Bits are read MSB-first *within* each byte.
    Byte 0b1011_0011 -> first bit read is 1 (bit 7), then 0 (bit 6), ...
  * Numbers spanning multiple bits are reassembled LSB-first: the first bit
    read becomes bit 0 of the returned integer. This matches how UE's
    NetBitReader reads serialized integers (quantized values, packed counts).

Reference: Engine/Source/Runtime/Core/Public/Serialization/BitReader.h
           Engine/Source/Runtime/Core/Private/Serialization/BitArchive.cpp
           (FArchive::SerializeIntPacked)
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import List, Optional


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


class BitReader:
    def __init__(self, data: bytes, size_in_bits: Optional[int] = None):
        """
        data: the source buffer (bytes-like).
        size_in_bits: total readable size in bits. If None, uses len(data)*8.
        """
        self._data = bytes(data)
        self._num_bytes = len(self._data)
        if size_in_bits is None:
            self._num_bits = self._num_bytes * 8
        else:
            self._num_bits = int(size_in_bits)
        self._pos = 0  # current bit position
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
            print(
                f"[{e.kind:>10}] byte={e.byte_off:>8} "
                f"bit={e.bit_off:>8} n={e.n_bits:>4} "
                f"value={v!r} {e.note}"
            )

    def _log(self, kind: str, n_bits: int, value: object, note: str = ""):
        if self._trace_on:
            self._trace.append(
                TraceEntry(kind, self._pos - n_bits, self._pos - n_bits, n_bits, value, note)
            )

    # ---- core reads ----------------------------------------------------
    def read_bit(self) -> int:
        """Read a single bit, returned as 0 or 1."""
        if self._pos >= self._num_bits:
            self._error = True
            raise BitReaderError(
                f"read past end: pos={self._pos} >= num_bits={self._num_bits}"
            )
        byte = self._data[self._pos >> 3]
        mask = 1 << (7 - (self._pos & 7))
        bit = 1 if (byte & mask) else 0
        self._pos += 1
        self._log("bit", 1, bit)
        return bit

    def read_bits(self, n: int) -> int:
        """
        Read n bits and return them as an integer, LSB-first
        (first bit read -> bit 0). n must be <= 32 for the int result.
        """
        if n > 32:
            raise ValueError("read_bits supports at most 32 bits into an int")
        value = 0
        for i in range(n):
            value |= self.read_bit() << i
        return value

    def read_bytes(self, n: int) -> bytes:
        """Byte-aligned raw byte read. Asserts the stream is byte-aligned."""
        if not self.byte_aligned():
            raise BitReaderError(
                f"read_bytes requires byte alignment, pos={self._pos}"
            )
        if self._pos + n * 8 > self._num_bits:
            self._error = True
            raise BitReaderError(
                f"read_bytes past end: need {n} bytes at pos={self._pos} "
                f"(num_bits={self._num_bits})"
            )
        start = self._pos >> 3
        out = self._data[start : start + n]
        self._pos += n * 8
        self._log("bytes", n * 8, out)
        return out

    # ---- UE-aligned helpers (mirror FBitReader API shapes) -------------
    def serialize_bits(self, n: int) -> bytes:
        """
        Read n bits into a fresh byte buffer, MSB-first within bytes
        (mirrors FBitReader::SerializeBits). Returns the byte buffer.
        """
        nbytes = (n + 7) // 8
        out = bytearray(nbytes)
        for i in range(n):
            bit = self.read_bit()
            if bit:
                out[i >> 3] |= 1 << (i & 7)
        self._log("serialize_bits", n, bytes(out))
        return bytes(out)

    def serialize(self, n_bytes: int) -> bytes:
        """Read n_bytes (byte-aligned). Mirrors FBitReader::Serialize."""
        return self.read_bytes(n_bytes)

    def serialize_int_packed(self) -> int:
        """
        UE5.6 FArchive::SerializeIntPacked (ULW / VLQ scheme).
        Each step reads one byte: LSB is a continuation flag; the upper 7 bits
        are a value chunk, combined little-endian across steps
        (chunk0 << 0, chunk1 << 7, chunk2 << 14, ...).
        Byte reads here are byte-aligned by construction.
        """
        if not self.byte_aligned():
            # SerializeIntPacked reads whole bytes; force alignment per UE.
            # (FBitReader pads to byte for Serialize of 1 byte.)
            self._pos += (8 - (self._pos & 7)) & 7
        value = 0
        cnt = 0
        while True:
            byte_off = self._pos >> 3
            if self._pos + 8 > self._num_bits:
                self._error = True
                raise BitReaderError("serialize_int_packed past end")
            b = self._data[byte_off]
            self._pos += 8
            more = (b & 1) != 0
            chunk = b >> 1
            value += chunk << (7 * cnt)
            cnt += 1
            if not more:
                break
        self._log("int_packed", cnt * 8, value, note=f"{cnt} byte(s)")
        return value

    # ---- convenience ---------------------------------------------------
    def read_uint16(self) -> int:
        return struct.unpack("<H", self.read_bytes(2))[0]

    def read_uint32(self) -> int:
        return struct.unpack("<I", self.read_bytes(4))[0]

    def read_uint64(self) -> int:
        return struct.unpack("<Q", self.read_bytes(8))[0]

    def read_fstring(self) -> str:
        """
        UE FString network serialization: int32 length (negative = Unicode
        UTF-16, absolute byte length / 2), then the bytes. Returns a decoded
        string. (Sign-convention nuance noted; validate in Phase 02/03.)
        """
        length = struct.unpack("<i", self.read_bytes(4))[0]
        if length == 0:
            return ""
        if length < 0:
            # UTF-16
            length = -length
            nbytes = length * 2
            raw = self.read_bytes(nbytes)
            return raw.decode("utf-16-le", errors="replace")
        else:
            raw = self.read_bytes(length)
            return raw.decode("utf-8", errors="replace")


if __name__ == "__main__":
    # Smoke test: MSB-first bit order and SerializeIntPacked round-trip.
    br = BitReader(bytes([0b10110011, 0b00000010]))
    assert br.read_bit() == 1
    assert br.read_bit() == 0
    assert br.read_bit() == 1
    assert br.read_bit() == 1
    # remaining bytes: 0011 (rest of byte0) then full byte1
    print("bit-read smoke test ok")

    # SerializeIntPacked: value 0 -> single byte 0x00
    br2 = BitReader(bytes([0x00]))
    assert br2.serialize_int_packed() == 0
    # value 127 -> chunk 127, no continuation -> 0xFE
    br3 = BitReader(bytes([0xFE]))
    assert br3.serialize_int_packed() == 127
    # value 128 -> byte0: chunk 0 + more(0x01); byte1: chunk 1 (0x02)
    br4 = BitReader(bytes([0x01, 0x02]))
    assert br4.serialize_int_packed() == 128
    print("serialize_int_packed smoke test ok")
