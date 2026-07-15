#!/usr/bin/env python3
"""Locate TYR's real NetFieldExport/package-map export stream. The 1-byte
b_has_package_map_exports bunches are acks; the actual export stream is a larger
control bunch (probably on the package-map channel). Scan ALL control bunches,
largest first, try parsing as NetFieldExports, and report any that yield
exported handles with a class-path-like export_name. Also dump the top-5 largest
control bunches' first 32 bytes for manual layout ID."""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import frame_walk as FW
import container as CM

f = "sample/TyrReplay1.replay"
c = CM.parse_container(f)
rep = [ch for ch in c.chunks if ch.type_name == "ReplayData"]
raw = open(f, "rb").read()
allctrl = []
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
                if b.b_control:
                    allctrl.append((len(b.reassembled_payload), b.ch_index,
                                    b.b_has_package_map_exports, b.b_open,
                                    b.reassembled_payload))
allctrl.sort(reverse=True)
print(f"total control bunches={len(allctrl)}")
print("top 6 by size:")
for L, ch, pm, op, pl in allctrl[:6]:
    print(f"  L={L} ch={ch} pmap={pm} open={op} head={pl[:32].hex()}")
    # try parse as net field exports
    ea = FW.ByteArchive(pl)
    try:
        groups = FW.read_net_field_exports(ea)
        got = []
        for g in groups:
            ex = g.export
            if ex and ex.get("exported") and "handle" in ex:
                nm = ex.get("export_name")
                nm = nm.get("name") if isinstance(nm, dict) else nm
                got.append((ex["handle"], nm, g.path_name))
        if got:
            print(f"    -> PARSED {len(groups)} groups, {len(got)} exports: {got[:6]}")
    except Exception as e:
        print(f"    -> parse err: {str(e)[:50]}")
