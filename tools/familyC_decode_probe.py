"""
familyC_decode_probe.py — characterize Family C (xx08-0b, 100% terminal-00,
774k bunches, ~50% of all traffic) INTERNAL frame, per sub-type
pl[0] in {0x08,0x09,0x0a,0x0b}.

We already established (ADDENDUM 3b): Family C is NOT the U1 anchor (no A-key
link above chance, 0 ASCII). So this is an independent structured family to
decode at the FRAME level (self-validating, like Family B).

For each sub-type, collect content = pl[2:-1] and analyze:
  - length histogram (is it a few fixed lengths per sub-type? variable?)
  - first-byte (pl[2]) distribution — a sub-sub-type or a count?
  - presence of a length prefix (does a u8/u16 somewhere equal len(content)-k?)
  - second-half structure (terminal runs, repeats)
Goal: find a consistent internal framing per sub-type -> build decoder next.

ALL OBSERVATION.
"""
from __future__ import annotations
import os, sys, glob
from collections import Counter, defaultdict
import container as container_mod
import frame_walk as fw
import carrier_decode as cd

def main(argv):
    files = argv[1:] or sorted(glob.glob("sample/*.replay"))
    # per sub-type: lengths, firstbyte, lenprefix candidate offsets
    sub_types = {0x08: "08", 0x09: "09", 0x0a: "0a", 0x0b: "0b"}
    stats = {st: {"len": Counter(), "first": Counter(),
                   "lenprefix_off": Counter(), "n": 0}
             for st in sub_types}
    for path in files:
        c = container_mod.parse_container(path)
        rep = [ch for ch in c.chunks if ch.type_name == "ReplayData"]
        raw = open(path, "rb").read()
        for ch in rep:
            data = raw[ch.data_offset: ch.data_offset + ch.size_in_bytes]
            ar = fw.ByteArchive(data)
            ar.bytes(16)
            while not ar.at_end() and (len(data) - ar.tell()) >= 12:
                fstart = ar.tell()
                try:
                    fr, _ = fw.read_frame(ar, False, False)
                except Exception:
                    break
                if fr is None or ar.tell() <= fstart:
                    break
                for pkt in fr.packets:
                    for b in pkt.bunches:
                        pl = b.reassembled_payload
                        if not pl:
                            continue
                        cls = cd.classify(pl)
                        if cls != "C_xx08_0b" or not cd.familyC_validate(pl):
                            continue
                        st = pl[1]
                        if st not in stats:
                            continue
                        content = pl[2:-1]
                        L = len(content)
                        s = stats[st]
                        s["n"] += 1
                        s["len"][L] += 1
                        if L:
                            s["first"][content[0]] += 1
                        # does any u8/u16 window equal L (a self-length prefix)?
                        for off in range(0, min(L, 4)):
                            if off + 1 < L and int.from_bytes(
                                    content[off:off + 2], "little") == L:
                                s["lenprefix_off"][off] += 1
                                break
                            if content[off] == L:
                                s["lenprefix_off"][off] += 1
                                break
    for st in sub_types:
        s = stats[st]
        print(f"=== sub-type 0x{st:02x} (n={s['n']}) ===")
        print(f"  len hist (top8): {s['len'].most_common(8)}")
        print(f"  first-byte dist (top8): {[(hex(k),v) for k,v in s['first'].most_common(8)]}")
        print(f"  self-len-prefix offset hits: {s['lenprefix_off'].most_common(6)}")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))
