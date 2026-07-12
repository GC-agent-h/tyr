"""
selftest_bitreader.py — validation harness for tools/bitreader.py (Phase 03).

Run: python3 tools/selftest_bitreader.py

No live debugger is available; validation is static + round-trip + empirical:
  S1   Bit-ordering is LSB-first within a byte (matches UE5.6 FBitReader/ReadBit).
  S2   read_bits() reassembles LSB-first across/within bytes.
  S3   SerializeIntPacked: hand-constructed vectors (0,1,127,128,16384,MAX-1)
       decoded from byte sequences built BY HAND from the source algorithm,
       plus 10k random round-trips + non-byte-aligned bit-position decode.
  S4   SerializeInt: range-compacted decode for several MaxValue cases.
  S5   FString round-trip (empty / ASCII / UTF-16) via BitWriter->BitReader.
  S6   Network FName: hardcoded (1-bit + SerializeIntPacked) and string
       (FString + int32 Number) round-trip through BitWriter->BitReader.
  S7   FNetworkGUID: SerializeIntPacked64 + static/dynamic LSB flag, including
       the CreateFromIndex(NetIndex<<1 | static) construction, round-tripped.
  S8   SerializeIntPacked64: round-trip of 64-bit values including straddle.
  S9   Byte-aligned read_bytes() + out-of-range error path.
  S10  Trace logging captures (byte_off, bit_off, n_bits, value).

All vectors are derived from the actual UE5.6 source in /UE, not from
general knowledge or other formats.
"""

import random
import sys

from bitreader import BitReader, BitWriter, BitReaderError, BitWriterError


# Hand encoder for FBitWriter::SerializeIntPacked (bit-position aware; here
# we feed it at a byte boundary, so it matches FArchive::SerializeIntPacked).
def enc_int_packed(value: int) -> bytes:
    out = bytearray()
    while True:
        chunk = value & 0x7F
        value >>= 7
        if value:
            out.append((chunk << 1) | 1)
        else:
            out.append(chunk << 1)
            break
    return bytes(out)


# Hand encoder for FArchive::SerializeIntPacked64 (same 7/1 scheme).
def enc_int_packed64(value: int) -> bytes:
    return enc_int_packed(value)


def test_bit_order():
    # LSB-first: byte 0b0011_0011 (0x33) -> bits [1,1,0,0,1,1,0,0]
    # (bit0=1, bit1=1, bit2=0, bit3=0, bit4=1, bit5=1, bit6=0, bit7=0)
    br = BitReader(bytes([0b00110011]))
    seq = [br.read_bit() for _ in range(8)]
    assert seq == [1, 1, 0, 0, 1, 1, 0, 0], seq
    # byte 0x01 (b0000_0001) -> LSB first = [1,0,0,0,0,0,0,0]
    br2 = BitReader(bytes([0x01]))
    assert [br2.read_bit() for _ in range(8)] == [1, 0, 0, 0, 0, 0, 0, 0]
    print("S1 LSB-first bit order: OK")


def test_read_bits():
    # bytes [0xF0,0x0F]; LSB-first bit stream = 0000 1111 1111 0000;
    # read_bits(16) reassembles LSB-first = 0x0FF0.
    br = BitReader(bytes([0xF0, 0x0F]))
    v = br.read_bits(16)
    assert v == 0x0FF0, hex(v)
    # byte 0x80 (1000_0000) LSB-first = [0,0,0,0,0,0,0,1] -> 0b1000_0000 = 128
    br2 = BitReader(bytes([0x80]))
    assert br2.read_bits(8) == 128
    print("S2 read_bits LSB-first reassembly: OK")


def test_int_packed_hand_vectors():
    # Vectors built by hand from FArchive::SerializeIntPacked algorithm.
    cases = [
        (0,    bytes([0x00])),
        (1,    bytes([0x02])),
        (127,  bytes([0xFE])),
        (128,  bytes([0x01, 0x02])),
        (16384,  bytes([0x01, 0x01, 0x02])),   # 16384 = 0b100_0000_0000_0000 -> chunks [0,0,1]
        ((1 << 28) - 1, bytes([0xFF, 0xFF, 0xFF, 0xFE])),  # 28 ones -> 4 x 0x7F chunks
    ]
    for v, enc in cases:
        br = BitReader(enc)
        got = br.serialize_int_packed()
        assert got == v, f"hand vector {v}: got {got} (enc {enc.hex()})"
    print("S3a SerializeIntPacked hand vectors: OK")


def test_int_packed_random():
    rng = random.Random(1234)
    for _ in range(10000):
        v = rng.randint(0, (1 << 32) - 1)
        br = BitReader(enc_int_packed(v))
        assert br.serialize_int_packed() == v, f"rand {v}"
    print("S3b SerializeIntPacked 10k random round-trip: OK")


def test_int_packed_straddle():
    # Encode at a non-byte-aligned bit position through the writer, then read
    # it back at the same position. Exercises the bit-position-aware reader path.
    for v in [0, 1, 127, 128, 5000, 1_000_000]:
        for align in [0, 1, 3, 7]:
            bw = BitWriter()
            for _ in range(align):
                bw.write_bit(0)
            bw.serialize_int_packed(v)
            # read back with matching alignment
            br = BitReader(bw.getvalue())
            for _ in range(align):
                br.read_bit()
            got = br.serialize_int_packed()
            assert got == v, f"straddle v={v} align={align} got={got}"
    print("S3c SerializeIntPacked non-byte-aligned decode: OK")


