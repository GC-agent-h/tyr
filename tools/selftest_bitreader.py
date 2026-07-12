"""
selftest_bitreader.py — validation harness for tools/bitreader.py.

Run: python3 tools/selftest_bitreader.py
Validates (no live debugger available; static + round-trip checks only):
  S1  MSB-first bit ordering within a byte (matches FBitReader).
  S2  read_bits() LSB-first reassembly across byte boundaries.
  S3  SerializeIntPacked ULW/VLQ round-trip for 0,1,127,128,16384,MAX-1
      and 10k random values, verified against a hand re-encoder.
  S4  read_fstring() round-trip for ASCII, UTF-16, and empty strings.
  S5  byte-aligned read_bytes() + out-of-range error path.
  S6  trace logging captures (byte_off, bit_off, n_bits, value).
"""

import random
import struct
import sys

from bitreader import BitReader, BitReaderError


def enc_int_packed(value: int) -> bytes:
    """Hand encoder for FArchive::SerializeIntPacked (ULW scheme)."""
    out = bytearray()
    while True:
        chunk = value & 0x7F
        value >>= 7
        if value:
            out.append((chunk << 1) | 1)  # continuation
        else:
            out.append(chunk << 1)
            break
    return bytes(out)


def test_bit_order():
    # Byte 0b1011_0011 -> bits read in order: 1,0,1,1,0,0,1,1
    br = BitReader(bytes([0b10110011]))
    seq = [br.read_bit() for _ in range(8)]
    assert seq == [1, 0, 1, 1, 0, 0, 1, 1], seq
    print("S1 MSB-first bit order: OK")


def test_read_bits():
    # bytes [0xF0,0x0F]; MSB-first bit stream = 1111 0000 0000 1111;
    # read_bits(16) reassembles LSB-first = 0xF00F.
    br = BitReader(bytes([0xF0, 0x0F]))
    v = br.read_bits(16)
    assert v == 0xF00F, hex(v)
    # byte 0x01 has MSB-first bits 0,0,0,0,0,0,0,1; read_bits(8) reassembles
    # that single '1' into the most-significant bit -> 0b1000_0000 = 128.
    br2 = BitReader(bytes([0x01]))
    assert br2.read_bits(8) == 128
    print("S2 read_bits LSB-first reassembly: OK")


def test_int_packed():
    cases = [0, 1, 2, 127, 128, 16383, 16384, (1 << 28) - 1]
    for v in cases:
        br = BitReader(enc_int_packed(v))
        got = br.serialize_int_packed()
        assert got == v, f"enc/dec mismatch: {v} != {got}"
    # 10k random round-trips
    rng = random.Random(1234)
    for _ in range(10000):
        v = rng.randint(0, (1 << 32) - 1)
        br = BitReader(enc_int_packed(v))
        assert br.serialize_int_packed() == v
    # also that encode is minimal/sane
    assert enc_int_packed(127) == bytes([0xFE])
    assert enc_int_packed(128) == bytes([0x01, 0x02])
    print("S3 SerializeIntPacked round-trip (hand encoder + 10k random): OK")


def test_fstring():
    def enc_fstring(s: str) -> bytes:
        if s == "":
            return struct.pack("<i", 0)
        b = s.encode("utf-8")
        return struct.pack("<i", len(b)) + b

    def enc_fstring_u16(s: str) -> bytes:
        b = s.encode("utf-16-le")
        return struct.pack("<i", -len(s)) + b  # length in UTF-16 code units

    for s in ["", "hello", "WorldGravity", "Unreal® Engine"]:
        br = BitReader(enc_fstring(s))
        assert br.read_fstring() == s, s
    uni = "Größe—日本語"
    br = BitReader(enc_fstring_u16(uni))
    assert br.read_fstring() == uni, uni
    print("S4 read_fstring round-trip (ASCII/UTF-16/empty): OK")


def test_bytes_and_error():
    br = BitReader(bytes([0xDE, 0xAD, 0xBE, 0xEF]))
    assert br.read_bytes(4) == bytes([0xDE, 0xAD, 0xBE, 0xEF])
    br2 = BitReader(bytes([0x01, 0x02]), size_in_bits=8)
    try:
        br2.read_bytes(2)
        raise AssertionError("expected error on short read")
    except BitReaderError:
        pass
    print("S5 read_bytes + error path: OK")


def test_trace():
    br = BitReader(bytes([0x01]))
    br.set_trace(True)
    _ = br.read_bits(8)  # each bit logged individually (MSB-first within byte)
    tr = br.get_trace()
    assert len(tr) == 8, len(tr)
    assert [e.value for e in tr] == [0, 0, 0, 0, 0, 0, 0, 1]  # 0x01 bits
    assert tr[0].byte_off == 0 and tr[0].bit_off == 0 and tr[0].n_bits == 1
    print("S6 trace logging captures per-bit position+value: OK")


if __name__ == "__main__":
    test_bit_order()
    test_read_bits()
    test_int_packed()
    test_fstring()
    test_bytes_and_error()
    test_trace()
    print("\nALL BITREADER SELFTESTS PASSED")
