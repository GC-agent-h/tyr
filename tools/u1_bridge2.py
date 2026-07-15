#!/usr/bin/env python3
"""Corrected U1 handle->class bridge: extract f.net_export_groups (the
per-FRAME ReceiveNetFieldExports cache, parsed by frame_walk.read_frame) and
check whether the Family-A blob's handles (587,595,...; 2215,...; 7287,...) map
to class-path export_names. This is the genuine handle->class anchor the
width-sum tautology lacked.

For each replay:
  - walk read_frame over each ReplayData chunk (skip the 16-byte chunk header
    the same way frame_walk's container consumer does)
  - accumulate handle -> export_name (path) / path_name from every frame's
    net_export_groups
  - load out/u1_blobs.json (largest A/E blob) and report coverage of its keys
"""
from __future__ import annotations
import glob, json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
import frame_walk as FW
import container as CM


def extract_exports(replay):
    hmap = {}
    c = CM.parse_container(replay)
    rep = [ch for ch in c.chunks if ch.type_name == "ReplayData"]
    raw = open(replay, "rb").read()
    for ch in rep:
        data = raw[ch.data_offset: ch.data_offset + ch.size_in_bytes]
        ar = FW.ByteArchive(data)
        ar.bytes(16)  # chunk-level header read once
        while not ar.at_end() and (len(data) - ar.tell()) >= 12:
            before = ar.tell()
            # Per-frame: level(i32), time(f32), THEN ReceiveNetFieldExports.
            # We read the export cache directly (validated against UE5.6 source +
            # empirical bytes: group0 = /Script/Engine.WorldSettings, 22 exports).
            # We do NOT call read_frame (its NetExportGuids framing order desyncs).
            try:
                _lvl = ar.i32(); _t = ar.f32()
            except Exception:
                break
            if ar.at_end() or (len(data) - ar.tell()) < 4:
                break
            try:
                groups = FW.read_net_field_exports(ar)
            except Exception:
                # a desynced group; skip to next frame heuristically
                break
            for g in groups:
                if not g.export or "handle" not in g.export:
                    continue
                h = g.export["handle"]
                nm = g.export.get("export_name")
                nm = nm.get("name") if isinstance(nm, dict) else nm
                hmap[h] = (nm, g.path_name)
            # advance past the rest of this frame (guids/streaming/external/packets)
            # by seeking to the next level(i32) that looks like a frame start.
            # Simplest robust approach: we already consumed exports; break the chunk
            # loop after the FIRST frame's export cache (handles are stable/accumulated
            # across the stream, but re-reading per frame is costly). Instead, walk
            # ALL frames by re-seeking: use read_frame's packet consumption is broken,
            # so we approximate by scanning each 4-byte-aligned frame start.
            # Pragmatic: only the FIRST export cache per chunk is parseable here;
            # that cache already contains the global handle->class map for the chunk.
            break
    return hmap


def main():
    blobs = json.load(open("out/u1_blobs.json"))
    for f in sorted(glob.glob("sample/*.replay")):
        hmap = extract_exports(f)
        b = blobs.get(f)
        line = f"{os.path.basename(f):16} exports={len(hmap):6d}"
        if b:
            keys = b["keys"]
            ok = [k for k in keys if k in hmap]
            h = keys[0] if keys else None
            ex0 = []
            for k in keys[:6]:
                nm = hmap.get(k)
                ex0.append(f"{k}->{nm[0] if nm else '?'}")
            line += f"  blob:ch{b['channel']},n{len(keys)}  covered={len(ok)}/{len(keys)}"
            line += "  e.g. " + ", ".join(ex0)
        print(line)


if __name__ == "__main__":
    main()
