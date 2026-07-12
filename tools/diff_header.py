"""diff_header.py — find which Header-chunk byte offsets vary across samples.

Evidence-first: before naming any field we locate the boundary between the
constant prefix (same build → same defaulted/version fields) and the
per-file region (guid, level name, etc.).
"""

import glob
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tools.container import parse_container  # noqa: E402


def hdr_chunk(path):
    c = parse_container(path)
    for ch in c.chunks:
        if ch.type_name == "Header":
            with open(path, "rb") as f:
                f.seek(ch.data_offset)
                return f.read(ch.size_in_bytes)
    return None


def main():
    files = sorted(glob.glob(os.path.join(REPO, "sample", "*.replay")))
    hdrs = [(os.path.basename(f), hdr_chunk(f)) for f in files]
    sizes = set(len(h) for _, h in hdrs)
    print("sizes:", sizes)

    ref = hdrs[0][1]
    diffs = set()
    for _, h in hdrs:
        for i in range(len(ref)):
            if h[i] != ref[i]:
                diffs.add(i)
    diffs = sorted(diffs)
    print("num differing offsets:", len(diffs))
    print("first 30 diff offsets:", diffs[:30])
    print("last 10 diff offsets:", diffs[-10:])
    print("--- bytes [0x50:0x70] per file ---")
    for name, h in hdrs:
        print(name, h[0x50:0x70].hex())
    print("--- full hex of first 0x60 bytes of ref (TyrReplay1) ---")
    print(hdrs[0][1][:0x60].hex())


if __name__ == "__main__":
    main()
