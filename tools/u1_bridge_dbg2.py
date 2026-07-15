#!/usr/bin/env python3
"""Debug: dump raw payload bytes of the first package-map-export control bunch
in TyrReplay1, to understand TYR's actual export-bunch layout (the existing
read_net_field_exports throws 'index out of range')."""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import frame_walk as FW
import container as CM

f = "sample/TyrReplay1.replay"
c = CM.parse_container(f)
rep = [ch for ch in c.chunks if ch.type_name == "ReplayData"]
raw = open(f, "rb").read()
shown = 0
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
                if not (b.b_control and b.b_has_package_map_exports):
                    continue
                pl = b.reassembled_payload
                print(f"--- control bunch ch={b.ch_index} payload_len={len(pl)} ---")
                print("  hex[:96]:", pl[:96].hex())
                # how many int_packed groups are readable before garbage?
                ea = FW.ByteArchive(pl)
                for i in range(8):
                    try:
                        v = ea.int_packed()
                        print(f"  int_packed[{i}] = {v}  (tell {ea.tell()})")
                    except Exception as e:
                        print(f"  int_packed[{i}] ERR {e}")
                        break
                shown += 1
                if shown >= 3:
                    sys.exit(0)
