import sys
sys.path.insert(0, "tools")
import frame_walk as FW, container as CM

def extract_all(replay):
    out = []
    c = CM.parse_container(replay)
    rep = [ch for ch in c.chunks if ch.type_name == "ReplayData"]
    raw = open(replay, "rb").read()
    for ch in rep:
        data = raw[ch.data_offset: ch.data_offset + ch.size_in_bytes]
        ar = FW.ByteArchive(data); ar.bytes(16)
        while not ar.at_end() and (len(data) - ar.tell()) >= 12:
            fstart = ar.tell()
            try:
                fr, _ = FW.read_frame(ar, False, False)
            except Exception:
                break
            if fr is None or ar.tell() <= fstart:
                break
            for pkt in fr.packets:
                for b in pkt.bunches:
                    pl = b.reassembled_payload
                    if len(pl) >= 2 and pl[:2] != b"\x01\x00":
                        n = int.from_bytes(pl[0:2], "little")
                        if 1 <= n <= 2000 and len(pl) >= 2 + 2 * n + 1:
                            body = pl[2 + 2 * n:]
                            out.append((ch.index, n, bytes(body)))
    return out

def read_bits_at(data, bitpos, n):
    val = 0
    for i in range(n):
        byte = data[(bitpos + i) >> 3]
        bit = (byte >> ((bitpos + i) & 7)) & 1
        val |= bit << i
    return val

def read_packed_uint64(data, bitpos):
    """Faithful ReadPackedUint64 (NetBitStreamUtil.cpp:51-67)."""
    bytecount = read_bits_at(data, bitpos, 3) + 1
    bitcount = bytecount * 8
    if bitcount <= 32:
        val = read_bits_at(data, bitpos + 3, bitcount)
    else:
        lo = read_bits_at(data, bitpos + 3, 32)
        hi = read_bits_at(data, bitpos + 3 + 32, bitcount - 32)
        val = lo | (hi << 32)
    return val, 3 + bitcount

allb = extract_all("sample/TyrReplay1.replay")
ch, n, body = [b for b in allb if len(b[2]) == 1936][0]
TOTAL = len(body) * 8
print(f"channel={ch} n_handles={n} body={len(body)}B total_bits={TOTAL}")

# Scan: try root handle as ReadPackedUint64 at bit 1 (after bIsDestructionInfo=0).
# For each plausible handle width, compute batch-size-field offset and check invariant:
#   offset_field + 16 + batchsize == TOTAL
print("\nScan for stock-envelope 16-bit batch-size invariant (offset_field + 16 + batchsize == TOTAL):")
found = []
# brute force the root handle width: handle can be 1..N bytes => field at bit 1 + (3+8k)
for k in range(0, 4):  # 1..4 bytes
    handle_bitlen = 3 + 8 * (k + 1)
    field_off = 1 + handle_bitlen
    if field_off + 16 > TOTAL:
        break
    batchsize = read_bits_at(body, field_off, 16)
    end = field_off + 16 + batchsize
    ok = abs(end - TOTAL) <= 8
    # also decode the handle value
    hv, _ = read_packed_uint64(body, 1)
    print(f"  rootHandleBytes={k+1} field_bitoff={field_off} -> batchsize={batchsize} end_bit={end} match={ok} (rootHandleVal={hv})")
    if ok:
        found.append((k, field_off, batchsize, hv))

if not found:
    print("  NO batch-size invariant match -> stock single-batch envelope UNLIKELY (custom envelope).")
else:
    print(f"  MATCH at {found} -> stock single-batch envelope CONSISTENT.")
