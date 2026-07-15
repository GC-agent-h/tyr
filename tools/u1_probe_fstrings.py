#!/usr/bin/env python3
"""Empirically recover TYR's NetFieldExport group grammar by locating every
FString in the first frame's export region and showing the bytes just BEFORE
each (the varints/u32s that are the int_packed indices & counts)."""
import sys; sys.path.insert(0, "tools")
import frame_walk as FW

raw = open("sample/TyrReplay1.replay", "rb").read()
data = raw[828 + 16: 828 + 307775]
# find all FString boundaries: scan for plausible FString = i32 len (could be
# negative for inline). We'll find ASCII runs preceded by a 4-byte little-endian
# length that matches the run length.
def find_fstrings(buf, maxscan=20000):
    out = []
    i = 0
    while i + 4 < maxscan:
        L = int.from_bytes(buf[i:i+4], "little", signed=True)
        if 1 <= L <= 200 and buf[i+4:i+4+L].isascii() and buf[i+4+L:i+4+L+1] == b"\x00":
            out.append((i, L, buf[i+4:i+4+L].decode()))
            i += 4 + L + 1
            continue
        i += 1
    return out

fs = find_fstrings(data[8:8+20000])  # start after num-groups varint (~2 bytes)
# fs are relative to data[8]; convert to absolute-in-data
print("FStrings found in first 20KB of export region:")
for off, L, s in fs[:25]:
    abs_off = 8 + off
    # show 6 bytes before (the varints/u32 that precede this FString)
    pre = data[max(0,abs_off-8):abs_off]
    print(f"  off={abs_off:5d} pre={pre.hex():16} len={L:3d}  {s[:40]}")
