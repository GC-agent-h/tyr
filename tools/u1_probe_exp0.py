#!/usr/bin/env python3
import sys; sys.path.insert(0, "tools")
import frame_walk as FW

raw = open("sample/TyrReplay1.replay", "rb").read()
data = raw[828 + 16: 828 + 307775]
ar = FW.ByteArchive(data)
ar.i32(); ar.f32()
num = ar.int_packed()
# group0
pni = ar.int_packed(); we = ar.int_packed()
print("pni", pni, "we", we, "tell", ar.tell())
path = ar.fstring(); print("path", repr(path), "tell", ar.tell())
nin = ar.int_packed(); print("nin", nin, "tell", ar.tell())
print("next 40 bytes:", data[ar.tell(): ar.tell()+40].hex())
# decode export 0 manually
def rd_export(a):
    fl = a.u8(); print("  flags", fl, "tell", a.tell())
    if fl & 1:
        h = a.int_packed(); cs = a.u32()
        print("  handle", h, "csum", cs, "tell", a.tell())
        b = a.u8(); print("  namebyte", hex(b), "tell", a.tell())
        if b & 1:
            ni = a.int_packed(); print("  hardname#", ni)
        else:
            nm = a.fstring(); print("  name", repr(nm), "tell", a.tell())
    return fl
for i in range(3):
    print(f"export {i}:")
    rd_export(ar)
    print("  after export, next 24:", data[ar.tell(): ar.tell()+24].hex())
