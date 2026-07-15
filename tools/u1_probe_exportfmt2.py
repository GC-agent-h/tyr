#!/usr/bin/env python3
"""Brute-force the per-export format of group0 in TyrReplay1. Group0 = class
/Script/Engine.WorldSettings, starts at tell=10 after num=194. We know:
  pni=1, we=1, fstring('/Script/Engine.WorldSettings'), then nin=22?? (suspect).
Actually let's re-locate group0 start precisely and walk exports trying:
  each export = u8 flags; if flags&1: handle=ikp, csum=u32, then name via
  StaticSerializeName (u8 b; if b&1: ikp name_index else fstring inline).
We'll try, at each export, BOTH interpretations and print the resulting name
candidate; the one that yields ASCII tells us the real layout."""
import sys; sys.path.insert(0, "tools")
import frame_walk as FW

raw = open("sample/TyrReplay1.replay", "rb").read()
data = raw[828 + 16: 828 + 307775]
# group0 starts right after num(194) which is 1 byte (0xc2 -> int_packed=194)
ar = FW.ByteArchive(data)
ar.i32(); ar.f32()        # level, time
num = ar.int_packed()     # 194
start = ar.tell()         # = 10
print("group0 starts at", start, "bytes:", data[start:start+60].hex())

def try_decode(buf):
    """Attempt to decode a sequence of exports assuming nin given; return list of
    (handle, name) or raise."""
    a = FW.ByteArchive(buf)
    out = []
    for _ in range(30):
        if a.at_end():
            break
        fl = a.u8()
        if fl == 0:
            # not exported; maybe end of group -> stop
            # but could be a 0 flag meaning export w/ no handle? treat as stop
            break
        if fl & 1:
            h = a.int_packed()
            cs = a.u32()
            # name
            b = a.u8()
            if b & 1:
                ni = a.int_packed()
                out.append((h, f"#hardcoded{ni}"))
            else:
                try:
                    nm = a.fstring()
                    out.append((h, nm))
                except Exception as e:
                    out.append((h, f"<fstr-err:{e}>"))
                    break
        else:
            # flag with b0 but not b1? skip 1 byte
            pass
    return out

print("decode from group0 start:", try_decode(data[start:start+200]))
