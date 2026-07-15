#!/usr/bin/env python3
"""Search ALL bunches (any channel, control or data) in TyrReplay1 for byte-aligned
class-path FStrings (BP_*, /Game/..., *_C, BlueprintGeneratedClass). If the
package-map export stream is byte-aligned, this recovers the export->class names.
Reports the channels/positions where class paths appear, plus any int just before
that could be the export handle."""
from __future__ import annotations
import os, sys, re
sys.path.insert(0, os.path.dirname(__file__))
import frame_walk as FW
import container as CM

f = "sample/TyrReplay1.replay"
c = CM.parse_container(f)
rep = [ch for ch in c.chunks if ch.type_name == "ReplayData"]
raw = open(f, "rb").read()
tok_re = re.compile(rb"(BP_[A-Za-z0-9_]+|/Game/[ -~]+|BlueprintGeneratedClass|[A-Za-z0-9_]+_C)")
found = {}
for ch in rep:
    data = raw[ch.data_offset: ch.data_offset + ch.size_in_bytes]
    ar = FW.ByteArchive(data)
    ar.bytes(16)
    while not ar.at_end() and (len(data) - ar.tell()) >= 12:
        before = ar.tell()
        try:
            fr, _ = FW.read_frame(ar, False, False)
        except Exception:
            break
        if fr is None or ar.tell() <= before:
            break
        for pkt in fr.packets:
            for b in pkt.bunches:
                pl = b.reassembled_payload
                if len(pl) < 8:
                    continue
                for m in tok_re.finditer(pl):
                    s = m.group()
                    if len(s) >= 6 and (b"_C" in s or b"BP_" in s or b"/Game/" in s):
                        found.setdefault(s, 0)
                        found[s] += 1
print(f"class-path-like tokens anywhere in bunches: {len(found)}")
for s, n in sorted(found.items(), key=lambda kv: -kv[1])[:30]:
    print(f"  {n:4d}  {s.decode('latin1')[:70]}")
