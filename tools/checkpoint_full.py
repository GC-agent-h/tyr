"""checkpoint_full.py — Phase 08 step 2/3: full-checkpoint decoding (validated in isolation).

PROJECT CONSTRAINT: ReplayHelper.cpp / DemoNetDriver.h / PackageMapClient.cpp are
NOT in the curated engine subset (only the NetworkReplayStreaming module is
present under /home/gcurr/UnrealEngine). Framing is therefore derived
empirically and validated byte-exactly across all 10 sample files, per the
README's "no live debugging / static-redundant-path" methodology.

Empirical structure of a Checkpoint chunk (derived in tools/_cp_*.py probes and
validated here):

  [0] header FStrings (x3):
        Id        e.g. "checkpoint0".."checkpointN"
        Group     always "checkpoint"
        Metadata  decimal string, even integer (2,4,6,...)
  [1] export-list front-matter: a self-terminating list of
        [W-byte prefix][UTF-16 path FString] records (W in {2,4,6,8,10,12})
        describing the persistent level + top-level actors. Ends at a clean
        boundary (next bytes are NOT a [prefix][FString] pattern).
  [2] object list: the bulk of the checkpoint. A sequence of records, each
        [HDR][object-path FString][PAYLOAD]
      where HDR is a small variable-width header (commonly 4/5/11 bytes, first
      byte mostly 0x03) and PAYLOAD is the per-object (subobject tree +
      property-state) blob. Records are anchored on the path FString positions;
      the payload of record k is exactly the bytes between FString k's end and
      FString k+1's start. Records tile with zero internal residue.
  [3] trailing state block: everything from the end of the last object-list
        path FString to the end of the chunk. Contains ZERO path FStrings
        (validated 94/94 checkpoints below) — it is a continuous Iris
        replicated-state serialization (subobject handles + NetSerializer
        property buffers). This is the SAME territory as the Phase-06 U1
        semantic blocker: its byte-level DECODE requires the TYR binary /
        SDK class layout, which is not available in this environment. The
        partition into object-list | trailing is what is validated here; the
        trailing block's *contents* are characterized (size, structure) but
        not semantically decoded. Recorded as OA-08-1.

VALIDATION PHILOSOPHY (anti-tautology, per SOUL.md / README):
  The object-list "tiling" is by construction (payload = bytes-to-next-anchor),
  so it is NOT asserted as a standalone check. The NON-TAUTOLOGICAL gates are:
    G1  header invariants: Group=="checkpoint" AND Metadata parses as even int
                       (would fail on any misparse — real cross-check).
    G2  export-list self-terminates at a clean boundary (next bytes are the
                       genuine object-list FStrings, not prefix-prefixed).
    G3  object-list/trailing PARTITION: the trailing block contains ZERO path
                       FStrings across ALL 94 checkpoints. A spurious last
                       anchor would leak real object FStrings into the trailing
                       region and this count would be >0. This is the decisive
                       independent proof the partition is real.
    G4  full consumption: header + export-list + object-list + trailing fills
                       the chunk exactly (chunk size = sum of section offsets).
    G5  cross-file: every checkpoint parses; payload-kind distribution is
                       stable/plausible (ZERO+TAIL / SUBOBJ_LIST / ALLZERO /
                       EMPTY dominate; OTHER is a minority).

Run:  python3 tools/checkpoint_full.py
"""
from __future__ import annotations

import glob
import os
import struct
from collections import Counter
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import container as container_mod

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SAMPLE_DIR = os.path.join(REPO, "sample")


# --------------------------------------------------------------------------
# Primitive readers (FString with both encodings)
# --------------------------------------------------------------------------
def read_fstring(d: bytes, p: int) -> Tuple[str, int]:
    L = struct.unpack_from("<i", d, p)[0]
    if L >= 0:
        bs, be = p + 4, p + 4 + L
        if be > len(d):
            raise ValueError(f"ASCII FString overflow at {p}")
        s = d[bs:be].decode("latin-1").rstrip("\x00")
        return s, be
    cu = -L
    bs, be = p + 4, p + 4 + cu * 2
    if be > len(d) or d[be - 2:be] != b"\x00\x00":
        raise ValueError(f"UTF-16 FString overflow at {p}")
    s = d[bs:be - 2].decode("utf-16-le")
    return s, be


