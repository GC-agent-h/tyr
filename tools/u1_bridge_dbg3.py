#!/usr/bin/env python3
"""Find the control bunches with the LARGEST payloads (the real export/NetFieldExport
stream, not the 1-byte acks) in TyrReplay1, and dump their hex + first fields."""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import frame_walk as FW
import container as CM

f = "sample/TyrReplay1.replay"
c = CM.parse_container(f)
rep = [ch for ch in c.chunks if ch.type_name == "ReplayData"]
raw = open(f, "rb").read()
big = []
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
                if not b.b_control:
                    continue
                pl = b.reassembled_payload
                big.append((len(pl), b.ch_index, b.b_open, b.b_has_package_map_exports, pl))
big.sort(reverse=True)
print("top 12 control bunches by payload size:")
for L, ch, op, pm, pl in big[:12]:
    print(f"  L={L} ch={ch} bOpen={op} pmap={pm} hex[:48]={pl[:48].hex()}")
