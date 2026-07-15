#!/usr/bin/env python3
import sys, traceback; sys.path.insert(0, "tools")
import frame_walk as FW, container as CM

raw = open("sample/TyrReplay1.replay", "rb").read()
c = CM.parse_container("sample/TyrReplay1.replay")
ch = [x for x in c.chunks if x.type_name == "ReplayData"][0]
data = raw[ch.data_offset: ch.data_offset + ch.size_in_bytes]
ar = FW.ByteArchive(data)
ar.bytes(16)
try:
    fr, consumed = FW.read_frame(ar, False, False)
    print("OK frame: groups=", len(fr.net_export_groups) if fr else None)
    if fr:
        for g in fr.net_export_groups[:3]:
            print("  group path=", repr(g.path_name), "nin=", g.num_exports_in_group,
                  "export=", g.export)
except Exception as e:
    traceback.print_exc()