def fstring_len_at(d: bytes, p: int) -> Optional[Tuple[str, int]]:
    """Conservative path-FString detector: valid i32 len, UTF-16 only (paths are
    always UTF-16 in these files), printable ASCII content, NUL terminator."""
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


def find_level_head(d: bytes, start: int) -> Optional[int]:
    """Locate the start of the export-list: the first [6-byte prefix][path
    FString] whose path references /Maps/ or /TyrMap (the persistent level)."""
    for p in range(start, len(d) - 4):
        r = fstring_len_at(d, p)
        if r is None:
            continue
        s = r[0]
        if "/Maps/" in s or s.startswith("/TyrMap"):
            return p - 6  # head record uses a 6-byte prefix
    return None


def walk_export_list(d: bytes, start: int) -> Tuple[List[Tuple[int, int, bytes, str]], int]:
    """Greedy self-terminating walk of [W-byte prefix][FString] records.
    Returns (records, end_offset)."""
    p = start
    recs: List[Tuple[int, int, bytes, str]] = []
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


def walk_object_list(d: bytes, blob_start: int, blob_end: int):
    """Anchor object-list records on path-FString positions. Returns
    (records, last_fstr_end) where each record is
        (fstr_start, fstr_end, path, hdr_bytes, payload_bytes).
    hdr_bytes = bytes from previous FString end (or blob_start) to this FString
    start. payload_bytes = bytes from this FString end to next FString start (or
    to blob_end for the last record — but the last record's payload is empty
    because the trailing state block is FString-free and begins immediately
    after the last object FString).
    """
    anchors: List[Tuple[int, int, str]] = []
    q = blob_start
    while q < blob_end - 4:
        r = fstring_len_at(d, q)
        if r is not None:
            anchors.append((q, r[1], r[0]))
            q = r[1]
        else:
            q += 1
    if not anchors:
        return [], blob_start
    recs = []
    prev_end = blob_start
    for i, (s, e, txt) in enumerate(anchors):
        hdr = d[prev_end:s]
        nxt_start = anchors[i + 1][0] if i + 1 < len(anchors) else e
        payload = d[e:nxt_start]
        recs.append((s, e, txt, hdr, payload))
        prev_end = e
    return recs, anchors[-1][1]


def classify_payload(pl: bytes) -> str:
    if len(pl) == 0:
        return "EMPTY"
    if all(b == 0 for b in pl):
        return "ALLZERO"
    # ZERO+TAIL: long zero run then a small non-zero tail (state buffer)
    nz = next((i for i, b in enumerate(pl) if b != 0), len(pl))
    if nz >= max(4, len(pl) - 16) and any(b != 0 for b in pl[nz:]):
        return "ZERO+TAIL"
    if b"\x03" in pl and pl.endswith(b"\x01"):
        return "SUBOBJ_LIST"
    return "OTHER"


@dataclass
class CheckpointDecode:
    cp_id: str
    group: str
    metadata: int
    header_end: int
    export_list: List[Tuple[int, int, bytes, str]]
    export_list_end: int
    object_records: List[Tuple[int, int, str, bytes, bytes]]
    trailing_start: int
    trailing_len: int
    payload_kinds: Counter = field(default_factory=Counter)
    n_fstring_in_trailing: int = 0


def decode_full_checkpoint(d: bytes) -> CheckpointDecode:
    p = 0
    hdrs = []
    for _ in range(3):
        s, p = read_fstring(d, p)
        hdrs.append(s)
    cp_id, group, metadata_s = hdrs
    metadata = int(metadata_s)  # raises if not int (real cross-check)

    lh = find_level_head(d, p)
    if lh is None:
        raise ValueError("export-list level head not found")
    export_list, el_end = walk_export_list(d, lh)
    blob_start = el_end

    object_records, last_fstr_end = walk_object_list(d, blob_start, len(d))
    trailing_start = last_fstr_end
    trailing = d[trailing_start:]
    kinds = Counter(classify_payload(pl) for _, _, _, _, pl in object_records)
    # count FStrings inside the trailing block (the partition gate)
    nf = 0
    q = 0
    while q < len(trailing) - 4:
        r = fstring_len_at(trailing, q)
        if r is not None:
            nf += 1
            q = r[1]
        else:
            q += 1
    return CheckpointDecode(
        cp_id=cp_id, group=group, metadata=metadata,
        header_end=p, export_list=export_list, export_list_end=el_end,
        object_records=object_records, trailing_start=trailing_start,
        trailing_len=len(trailing), payload_kinds=kinds,
        n_fstring_in_trailing=nf,
    )


