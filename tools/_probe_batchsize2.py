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

body = None
for ch, n, b in extract_all("sample/TyrReplay1.replay"):
    if len(b) == 1936:
        body = b; break
TOTAL = len(body) * 8

def rbits(d, p, n):
    v=0
    for i in range(n):
        v |= ((d[(p+i)>>3] >> ((p+i)&7)) & 1) << i
    return v

def rpu64(d, p):
    bc = rbits(d, p, 3) + 1
    if bc*8 <= 32:
        return rbits(d, p+3, bc*8)
    lo = rbits(d, p+3, 32); hi = rbits(d, p+3+32, bc*8-32)
    return lo | (hi<<32)

# Airtight stock-batch refutation across all start offsets + 4 root-handle widths.
# Stock batch: [bIsDestructionInfo(1b)][WriteNetRefHandleId(root)=WritePackedUint64 (3+8k bits)][WriteBits(0,16) = batchsize placeholder]
# Filled: batchsize = bits after placeholder => (placeholder_off + 16) + batchsize == TOTAL.
matches = []
for off in range(0, 64):
    for k in range(0, 5):  # root handle 1..5 bytes
        handle_bits = 3 + 8*(k+1)
        field_off = off + 1 + handle_bits  # +1 for bIsDestructionInfo
        if field_off + 16 > TOTAL: continue
        batchsize = rbits(body, field_off, 16)
        end = field_off + 16 + batchsize
        # also sanity: bIsDestructionInfo should be 0 (not destruction info)
        if rbits(body, off, 1) != 0: continue
        if abs(end - TOTAL) <= 8:
            matches.append((off, k+1, batchsize, end))
print(f"TOTAL bits={TOTAL}")
print(f"Stock-batch 16-bit-batchsize invariant matches across offsets 0..63, handle 1..5B: {len(matches)}")
if matches:
    print("  MATCHES (would mean stock batch plausible):", matches[:5])
else:
    print("  NO MATCHES -> stock single Iris batch envelope REFUTED (model-correct, prefix-shift robust).")
