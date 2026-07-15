#!/usr/bin/env python3
"""Confirm group0's 22 exports decode to ASCII property names if blob length is
read as int_packed (not i32). This nails the FNetFieldExport blob format."""
import sys; sys.path.insert(0, "tools")
import frame_walk as FW

raw = open("sample/TyrReplay1.replay", "rb").read()
data = raw[828 + 16: 828 + 307775]
ar = FW.ByteArchive(data)
ar.i32(); ar.f32()
num = ar.int_packed()
pni = ar.int_packed(); we = ar.int_packed()
path = ar.fstring(); nin = ar.int_packed()
print("group0 path", repr(path), "nin", nin)

def read_export(a, blob_len_is_packed):
    fl = a.u8()
    h = nm = None; cs = None; blen = 0
    if fl & 1:
        h = a.int_packed(); cs = a.u32()
        b = a.u8()
        if b & 1:
            nm = "#hard%d" % a.int_packed()
        else:
            nm = a.fstring()
    if fl & 2:
        blen = a.int_packed() if blob_len_is_packed else a.i32()
        a.bytes(blen)
    return fl, h, cs, nm, blen

names = []
for i in range(nin):
    try:
        fl, h, cs, nm, blen = read_export(ar, True)
        names.append((i, fl, h, nm, blen))
    except Exception as e:
        print("  export", i, "ERR", e, "at tell", ar.tell())
        break
print("decoded with blob=int_packed:")
for i, fl, h, nm, blen in names[:25]:
    print(f"  [{i}] flags={fl} handle={h} name={nm!r} blob={blen}")
