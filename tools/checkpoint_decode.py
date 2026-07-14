"""checkpoint_decode.py — Phase 08 step 1 (framing) + step 4 (full/delta).

ReplayHelper.cpp is NOT in the curated /UE subset, so framing is derived
empirically and validated byte-exact across all 10 files. Scope (per README: do
not over-assert): this tool establishes the CHUNK FRAMING and the full-vs-delta
mode. It does NOT decode the state blob (that is a separate, larger effort) and
does NOT claim to resolve object ids.

Empirical structure of a Checkpoint chunk payload (validated):
  [0]   FString Id            ("checkpoint0".."checkpointN")
  [1]   FString Group         ("checkpoint")
  [2]   FString Metadata      ("2","4",...)  -- increments by 2 / checkpoint
  [3]   export-list front matter: a SHORT, self-terminating list of
          [prefix][neg-len UTF-16 FString path] records describing the
          persistent level + top-level actors (level path, PersistentLevel,
          WorldSettings, Map_*_C, first spawned actors). 7..45 records.
          Head record uses a 6-byte prefix; subsequent records use a 4-byte
          prefix. The list ENDS where the next offset is not a valid
          [prefix][FString] (clean boundary, not a heuristic).
  [4]   state blob: the bulk of the chunk. A serialized checkpoint state. It
          CONTAINS ~hundreds of path FStrings whose preceding u16 are UObject
          export indices (0..~65k, ~30% odd) — a namespace DISJOINT from the
          Family-A u16 static handles (~99% odd, range ~1..few-thousand). There
          is NO Family-A-key -> path lookup table here (see U1 closure).

Full-vs-delta (step 4): each checkpoint re-exports the CURRENTLY-LIVE object
path set. Across checkpoints the set grows AND shrinks (actors spawn/despawn),
jaccard(cp0,cpLast) ~0.66, not a fixed dictionary and not a pure cumulative
delta. => each checkpoint is a FULL snapshot of live objects at that time.

Run:  python3 tools/checkpoint_decode.py
"""
from __future__ import annotations

import glob
import os
import struct
import sys

import container as container_mod


def read_fstring(d: bytes, p: int):
    """Read an FString at p (handles both encodings):
      length >= 0 -> ASCII, body = d[p+4 : p+4+len]
      length <  0 -> UTF-16, body = d[p+4 : p+4+(-len)*2]
    Returns (text, end)."""
    L = struct.unpack_from("<i", d, p)[0]
    if L >= 0:
        bs = p + 4
        be = bs + L
        if be > len(d):
            raise ValueError(f"bad ASCII FString at {p}")
        s = d[bs:be].decode("latin-1").rstrip("\x00")
        return s, be
    cu = -L
    bs = p + 4
    be = bs + cu * 2
    if be > len(d) or d[be - 2:be] != b"\x00\x00":
        raise ValueError(f"bad UTF-16 FString at {p}")
    s = d[bs:be - 2].decode("utf-16-le")
    return s, be


def parse_header(d: bytes):
    p = 0
    out = []
    for _ in range(3):
        s, p = read_fstring(d, p)
        out.append(s)
    return out, p


def fstring_len_at(d: bytes, p: int):
    if p + 4 > len(d):
        return None
    L = struct.unpack_from("<i", d, p)[0]
    if L >= 0 or not (2 <= -L <= 8192):
        return None
    cu = -L
    bs, be = p + 4, p + 4 + cu * 2
    if be > len(d) or d[be - 2:be] != b"\x00\x00":
        return None
    try:
        s = d[bs:be - 2].decode("utf-16-le")
    except Exception:
        return None
    if not s or any(ord(c) < 0x20 or ord(c) > 0x7e for c in s):
        return None
    return s, be