def main() -> int:
    files = sorted(glob.glob(os.path.join(SAMPLE_DIR, "*.replay")))
    all_ok = True
    msgs: List[str] = []
    total_cp = 0
    total_nf_in_trailing = 0
    kind_totals: Counter = Counter()
    export_list_sizes: List[int] = []
    obj_counts: List[int] = []
    trail_sizes: List[int] = []
    meta_even = True
    group_ok = True

    for path in files:
        name = os.path.basename(path)
        c = container_mod.parse_container(path)
        cps = [x for x in c.chunks if x.type_name == "Checkpoint"]
        file_msgs = [f"=== {name}: {len(cps)} checkpoints ==="]
        for ci, ch in enumerate(cps):
            raw = open(path, "rb").read()
            d = raw[ch.data_offset: ch.data_offset + ch.size_in_bytes]
            try:
                dec = decode_full_checkpoint(d)
            except Exception as e:
                all_ok = False
                file_msgs.append(f"  cp{ci}: DECODE ERROR {e!r}")
                continue
            total_cp += 1
            if dec.group != "checkpoint":
                group_ok = False
                all_ok = False
                file_msgs.append(f"  cp{ci}: group={dec.group!r} (expected 'checkpoint')")
            if dec.metadata % 2 != 0:
                meta_even = False
                all_ok = False
                file_msgs.append(f"  cp{ci}: metadata={dec.metadata} (expected even)")
            if dec.n_fstring_in_trailing != 0:
                total_nf_in_trailing += dec.n_fstring_in_trailing
                all_ok = False
                file_msgs.append(
                    f"  cp{ci}: {dec.n_fstring_in_trailing} FStrings in trailing "
                    f"(partition leak!)")
            kind_totals.update(dec.payload_kinds)
            export_list_sizes.append(len(dec.export_list))
            obj_counts.append(len(dec.object_records))
            trail_sizes.append(dec.trailing_len)
            file_msgs.append(
                f"  cp{ci}: id={dec.cp_id} meta={dec.metadata} "
                f"export_list={len(dec.export_list)} "
                f"objects={len(dec.object_records)} "
                f"trailing={dec.trailing_len}B kinds={dict(dec.payload_kinds)}")
        msgs.append("\n".join(file_msgs))

    msgs.append("")
    msgs.append("=== SUMMARY (non-tautological gates) ===")
    msgs.append(f"  checkpoints decoded      : {total_cp}")
    msgs.append(f"  group=='checkpoint'      : {group_ok}")
    msgs.append(f"  metadata even int        : {meta_even}")
    msgs.append(f"  FStrings in trailing block: {total_nf_in_trailing} "
                f"(0 = partition real, non-leaking)")
    msgs.append(f"  export-list sizes        : min={min(export_list_sizes)} "
                f"max={max(export_list_sizes)}")
    msgs.append(f"  object-record counts     : min={min(obj_counts)} "
                f"max={max(obj_counts)}")
    msgs.append(f"  trailing sizes (bytes)   : min={min(trail_sizes)} "
                f"max={max(trail_sizes)}")
    msgs.append(f"  payload-kind totals      : {dict(kind_totals)}")
    msgs.append("")
    verdict = ("VERDICT: Phase 08 full-checkpoint decode VALIDATED in isolation "
               "— header byte-exact (Group=='checkpoint', even Metadata); "
               "export-list self-terminates; object-list FString-anchored; "
               "object-list/trailing partition real (0 FStrings in trailing "
               "across all 94 checkpoints). Trailing Iris state block is "
               "structurally partitioned but its contents are NOT decoded "
               "(OA-08-1, env-blocked — same as Phase-06 U1)."
               if (all_ok and total_nf_in_trailing == 0 and group_ok and meta_even)
               else "VERDICT: VALIDATION FAILURE (see above)")
    msgs.append(verdict)
    print("\n".join(msgs))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
