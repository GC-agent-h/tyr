"""
familyC_dump.py — dump real Family-C (pl[1] in 08-0b, terminal-00) records,
per subtype, to find the byte-level internal frame. OBSERVATION ONLY.
"""
from __future__ import annotations
import sys, glob
import container as container_mod
import frame_walk as fw
import carrier_decode as cd


def main(argv):
    files = argv[1:2] or ["sample/TyrReplay1.replay"]
    want = {0x08, 0x09, 0x0a, 0x0b}
    per = {w: [] for w in want}
    c = container_mod.parse_container(files[0])
    rep = [ch for ch in c.chunks if ch.type_name == "ReplayData"]
    raw = open(files[0], "rb").read()
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
                    if not pl or len(pl) < 3:
                        continue
                    if pl[1] in want and pl[-1] == 0x00:
                        st = pl[1]
                        if len(per[st]) < 25:
                            per[st].append(pl)
    for st in sorted(per):
        print(f"\n==== subtype 0x{st:02x} ({len(per[st])} shown) ====")
        for pl in per[st]:
            # show pl[0], pl[1], then content
            print(f"  len={len(pl):3d} pl0={pl[0]:02x} | {pl[2:].hex()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