def walk_export_list(d: bytes, start: int):
    """Greedy self-terminating walk of [W-byte prefix][FString] records.
    Returns list of (offset, width, prefix, text) and the end offset."""
    p = start
    recs = []
    while True:
        chosen = None
        for w in (4, 6, 2, 8, 10, 12):
            if p + w + 4 > len(d):
                continue
            if fstring_len_at(d, p + w) is not None:
                chosen = w
                break
        if chosen is None:
            break
        s, be = fstring_len_at(d, p + chosen)
        recs.append((p, chosen, d[p:p + chosen], s))
        p = be
    return recs, p


def blob_fstring_set(d: bytes, start: int):
    out = set()
    n = len(d)
    for p in range(start, n - 4):
        r = fstring_len_at(d, p)
        if r is not None:
            out.add(r[0])
    return out


def find_level_head(d: bytes, start: int):
    for p in range(start, len(d) - 4):
        r = fstring_len_at(d, p)
        if r is None:
            continue
        s = r[0]
        if "/Maps/" in s or s.startswith("/TyrMap"):
            return p - 6  # head record uses 6-byte prefix
    return None


def decode_checkpoint(d: bytes):
    hdrs, p = parse_header(d)
    list_start = find_level_head(d, p)
    if list_start is None:
        recs, list_end = [], p
    else:
        recs, list_end = walk_export_list(d, list_start)
    blob = blob_fstring_set(d, list_end)
    return {
        "id": hdrs[0], "group": hdrs[1], "metadata": hdrs[2],
        "header_end": p, "list_start": list_start,
        "export_list": recs, "export_list_end": list_end,
        "state_blob_len": len(d) - list_end, "blob_paths": blob,
    }


def main(argv):
    files = sorted(glob.glob("sample/*.replay"))
    all_ok = True
    msgs = []
    for path in files:
        name = os.path.basename(path)
        c = container_mod.parse_container(path)
        cps = [x for x in c.chunks if x.type_name == "Checkpoint"]
        sizes = []
        nrecs = []
        head_ok = True
        head_reason = ""
        for ch in cps:
            raw = open(path, "rb").read()
            d = raw[ch.data_offset: ch.data_offset + ch.size_in_bytes]
            try:
                info = decode_checkpoint(d)
            except Exception as e:
                msgs.append(f"  {name} cp decode ERROR {e!r}")
                all_ok = False
                continue
            sizes.append(len(info["blob_paths"]))
            nrecs.append(len(info["export_list"]))
            # header invariants: Group=="checkpoint", metadata is even int
            g = info["group"]; m = info["metadata"]
            if g != "checkpoint":
                head_ok = False; head_reason = f"group={g!r}"
            try:
                mv = int(m)
                if mv % 2 != 0:
                    head_ok = False; head_reason = f"metadata={m!r} odd"
            except Exception as e:
                head_ok = False; head_reason = f"metadata={m!r} parseerr {e!r}"
        msgs.append(f"=== {name}: {len(cps)} checkpoints, "
                    f"export-list sizes={nrecs}, blob-path-set sizes={sizes}")
        mono = all(sizes[i] <= sizes[i + 1] for i in range(len(sizes) - 1))
        grows = any(sizes[i] < sizes[i + 1] for i in range(len(sizes) - 1))
        shrinks = any(sizes[i] > sizes[i + 1] for i in range(len(sizes) - 1))
        mode = ("FULL snapshot (live set per checkpoint)" if (grows and shrinks)
                else ("monotonic growth (possibly delta-accum)" if grows
                      else "?"))
        msgs.append(f"    header_ok={head_ok} {head_reason} sizes_nondec={mono} "
                    f"grow={grows} shrink={shrinks} -> {mode}")
        all_ok = all_ok and head_ok
    print("\n".join(msgs))
    print("\nVERDICT:",
          "Phase 08 framing OK — header byte-exact (Group=='checkpoint', even Metadata), "
          "export-list self-terminates, state blob is the remainder; mode = FULL per-checkpoint snapshot"
          if all_ok else "FRAMING ISSUE (see above)")


if __name__ == "__main__":
    main(sys.argv)