def test_serialize_int():
    # FBitReader::SerializeInt reads ceil(log2(max)) bits LSB-first.
    # For Max=10 (needs 4 bits): value 9 -> bits [1,0,0,1] LSB-first -> 0b1001=9.
    bw = BitWriter()
    bw.serialize_int(9, 10)
    br = BitReader(bw.getvalue())
    assert br.serialize_int(10) == 9
    # Max=2 (1 bit): value 1 -> bit [1]; Max=3 (2 bits): value 2 -> [0,1]=2.
    bw = BitWriter(); bw.serialize_int(1, 2)
    assert BitReader(bw.getvalue()).serialize_int(2) == 1
    bw = BitWriter(); bw.serialize_int(2, 3)
    assert BitReader(bw.getvalue()).serialize_int(3) == 2
    print("S4 SerializeInt range-compacted: OK")


def test_fstring():
    for s in ["", "hello", "WorldGravity", "Unreal Engine"]:
        bw = BitWriter(); bw.write_fstring(s)
        assert BitReader(bw.getvalue()).read_fstring() == s, s
    uni = "Größe—日本語"
    bw = BitWriter(); bw.write_fstring(uni)
    assert BitReader(bw.getvalue()).read_fstring() == uni, uni
    print("S5 FString round-trip (empty/ASCII/UTF-16): OK")


def test_fname():
    # string form: FString + int32 Number
    bw = BitWriter(); bw.write_fname("RootComponent", 1)
    d = BitReader(bw.getvalue()).read_fname()
    assert d == {"kind": "string", "name": "RootComponent", "number": 1}, d
    # hardcoded form: 1-bit + SerializeIntPacked index
    bw = BitWriter(); bw.write_fname("", 0, hardcoded_index=42)
    d = BitReader(bw.getvalue()).read_fname()
    assert d == {"kind": "hardcoded", "name_index": 42, "number": 0}, d
    # round-trip a sequence mixing both
    bw = BitWriter()
    bw.write_fname("SpawnPoint", 0)
    bw.write_fname("", 0, hardcoded_index=7)
    br = BitReader(bw.getvalue())
    assert br.read_fname()["name"] == "SpawnPoint"
    assert br.read_fname()["name_index"] == 7
    print("S6 network FName round-trip (string + hardcoded): OK")


def test_network_guid():
    # static flag = LSB of ObjectId; CreateFromIndex(NetIndex<<1 | static).
    for net_index, is_static in [(0, True), (5, True), (5, False), (123456, False)]:
        object_id = (net_index << 1) | (1 if is_static else 0)
        bw = BitWriter(); bw.write_network_guid(object_id)
        d = BitReader(bw.getvalue()).read_network_guid()
        assert d["object_id"] == object_id, (net_index, is_static, d)
        assert d["is_static"] == bool(is_static)
        assert d["is_dynamic"] == (object_id > 0 and not (object_id & 1))
    # invalid (0)
    bw = BitWriter(); bw.write_network_guid(0)
    d = BitReader(bw.getvalue()).read_network_guid()
    assert d["is_valid"] is False
    print("S7 FNetworkGUID static/dynamic LSB flag + CreateFromIndex: OK")


def test_int_packed64():
    for v in [0, 1, 127, 128, (1 << 35) - 1, (1 << 63) + (1 << 40) + 12345]:
        bw = BitWriter(); bw.serialize_int_packed64(v)
        got = BitReader(bw.getvalue()).serialize_int_packed64()
        assert got == v, f"intpacked64 {v} != {got}"
    # non-aligned
    for v in [123456789012345, 0, 7]:
        bw = BitWriter(); bw.write_bit(1); bw.serialize_int_packed64(v)
        br = BitReader(bw.getvalue()); br.read_bit()
        assert br.serialize_int_packed64() == v, v
    print("S8 SerializeIntPacked64 64-bit round-trip (incl. straddle): OK")


def test_bytes_and_error():
    br = BitReader(bytes([0xDE, 0xAD, 0xBE, 0xEF]))
    assert br.read_bytes(4) == bytes([0xDE, 0xAD, 0xBE, 0xEF])
    br2 = BitReader(bytes([0x01, 0x02]), size_in_bits=8)
    try:
        br2.read_bytes(2)
        raise AssertionError("expected error on short read")
    except BitReaderError:
        pass
    print("S9 read_bytes + error path: OK")


def test_trace():
    br = BitReader(bytes([0x01]))
    br.set_trace(True)
    _ = br.read_bits(8)
    tr = br.get_trace()
    assert len(tr) == 8, len(tr)
    assert [e.value for e in tr] == [1, 0, 0, 0, 0, 0, 0, 0]  # 0x01 LSB-first
    assert tr[0].byte_off == 0 and tr[0].bit_off == 0 and tr[0].n_bits == 1
    print("S10 trace logging captures per-bit position+value: OK")


if __name__ == "__main__":
    test_bit_order()
    test_read_bits()
    test_int_packed_hand_vectors()
    test_int_packed_random()
    test_int_packed_straddle()
    test_serialize_int()
    test_fstring()
    test_fname()
    test_network_guid()
    test_int_packed64()
    test_bytes_and_error()
    test_trace()
    print("\nALL BITREADER SELFTESTS PASSED (Phase 03)")
