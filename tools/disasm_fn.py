#!/usr/bin/env python3
"""Disassemble a .text function (by VA) from the TYR Shipping binary using the
.pdata-derived function boundaries for clean extent.

Used to inspect TYR's custom carrier/creation-info serializer functions
(Phase 06 U1 / todo 7): given a function VA (from game_serializer_tables.py),
dump its x86-64 disassembly so we can read the wire-framing idioms
(bit-writer calls, WritePackedUint64-style varint, array-count loops).

Usage: python3 tools/disasm_fn.py <va_hex> [max_bytes]
  e.g. python3 tools/disasm_fn.py 0x1416ad650
Prints mnemonic/operand lines; function extent taken from pdata boundaries.

Validation: opens the binary, finds the function in pdata, disassembles its
exact [begin,end) bytes. No crash on missing VA (prints NOT FOUND).
"""
from __future__ import annotations
import os
import struct
import sys
import pefile
import capstone

import func_map as F

CS = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
CS.detail = True


def find_fn(va):
    pe = pefile.PE(F.BIN, fast_load=True)
    secs = F.section_lookup(pe)
    raw = open(F.BIN, "rb").read()
    fns, _ = F.parse_pdata(pe, secs, raw)
    begins = [b for b, _ in fns]
    import bisect
    idx = bisect.bisect_right(begins, (va - F.section_lookup(pe)[0]["va"])) - 1
    # va is absolute; pdata begins are text-relative RVAs -> convert
    ib = pe.OPTIONAL_HEADER.ImageBase
    text = next(s for s in secs if s["name"] == ".text")
    rva = va - ib
    idx = bisect.bisect_right(begins, rva) - 1
    if idx < 0:
        return None, None, None
    b, e = fns[idx]
    if not (b <= rva < e):
        return None, None, None
    raw_off = F.rva_to_raw(secs, b)
    end_off = F.rva_to_raw(secs, e)
    code = raw[raw_off:end_off]
    base = ib + b
    return code, base, (b, e)


def main():
    if len(sys.argv) < 2:
        print("usage: disasm_fn.py <va_hex> [max_bytes]")
        return
    va = int(sys.argv[1], 16)
    maxb = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    code, base, rng = find_fn(va)
    if code is None:
        print("NOT FOUND (no function containing 0x%x)" % va)
        return
    print("function 0x%x  rva=0x%x..0x%x  base=0x%x  len=%d" %
          (va, rng[0], rng[1], base, len(code)))
    if maxb:
        code = code[:maxb]
    for ins in CS.disasm(code, base):
        print("0x%x:\t%s\t%s" % (ins.address, ins.mnemonic, ins.op_str))


if __name__ == "__main__":
    main()
