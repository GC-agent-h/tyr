#!/usr/bin/env python3
import sys; sys.path.insert(0, "tools")
import frame_walk as FW
raw = open("sample/TyrReplay1.replay", "rb").read()
# first ReplayData chunk at 828, skip 16-byte chunk header
data = raw[828 + 16: 828 + 307775]
ar = FW.ByteArchive(data)
lvl = ar.i32(); t = ar.f32()
print("level", lvl, "time", t, "tell", ar.tell())
num = ar.int_packed()
print("num groups", num, "tell", ar.tell())
seg = data[ar.tell(): ar.tell() + 200]
print("hex after num:", seg.hex())
print("ascii:", repr(seg))
# manual: group0 PathName FString
pn = ar.fstring(); print("group0 PathName =", pn)
pni = ar.int_packed(); print("PathNameIndex", pni, "tell", ar.tell())
nin = ar.int_packed(); print("NumExports", nin, "tell", ar.tell())
for i in range(min(nin, 6)):
    flags = ar.u8()
    h = None; cs = None; nm = None
    if flags & 1:
        h = ar.int_packed(); cs = ar.u32()
    b = ar.u8()
    if b & 1:
        nm_idx = ar.int_packed(); nm = "hardcoded#%d" % nm_idx
    else:
        s = ar.fstring(); num2 = ar.i32(); nm = s
    print(f"  export[{i}] flags={flags:#04x} handle={h} csum={cs} name={nm}")
