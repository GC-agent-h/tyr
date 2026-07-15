#!/usr/bin/env python3
"""Tolerant group-by-group scan of the NetFieldExport stream in TyrReplay1.
For each of the 194 groups, read pni(ikp), we(ikp); if we: fstring path,
ikp nin; then try to read nin exports but cap at a sane max and catch errors.
Report the (pni, we, path, nin) per group to find the desync point."""
import sys; sys.path.insert(0, "tools")
import frame_walk as FW

raw = open("sample/TyrReplay1.replay", "rb").read()
data = raw[828 + 16: 828 + 307775]
ar = FW.ByteArchive(data)
lvl = ar.i32(); t = ar.f32()
num = ar.int_packed()
print("num", num, "tell", ar.tell())
for gi in range(num):
    try:
        pni = ar.int_packed()
        we = ar.int_packed()
        path = None; nin = 0
        if we:
            path = ar.fstring()
            nin = ar.int_packed()
        # read nin exports (best-effort)
        exp_handles = []
        ok = True
        for ei in range(nin):
            try:
                fl = ar.u8()
                if fl & 1:
                    h = ar.int_packed(); cs = ar.u32()
                    nm = ar.fstring()
                    exp_handles.append((h, nm[:20]))
            except Exception as e:
                ok = False
                print(f"    export {ei} ERR: {e} (tell {ar.tell()}, fl={fl if 'fl' in dir() else '?'})")
                break
        print(f"g{gi:3d} pni={pni} we={we} path={path!r:45} nin={nin:3d} "
              f"handles={exp_handles[:4]}{'...' if len(exp_handles)>4 else ''} {'ERR' if not ok else ''} tell={ar.tell()}")
    except Exception as e:
        print(f"g{gi} THREW at tell {ar.tell()}: {e}")
        break
