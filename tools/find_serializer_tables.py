#!/usr/bin/env python3
"""Locate Iris NetSerializer function-pointer tables in TYR's Shipping binary.

With /GL (LTCG), __FILE__ strings are dead data (no live lea/reloc refs), so we
anchor on the serializer DISPATCH TABLES instead: per-type NetSerializer
Serialize/Deserialize/Quantize/Dequantize stubs are stored as absolute VA
pointers in .rdata, hence they appear in the .reloc DIR64 table. Scanning .rdata
for contiguous runs of pointers into .text yields the serializer vtable region.

Outputs /tmp/serializer_tables.json : { table_rva_hex : [fn_va, ...], ... }
"""
import json
import pefile
import struct
from collections import defaultdict

BIN = "Binaries/Win64/TyrClient-Win64-Shipping.exe"


def main():
    pe = pefile.PE(BIN, fast_load=True)
    raw = open(BIN, "rb").read()
    IB = pe.OPTIONAL_HEADER.ImageBase
    text = next(s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text")
    text_va = text.VirtualAddress
    text_vsize = text.Misc_VirtualSize

    def rva_to_raw(rva):
        for s in pe.sections:
            if s.VirtualAddress <= rva < s.VirtualAddress + s.Misc_VirtualSize:
                return s.PointerToRawData + (rva - s.VirtualAddress)
        return None

    # parse .reloc DIR64 -> target VAs that land in .text
    reloc = next(s for s in pe.sections if s.Name.rstrip(b"\x00") == b".reloc")
    data = raw[reloc.PointerToRawData: reloc.PointerToRawData + reloc.SizeOfRawData]
    targets = set()
    pos = 0
    while pos + 8 <= len(data):
        pv = struct.unpack_from("<I", data, pos)[0]
        bs = struct.unpack_from("<I", data, pos + 4)[0]
        if bs == 0:
            break
        off = pos + 8
        end = pos + bs
        while off + 2 <= end:
            e = struct.unpack_from("<H", data, off)[0]
            if e >> 12 == 0xA:
                lr = rva_to_raw(pv + (e & 0xFFF))
                if lr is not None and lr + 8 <= len(raw):
                    v = struct.unpack_from("<Q", raw, lr)[0]
                    if IB + text_va <= v < IB + text_va + text_vsize:
                        targets.add(v)
            off += 2
        pos += bs

    rd = next(s for s in pe.sections if s.Name.rstrip(b"\x00") == b".rdata")
    rdva = rd.VirtualAddress
    rdraw = rd.PointerToRawData
    rdsz = rd.SizeOfRawData
    buf = raw[rdraw: rdraw + rdsz]

    runs = []
    i = 0
    while i + 8 <= rdsz:
        vals = []
        j = i
        while j + 8 <= rdsz:
            v = struct.unpack_from("<Q", buf, j)[0]
            if v in targets:
                vals.append(IB + v)
                j += 8
            else:
                break
        if len(vals) >= 4:
            runs.append((rdva + i, vals))
            i = j
        else:
            i += 8

    out = {("0x%x" % rva): [v for v in vals] for rva, vals in runs}
    with open("/tmp/serializer_tables.json", "w") as f:
        json.dump(out, f)
    # also report the interesting mid-size tables near the Iris region
    interesting = [(rva, v) for rva, v in runs if 6 <= len(v) <= 80]
    print("total fp-table runs:", len(runs))
    print("mid-size tables (6..80 entries):", len(interesting))
    for rva, vals in interesting[:12]:
        print("  RVA=0x%X entries=%d first=%s" % (
            rva, len(vals), ", ".join("0x%x" % (v - IB) for v in vals[:5])))


if __name__ == "__main__":
    main()
