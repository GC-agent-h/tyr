"""annotate_header_tail.py — clean offset-accurate dump of the Header chunk.

Reads the Header chunk, prints the constant prefix, the GUID, the mid
constant block, then walks the variable tail from 0x8C (empirically the
real start of the level list) reading:
  i32 level_count
  per entry: FString name, i32 time_ms
  then the trailing platform FString + 3-byte trailer
and prints every field with its absolute chunk offset.
"""

import glob
import os
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tools.container import parse_container  # noqa: E402


def i32(b, o):
    return struct.unpack_from("<i", b, o)[0]


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def i64(b, o):
    return struct.unpack_from("<q", b, o)[0]


def f32(b, o):
    return struct.unpack_from("<f", b, o)[0]


def fstring(b, o):
    slen = i32(b, o)
    o += 4
    if slen == 0:
        return "", o
    if slen < 0:
        n = -slen
        raw = b[o:o + n * 2]
        o += n * 2
        return raw.decode("utf-16-le", "replace"), o
    raw = b[o:o + slen]
    o += slen
    return raw.decode("latin-1", "replace"), o


def main():
    for p in sorted(glob.glob(os.path.join(REPO, "sample", "*.replay")))[:1]:
        c = parse_container(p)
        for ch in c.chunks:
            if ch.type_name == "Header":
                with open(p, "rb") as f:
                    f.seek(ch.data_offset)
                    b = f.read(ch.size_in_bytes)
                break
        n = len(b)
        print(f"=== {os.path.basename(p)} size={n} ===")
        print(f"[0x000,0x054) const prefix: {b[0:0x54].hex()}")
        print(f"[0x054,0x064) guid      : {b[0x54:0x64].hex()}")
        print(f"[0x064,0x08c) mid const : {b[0x64:0x8c].hex()}")
        print(f"    mid const ascii     : {b[0x64:0x8c].decode('latin-1','.')}")
        off = 0x8C
        cnt = i32(b, off)
        print(f"[0x{off:03x}] level_count (i32) = {cnt}")
        off += 4
        for k in range(max(cnt, 0)):
            slen = i32(b, off)
            nm, off2 = fstring(b, off)
            t = i32(b, off2)
            print(f"    level[{k}] len={slen} name={nm!r} time_ms={t} "
                  f"(off 0x{off:03x}->0x{off2+4:03x})")
            off = off2 + 4
        # after levels: dump the rest as a series of candidate primitives
        print(f"--- after levels, off=0x{off:03x} ({(n-off)} bytes left) ---")
        rest = b[off:]
        print("    hex:", rest.hex())
        print("    asc:", rest.decode("latin-1", "."))
        # try to read platform FString
        if off < n:
            plat, off2 = fstring(b, off)
            print(f"    platform FString @0x{off:03x}={plat!r} -> ends 0x{off2:03x}")
            print(f"    trailer hex:", b[off2:].hex(), "len", n - off2)


if __name__ == "__main__":
    main()
