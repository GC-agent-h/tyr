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

TOTAL = 0
body = None
for ch, n, b in extract_all("sample/TyrReplay1.replay"):
    if len(b) == 1936:
        body = b; break
TOTAL = len(body) * 8

class BR:
    def __init__(self, d): self.d = d; self.p = 0
    def bits(self, n):
        v = 0
        for i in range(n):
            v |= ((self.d[(self.p+i)>>3] >> ((self.p+i)&7)) & 1) << i
        self.p += n
        return v
    def pu64(self):
        bc = self.bits(3) + 1
        if bc*8 <= 32:
            return self.bits(bc*8)
        lo = self.bits(32); hi = self.bits(bc*8-32)
        return lo | (hi<<32)

def try_parse(lead_is_handle, start=0):
    r = BR(body); r.p = start
    recs = []
    for i in range(31):
        rec = {"i": i}
        if lead_is_handle or i > 0:
            rec["handle"] = r.pu64()
        rec["destroy"] = r.bits(3)
        rec["hasState"] = r.bits(1)
        if rec["hasState"]:
            rec["isInitial"] = r.bits(1)
            if rec["isInitial"]:
                rec["deltaComp"] = r.bits(1)
                if rec["deltaComp"]:
                    rec["baseline"] = r.bits(2)
        rec["bitpos"] = r.p
        recs.append(rec)
        # We can't decode creation-info+state without the binary deep-dive,
        # so stop after the header of each record.
        # Without knowing state length, cannot continue to next record reliably.
        break  # only first record header is reliably checkable
    return recs

print(f"TOTAL bits={TOTAL}")
print("\nModel A: blob starts at ROOT record (no leading handle):")
for rec in try_parse(False):
    print(" ", rec)
print("\nModel B: blob starts at a SUBOBJECT record (leading handle):")
for rec in try_parse(True):
    print(" ", rec)

# Determine which model gives a coherent first record:
# coherent initial snapshot => destroy=0, hasState=1, isInitial=1, deltaComp=1, baseline=0
def coherent(rec):
    return rec.get("destroy")==0 and rec.get("hasState")==1 and rec.get("isInitial")==1 and rec.get("deltaComp")==1 and rec.get("baseline")==0
ra = try_parse(False)[0]; rb = try_parse(True)[0]
print(f"\nModel A first-record coherent(initial-snapshot)? {coherent(ra)} -> {ra}")
print(f"Model B first-record coherent(initial-snapshot)? {coherent(rb)} -> {rb}")
