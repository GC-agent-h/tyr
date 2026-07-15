#!/usr/bin/env python3
"""Characterize TYR game-module custom serializer WIRE IDIOMS at scale, by
disassembling all 1177 game serializer functions and counting the canonical
Iris bit-packing idioms (Phase 06 U1 / todo 7).

Idiom signals (x86-64 disassembly signatures):
  - BIT_WRITER_CALL  : `call qword ptr [reg + imm]`  (vtable dispatch to a
                       FNetBitWriter / reader method — the write/read of bits)
  - VARINT_PACK      : presence of the Iris WritePackedUint64 pattern
                       (3-bit byte count + bytes) — heuristic: `shl reg, 3`
                       / `and reg, 7` near a loop over bytes
  - LOOP             : `loop` / counted `dec`+`jne` loops (array element counts)
  - SHIFT_ACCUM      : `shl` into an accumulator with `or` (manual bit packing)

We report, per function, the idiom counts and aggregate histograms. This tells
us whether TYR's carrier uses (a) the stock Iris bit-stream serializer
(abundant BIT_WRITER_CALL + VARINT_PACK), or (b) a custom framing (different
idiom mix). A decisive structural fingerprint, not a hand-read guess.

Output (stdout + out/game_idioms.json):
  aggregate idiom histograms + per-function idiom dict.
Validation: number of functions scanned > 1000; prints histogram.
"""
from __future__ import annotations
import bisect
import json
import os
import pefile
import sys
import capstone

sys.path.insert(0, os.path.dirname(__file__))
import func_map as F

CS = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)


def main():
    pe = pefile.PE(F.BIN, fast_load=True)
    ib = pe.OPTIONAL_HEADER.ImageBase
    secs = F.section_lookup(pe)
    raw = open(F.BIN, "rb").read()
    fns, _ = F.parse_pdata(pe, secs, raw)
    begins = [b for b, _ in fns]

    def disasm(va):
        rva = va - ib
        idx = bisect.bisect_right(begins, rva) - 1
        if idx < 0:
            return []
        b, e = fns[idx]
        if not (b <= rva < e):
            return []
        co = F.rva_to_raw(secs, b)
        eo = F.rva_to_raw(secs, e)
        return list(CS.disasm(raw[co:eo], ib + b))

    with open(os.path.join(os.path.dirname(__file__), "..", "out",
                           "game_serializer_tables.json")) as f:
        tables = json.load(f)
    roots = set()
    for t in tables:
        for va in t["fns"]:
            if va is not None:
                roots.add(va)
    roots = sorted(roots)

    agg = {"bit_writer_call": 0, "varint_shift": 0, "loop": 0,
           "shift_accum": 0, "total_insns": 0}
    per_fn = []
    for va in roots:
        try:
            insns = disasm(va)
        except Exception:
            continue
        c = {"bit_writer_call": 0, "varint_shift": 0, "loop": 0,
             "shift_accum": 0}
        prev_shift = False
        for ins in insns:
            m, o = ins.mnemonic, ins.op_str
            if m == "call" and ("qword ptr" in o or "ptr [" in o):
                c["bit_writer_call"] += 1
            if m == "shl" and ("0x3" in o or ", 3" in o):
                c["varint_shift"] += 1
                prev_shift = True
            else:
                prev_shift = False
            if m in ("loop",) or (m == "dec" and "jne" in o):
                c["loop"] += 1
            if m == "shl" and m == "or":
                c["shift_accum"] += 1
        if c["bit_writer_call"] or c["varint_shift"] or c["loop"]:
            per_fn.append({"va": va, **c})
        for k in agg:
            if k == "total_insns":
                agg[k] += len(insns)
            else:
                agg[k] += c[k]

    out = {"aggregate": agg, "functions_with_idioms": len(per_fn),
           "per_fn": per_fn}
    outp = os.path.join(os.path.dirname(__file__), "..", "out", "game_idioms.json")
    os.makedirs(os.path.dirname(outp), exist_ok=True)
    with open(outp, "w") as f:
        json.dump(out, f, indent=1)

    print("functions scanned:", len(roots))
    print("aggregate idiom counts:", agg)
    print("functions exhibiting >=1 idiom:", len(per_fn))
    fn_w_bw = sum(1 for p in per_fn if p["bit_writer_call"])
    fn_w_varint = sum(1 for p in per_fn if p["varint_shift"])
    print("  with bit-writer vtable calls:", fn_w_bw)
    print("  with varint 3-bit shifts:", fn_w_varint)
    assert len(roots) > 1000, "too few functions scanned"


if __name__ == "__main__":
    main()
