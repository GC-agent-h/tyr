#!/usr/bin/env python3
"""Tolerant manual decode of the first NetFieldExport group in TyrReplay1 to
nail TYR's exact grammar. Walks: num=int_packed(194); then for each group:
try several candidate orderings and print what each yields, so we can see the
real layout (where the class PathName FString sits, where handles are)."""
import sys; sys.path.insert(0, "tools")
import frame_walk as FW

raw = open("sample/TyrReplay1.replay", "rb").read()
data = raw[828 + 16: 828 + 307775]
ar = FW.ByteArchive(data)
lvl = ar.i32(); t = ar.f32()
num = ar.int_packed()
print("num groups", num, "at tell", ar.tell())

# Save position, decode group 0 field-by-field with raw inspection.
start = ar.tell()
seg = data[start: start + 80]
print("raw group0 bytes:", seg.hex())

# Candidate A: int_packed(pni), int_packed(we), if we: fstring(path), int_packed(nin), exports...
a = FW.ByteArchive(data[start:])
pni = a.int_packed(); we = a.int_packed()
print(f"\n[A] pni={pni} we={we} tell={a.tell()}")
if we:
    try:
        pn = a.fstring(); print("   path(fstring)=", repr(pn), "tell", a.tell())
    except Exception as e:
        print("   fstring err", e)
    nin = a.int_packed(); print("   nin=", nin, "tell", a.tell())
    # first export
    try:
        fl = a.u8(); print("   export0 flags=", fl)
        if fl & 1:
            h = a.int_packed(); cs = a.u32()
            print("   export0 handle=", h, "csum=", cs, "tell", a.tell())
            nm = a.fstring(); print("   export0 name=", repr(nm))
    except Exception as e:
        print("   export0 err", e)

# Candidate B: the class PathName FString comes FIRST (stock UE order)
b = FW.ByteArchive(data[start:])
try:
    pn = b.fstring(); print(f"\n[B] first-fstring path={repr(pn)} tell={b.tell()}")
    pni = b.int_packed(); nin = b.int_packed()
    print("   pni=", pni, "nin=", nin, "tell", b.tell())
except Exception as e:
    print("[B] err", e)
