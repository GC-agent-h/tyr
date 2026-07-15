#!/usr/bin/env python3
"""Rank the 64 game-module custom serializer functions by real code size (from
.pdata boundaries) and identify which are shared across many serializer tables.

This tells us which TYR-custom functions are worth disassembling first for the
per-subobject wire grammar (Phase 06 U1 / todo 7).

Output (stdout + out/game_fn_rank.json):
  top functions by size, each with: va, size_bytes, num_tables_referencing_it.
Validation: prints total distinct functions; non-empty list asserted.
"""
from __future__ import annotations
import bisect
import json
import os
import pefile
import sys

sys.path.insert(0, os.path.dirname(__file__))
import func_map as F


def main():
    pe = pefile.PE(F.BIN, fast_load=True)
    secs = F.section_lookup(pe)
    raw = open(F.BIN, "rb").read()
    ib = pe.OPTIONAL_HEADER.ImageBase
    fns, _ = F.parse_pdata(pe, secs, raw)
    begins = [b for b, _ in fns]

    with open(os.path.join(os.path.dirname(__file__), "..", "out",
                           "game_serializer_tables.json")) as f:
        tables = json.load(f)

    # Collect every distinct fn VA + how many tables reference it.
    refcount = {}
    for t in tables:
        for va in t["fns"]:
            if va is None:
                continue
            refcount[va] = refcount.get(va, 0) + 1

    # Size of each distinct fn.
    def size_of(va):
        rva = va - ib
        idx = bisect.bisect_right(begins, rva) - 1
        if idx < 0:
            return None
        b, e = fns[idx]
        if not (b <= rva < e):
            return None
        return e - b

    rows = []
    for va, nref in refcount.items():
        sz = size_of(va)
        if sz is None:
            continue
        rows.append((va, sz, nref))
    rows.sort(key=lambda r: (-r[1], -r[2]))

    out = [{"va": va, "size": sz, "n_tables": nref} for va, sz, nref in rows]
    outp = os.path.join(os.path.dirname(__file__), "..", "out", "game_fn_rank.json")
    os.makedirs(os.path.dirname(outp), exist_ok=True)
    with open(outp, "w") as f:
        json.dump(out, f, indent=1)

    print("distinct game-module serializer functions:", len(rows))
    print("top 25 by code size (va, size, n_tables_referencing):")
    for va, sz, nref in rows[:25]:
        print("  0x%X  size=%-6d  refs=%d" % (va, sz, nref))
    assert rows, "no game functions ranked"


if __name__ == "__main__":
    main()
