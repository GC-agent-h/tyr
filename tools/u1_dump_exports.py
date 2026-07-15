#!/usr/bin/env python3
"""Dump the actual (handle, export_name, path_name) from TyrReplay1's
net_export_groups cache, and inspect handle value ranges + how many resolve to
gameplay class paths (/Game/..., _C, BP_). Also print the 2 blob handles that
DID match, to understand the mapping direction."""
from __future__ import annotations
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
import frame_walk as FW
import container as CM

f = "sample/TyrReplay1.replay"
c = CM.parse_container(f)
rep = [ch for ch in c.chunks if ch.type_name == "ReplayData"]
raw = open(f, "rb").read()
hmap = {}
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
        for g in getattr(fr, "net_export_groups", []) or []:
            ex = g.export
            if not ex or "handle" not in ex:
                continue
            h = ex["handle"]
            nm = ex.get("export_name")
            nm = nm.get("name") if isinstance(nm, dict) else nm
            hmap[h] = (nm, g.path_name)

print(f"total export handles: {len(hmap)}")
# handle value range
hs = sorted(hmap)
print(f"handle range: {hs[0]}..{hs[-1]}")
# how many look like gameplay class paths
game = [(h, v) for h, v in hmap.items()
        if v[1] and ("/Game/" in v[1] or "_C" in str(v[1]) or "BP_" in str(v[1]))]
print(f"gameplay-class-path exports: {len(game)}")
print("\nfirst 25 exports (handle, export_name, path_name):")
for h in hs[:25]:
    nm, pn = hmap[h]
    print(f"  {h:6d}  export_name={nm!r:40} path={pn}")
print("\nsample gameplay-class exports:")
for h, v in game[:20]:
    print(f"  {h:6d}  export_name={v[0]!r:40} path={v[1]}")
# the blob keys
blob = json.load(open("out/u1_blobs.json"))[f]
print("\nblob keys (first 8):", blob["keys"][:8])
print("matched blob keys:", [k for k in blob["keys"] if k in hmap])
