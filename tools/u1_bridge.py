#!/usr/bin/env python3
"""U1 (todo 7, option a) — handle->class BRIDGE extraction + coverage check.

Step 1 of the non-tautological recursive decoder: recover, from each replay's own
NetFieldExport stream (PackageMapClient::ReceiveNetFieldExports), the mapping

    export_handle -> class_path (FString)

Then check whether the Family-A blob's N handles (the 1936B ch13 initial snapshot)
are ALL present in that mapping. If yes, the width-sum tautology is defeated: each
subobject's struct is now GROUNDED in the replay's own spawn class names, not a
width-sum search. That is the non-tautological anchor.

Uses the existing frame_walk NetFieldExport parser (validated against UE5.6
PackageMapClient). Outputs, per file:
  - # NetFieldExports parsed, # with a handle+export_name
  - for the largest A/E blob: its handles -> how many resolve to a class_path
  - whether ALL handles resolve (the gating condition for the decoder)
"""
from __future__ import annotations
import glob
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
import frame_walk as FW
import container as CM


def extract_exports(replay):
    """Walk ReplayData chunks, parse each bunch's package-map export payload
    (the control bunch that carries ReceiveExportData). Returns list of
    (handle, export_name, path_name) for every NetFieldExport that is exported."""
    out = []
    c = CM.parse_container(replay)
    rep = [ch for ch in c.chunks if ch.type_name == "ReplayData"]
    raw = open(replay, "rb").read()
    for ch in rep:
        data = raw[ch.data_offset: ch.data_offset + ch.size_in_bytes]
        ar = FW.ByteArchive(data)
        ar.bytes(16)
        while not ar.at_end() and (len(data) - ar.tell()) >= 12:
            before = ar.tell()
            try:
                fr, _ = FW.read_frame(ar, False, False)
            except Exception:
                break
            if fr is None or ar.tell() <= before:
                break
            for pkt in fr.packets:
                for b in pkt.bunches:
                    if not b.b_control or not b.b_has_package_map_exports:
                        continue
                    pl = b.reassembled_payload
                    if len(pl) < 4:
                        continue
                    ea = FW.ByteArchive(pl)
                    try:
                        groups = FW.read_net_field_exports(ea)
                    except Exception:
                        continue
                    for g in groups:
                        ex = g.export
                        if ex and ex.get("exported") and "handle" in ex:
                            out.append((ex["handle"],
                                        ex.get("export_name", {}).get("name")
                                        if isinstance(ex.get("export_name"), dict)
                                        else ex.get("export_name"),
                                        g.path_name))
    return out


def main():
    files = sorted(glob.glob("sample/*.replay"))
    blobs = json.load(open("out/u1_blobs.json"))
    print(f"{'file':18} {'exports':>8} {'w/handle':>8}  blob(ch,n)  covered/total")
    for f in files:
        exports = extract_exports(f)
        hmap = {}
        for h, name, path in exports:
            if h is not None:
                hmap[h] = (name, path)
        b = blobs.get(f)
        cov = ""
        if b:
            keys = b["keys"]
            ok = sum(1 for k in keys if k in hmap)
            cov = f"{ok}/{len(keys)}"
            # a few resolved examples
            ex = []
            for k in keys[:4]:
                nm = hmap.get(k)
                ex.append(f"{k}->{ (nm[0] if nm else '?') }")
            cov += "  e.g. " + ", ".join(ex)
        print(f"  {os.path.basename(f):16} {len(exports):8d} {len(hmap):8d}  "
              f"ch{b['channel']},n{b['n_handles']}  {cov}")


if __name__ == "__main__":
    main()
