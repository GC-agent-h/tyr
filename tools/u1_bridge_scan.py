#!/usr/bin/env python3
"""Scan ALL control bunches in TyrReplay1 for a NetFieldExport stream whose
handles fall in the blob's range (580..640). The 'b_has_package_map_exports'
flagged bunches are 1-byte acks; the real export data is elsewhere. Try parsing
every control bunch payload as exports and collect handle->name for handles in
range. Reports which bunch carries the export stream."""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import frame_walk as FW
import container as CM

f = "sample/TyrReplay1.replay"
c = CM.parse_container(f)
rep = [ch for ch in c.chunks if ch.type_name == "ReplayData"]
raw = open(f, "rb").read()
hits = {}
carriers = []
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
                if len(pl) < 4:
                    continue
                ea = FW.ByteArchive(pl)
                try:
                    groups = FW.read_net_field_exports(ea)
                except Exception:
                    continue
                found = False
                for g in groups:
                    ex = g.export
                    if ex and ex.get("exported") and "handle" in ex:
                        h = ex["handle"]
                        nm = ex.get("export_name")
                        nm = nm.get("name") if isinstance(nm, dict) else nm
                        if 580 <= h <= 640:
                            hits[h] = nm
                            found = True
                if found and b.ch_index not in carriers:
                    carriers.append(b.ch_index)
print("handles 580..640 resolved:")
for h in sorted(hits):
    print(f"  {h} -> {hits[h]}")
print("carrying control-bunch channels:", carriers[:10])
print("total resolved in range:", len(hits))
