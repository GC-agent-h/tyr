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

class BR:
    def __init__(self, d, p): self.d=d; self.p=p
    def bits(self, n):
        v=0
        for i in range(n):
            v |= ((self.d[(self.p+i)>>3] >> ((self.p+i)&7)) & 1) << i
        self.p += n; return v
    def pu64(self):
        bc=self.bits(3)+1
        if bc*8<=32: return self.bits(bc*8)
        lo=self.bits(32); hi=self.bits(bc*8-32); return lo|(hi<<32)

def first_rec_ok(start, lead_handle):
    r = BR(body, start)
    if start + 64 > TOTAL: return None
    try:
        if lead_handle:
            h = r.pu64()
            if h > (1<<40): return None  # implausibly large for a static handle
        destroy = r.bits(3)
        if destroy != 0: return None
        hs = r.bits(1)
        if hs != 1: return None
        ini = r.bits(1)
        if ini != 1: return None
        dc = r.bits(1)
        if dc != 1: return None
        bl = r.bits(2)
        if bl != 0: return None
        return r.p  # coherent
    except Exception:
        return None

print(f"TOTAL bits={TOTAL}")
print("Offset scan (0..63) for a coherent initial-snapshot first record:")
hitsA=[]; hitsB=[]
for off in range(0, 64):
    if first_rec_ok(off, False): hitsA.append(off)
    if first_rec_ok(off, True): hitsB.append(off)
print(f"  Model A (root, no handle): coherent offsets = {hitsA}")
print(f"  Model B (subobject, handle): coherent offsets = {hitsB}")
if not hitsA and not hitsB:
    print("  => NO coherent initial-snapshot record at ANY offset 0..63.")
    print("  => CONCLUSION: blob does NOT begin with an Iris per-object record header (root or subobject).")
    print("     TYR uses a CUSTOM envelope; handles in carrier header, blob = custom state payload.")
else:
    print("  => coherent record found -> Iris envelope plausible at those offsets.")
