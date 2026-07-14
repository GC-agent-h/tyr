import sys, random
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

BODY = None
for ch, n, b in extract_all("sample/TyrReplay1.replay"):
    if len(b) == 1936:
        BODY = b; break
TOTAL = len(BODY) * 8

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

def first_rec_ok(data, start, lead_handle):
    r = BR(data, start)
    if start + 64 > TOTAL: return False
    try:
        if lead_handle:
            h = r.pu64()
            if h > (1<<40): return False
        if r.bits(3)!=0: return False
        if r.bits(1)!=1: return False
        if r.bits(1)!=1: return False
        if r.bits(1)!=1: return False
        if r.bits(2)!=0: return False
        return True
    except Exception:
        return False

REAL_A = sum(1 for o in range(64) if first_rec_ok(BODY, o, False))
REAL_B = sum(1 for o in range(64) if first_rec_ok(BODY, o, True))
print(f"REAL data: Model A coherent offsets={REAL_A}, Model B coherent offsets={REAL_B}")

def run_control(seed):
    random.seed(seed)
    arr = list(BODY); random.shuffle(arr)
    data = bytes(arr)
    a = sum(1 for o in range(64) if first_rec_ok(data, o, False))
    b = sum(1 for o in range(64) if first_rec_ok(data, o, True))
    return a, b

print("Random-shuffle control (200 trials):")
totA=totB=0
for s in range(200):
    a,b = run_control(s); totA+=a; totB+=b
print(f"  mean coherent offsets/run: Model A={totA/200:.2f}, Model B={totB/200:.2f}")
print(f"  real Model B hits={REAL_B}; if random mean << {REAL_B} => SIGNAL; if ~{REAL_B} => COINCIDENCE.")
