"""diff_header_tail.py — characterize the variable portion of the Header chunk.

Constant prefix is [0, 0x54). We dump:
  - the constant prefix as hex+ascii (to reason about defaulted fields)
  - per-file the region [0x54, end) with offset map, splitting on the
    recognizable ASCII runs (Tyr+release, level name, WindowsClient, trailing 04 03)
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
    return b""


def ascii_view(b):
    return "".join(chr(x) if 32 <= x < 127 else "." for x in b)


def main():
    files = sorted(glob.glob(os.path.join(REPO, "sample", "*.replay")))
    hdrs = [(os.path.basename(f), hdr_chunk(f)) for f in files]

    print("==== CONSTANT PREFIX [0, 0x54) — same in all files ====")
    ref = hdrs[0][1][:0x54]
    print("hex:", ref.hex())
    print("asc:", ascii_view(ref))
    print()

    print("==== PER-FILE TAIL [0x54, end) ====")
    for name, h in hdrs:
        tail = h[0x54:]
        print(f"--- {name} (total {len(h)}, tail {len(tail)}) ---")
        print("  hex:", tail.hex())
        print("  asc:", ascii_view(tail))
        # try to locate known anchors
        idx_release = tail.find(b"Tyr+release")
        idx_win = tail.find(b"WindowsClient")
        print(f"  'Tyr+release' at tail-off {idx_release}; 'WindowsClient' at tail-off {idx_win}")
        if idx_release >= 0:
            before = tail[:idx_release]
            print(f"  bytes before 'Tyr+release': {before.hex()} (len {len(before)})")
        if idx_win >= 0:
            after = tail[idx_win + len(b"WindowsClient"):]
            print(f"  bytes after 'WindowsClient': {after.hex()} (len {len(after)})")
        print()


if __name__ == "__main__":
    main()
