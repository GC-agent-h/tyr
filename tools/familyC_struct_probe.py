"""
familyC_struct_probe.py — rigorous search for Family C (08-0b) internal frame:
  (1) per-byte-position constancy across all records (after pl[2:]) -> which
      leading bytes are a fixed type tag vs high-entropy (GUID/var).
  (2) length-prefix search: is there a u8/u16 at a fixed offset whose value
      equals the byte count from that offset+size to the terminal 00?
      (would reveal a length-prefixed sub-structure, NON-tautological.)
  (3) trailing-run analysis: do records share a common terminal run?
ALL OBSERVATION.
"""
from __future__ import annotations
import sys, glob
from collections import Counter, defaultdict
import container as container_mod
import frame_walk as fw
import carrier_decode as cd


def main(argv):
    files = argv[1:] or sorted(glob.glob("sample/*.replay"))
    # per subtype: per-position modal byte + constancy; lengthprefix hits
    pos_const = {st: {} for st in (0x08, 0x09, 0x0a, 0x0b)}
    pos_modal = {st: {} for st in (0x08, 0x09, 0x0a, 0x0b)}
    lenset = {st: Counter() for st in (0x08, 0x09, 0x0a, 0x0b)}
    lprefix = {st: Counter() for st in (0x08, 0x09, 0x0a, 0x0b)}
    n = {st: 0 for st in (0x08, 0x09, 0x0a, 0x0b)}
    NPOS = 20
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
                        if not pl or len(pl) < 3 or pl[1] not in pos_const or pl[-1] != 0x00:
                            continue
                        st = pl[1]
                        content = pl[2:-1]  # exclude the subtype byte and terminal 00
                        n[st] += 1
                        lenset[st][len(content)] += 1
                        # per-position constancy over first NPOS bytes
                        for j in range(min(NPOS, len(content))):
                            pos_const[st].setdefault(j, 0)
                            pos_modal[st].setdefault(j, Counter())[content[j]] += 1
                            if pos_modal[st][j][content[j]] > pos_const[st][j]:
                                pos_const[st][j] = pos_modal[st][j][content[j]]
                        # length prefix search: at offset 0..9, u8 or u16 == remaining len
                        for off in range(0, min(10, len(content))):
                            rem = len(content) - off - 1  # bytes after a u8
                            if off + 1 <= len(content) and content[off] == rem:
                                lprefix[st][(off, "u8")] += 1
                            if off + 2 <= len(content):
                                val = int.from_bytes(content[off:off + 2], "little")
                                rem2 = len(content) - off - 2
                                if val == rem2:
                                    lprefix[st][(off, "u16")] += 1
    for st in (0x08, 0x09, 0x0a, 0x0b):
        if not n[st]:
            continue
        nn = n[st]
        print(f"\n=== subtype 0x{st:02x}  records={nn} ===")
        consts = []
        for j in range(NPOS):
            if j in pos_const[st]:
                cst = pos_const[st][j]
                frac = 100.0 * cst / nn
                consts.append((j, frac, pos_modal[st][j].most_common(1)[0][0]))
        # show positions that are >=90% constant
        near = [(j, round(f, 1), hex(b)) for j, f, b in consts if f >= 90.0]
        print(f"  positions >=90% constant (j,%,modalbyte): {near}")
        # show top length distribution
        print(f"  content-len top6: {lenset[st].most_common(6)}")
        # length prefix hits
        best = lprefix[st].most_common(4)
        print(f"  length-prefix hits (off,kind):n : {best}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
