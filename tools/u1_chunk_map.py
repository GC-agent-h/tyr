#!/usr/bin/env python3
"""Map raw-file offsets that contain class-path FStrings (920, 403680) to the
replay CHUNK that contains them, and dump the chunk type layout. The class paths
are in a chunk other than ReplayData bunches (the NetGUID/path cache stored in
checkpoint/initialization data)."""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import container as CM

f = "sample/TyrReplay1.replay"
c = CM.parse_container(f)
chs = c.chunks
print(f"{len(chs)} chunks")
for ch in chs:
    lo = ch.data_offset
    hi = ch.data_offset + ch.size_in_bytes
    print(f"  type={ch.type_name:20} off={lo:9} size={ch.size_in_bytes:9} "
          f"[{lo}..{hi}]")
# which chunk holds 920 and 403680?
for target in (920, 403680):
    owner = None
    for ch in chs:
        if ch.data_offset <= target < ch.data_offset + ch.size_in_bytes:
            owner = ch
            break
    print(f"\noffset {target} is in: {owner.type_name if owner else 'NONE'} "
          f"(off={owner.data_offset}, size={owner.size_in_bytes})")
