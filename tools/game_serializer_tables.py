#!/usr/bin/env python3
"""Extract game-module (Projects/Tyr/Source) Iris serializer tables and their
pointed .text functions, to localize TYR's custom carrier/creation-info bridge
(Phase 06 U1 / todo 7).

Reuses the reloc-vtable scan from func_map.py, then keeps only tables whose
nearest-preceding same-section PDB landmark is in Projects/Tyr/Source. For each
such table, prints the RVA range and the VA of each pointed .text function.

Output (stdout + out/game_serializer_tables.json):
  [ {rva, end_rva, n_entries, fns:[va,...], landmark} , ... ]
Validation:
  - game tables count reported; this is a discovery listing, not a hard assert.
"""
from __future__ import annotations
import json
import os
import struct
import pefile
import sys

sys.path.insert(0, os.path.dirname(__file__))
import func_map as F


def main():
    pe = pefile.PE(F.BIN, fast_load=True)
    secs = F.section_lookup(pe)
    raw = open(F.BIN, "rb").read()
    ib = pe.OPTIONAL_HEADER.ImageBase
    text = next(s for s in secs if s["name"] == ".text")
    tv, tvs = text["va"], text["vsize"]

    fns, _ = F.parse_pdata(pe, secs, raw)
    begins = [b for b, _ in fns]
    runs, _ = F.parse_reloc_serializer_pointers(pe, secs, raw, ib, tv, tvs)
    landmarks = F.collect_pdb_landmarks(raw, secs)

    results = []
    for table_rva, vals in runs.items():
        mod = F.attribute_module(table_rva, landmarks)
        if mod != "Source":
            continue
        fns_here = []
        for v in vals:
            fnstart = F.fn_start_for(v - ib, begins, fns)
            fns_here.append(fnstart if fnstart is not None else None)
        results.append({
            "rva": table_rva,
            "end_rva": table_rva + len(vals) * 8,
            "n_entries": len(vals),
            "fns": [None if f is None else (ib + f) for f in fns_here],
            "landmark": mod,
        })
    results.sort(key=lambda r: r["rva"])

    outp = os.path.join(os.path.dirname(__file__), "..", "out",
                        "game_serializer_tables.json")
    os.makedirs(os.path.dirname(outp), exist_ok=True)
    with open(outp, "w") as f:
        json.dump(results, f, indent=1)

    print("game-module (Projects/Tyr/Source) serializer tables:", len(results))
    for r in results[:40]:
        print("  rva=0x%X end=0x%X n=%d fns=%s" % (
            r["rva"], r["end_rva"], r["n_entries"],
            ",".join(("0x%x" % x) if x is not None else "?" for x in r["fns"][:6]) +
            ("..." if r["n_entries"] > 6 else "")))
    if len(results) > 40:
        print("  ... (%d more)" % (len(results) - 40))


if __name__ == "__main__":
    main()
