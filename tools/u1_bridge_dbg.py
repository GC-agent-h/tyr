#!/usr/bin/env python3
"""Debug: enumerate control bunches in TyrReplay1 and see which carry
NetFieldExports, and whether b_has_package_map_exports is ever set."""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import frame_walk as FW
import container as CM

f = "sample/TyrReplay1.replay"
c = CM.parse_container(f)
rep = [ch for ch in c.chunks if ch.type_name == "ReplayData"]
raw = open(f, "rb").read()
ctrl = 0
exp_ctrl = 0
pmap_flags = 0
sample_exp = []
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
                ctrl += 1
                if b.b_has_package_map_exports:
                    pmap_flags += 1
                    pl = b.reassembled_payload
                    ea = FW.ByteArchive(pl)
                    try:
                        groups = FW.read_net_field_exports(ea)
                        exp_ctrl += 1
                        for g in groups[:2]:
                            ex = g.export
                            if ex and ex.get("exported"):
                                sample_exp.append((ex.get("handle"),
                                                   ex.get("export_name")))
                    except Exception as e:
                        if exp_ctrl == 0:
                            sample_exp.append(("PARSE_ERR", str(e)[:60]))
print(f"control bunches={ctrl}  with b_has_package_map_exports={pmap_flags}  "
      f"successfully parsed as exports={exp_ctrl}")
for s in sample_exp[:10]:
    print("  export:", s)
