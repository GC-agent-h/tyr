#!/usr/bin/env python3
"""Locate ch=13's root actor spawn and map its subobject handles (587..639) to
classes, using the FULL all-chunks walk. Also dumps the richest spawns
(channels 8/16/32/42/64) to characterize the player/vehicle actor tree.

Mechanism (proven earlier): spawn bunches carry the actor + subobject class
paths as byte-aligned FStrings in their raw_payload. We regex-scan.
"""
import sys, re, json
sys.path.insert(0, "tools")
import frame_walk as FW, container as CM

RF = "sample/TyrReplay1.replay"
TARGET_CH = {13, 8, 16, 32, 42, 64}
TOK_RE = re.compile(r"[\x20-\x7e]{6,}")

def tokens(raw: bytes):
    out = []
    for m in TOK_RE.finditer(raw.decode("latin1", "replace")):
        t = m.group(0).rstrip("\x00").strip()
        if any(h in t for h in (".", "/", "BP_", "_C", "AttributeSet",
                               "Component", "Subsystem", "Sentinel",
                               "Ability", "Tyr", "Script", "Recall", "Player",
                               "Vehicle", "Tank", "Heal", "CanOpener", "Game")):
            out.append(t)
    seen = set(); ded = []
    for t in out:
        if t not in seen:
            seen.add(t); ded.append(t)
    return ded

c = CM.parse_container(RF)
rep = [x for x in c.chunks if x.type_name == "ReplayData"]
raw = open(RF, "rb").read()

hits = {ch: [] for ch in TARGET_CH}
for ci, ch in enumerate(rep):
    data = raw[ch.data_offset: ch.data_offset + ch.size_in_bytes]
    ar = FW.ByteArchive(data)
    ar.bytes(16)
    ndf = 0
    while not ar.at_end() and (len(data) - ar.tell()) >= 4:
        b = ar.tell()
        try:
            fr, _ = FW.read_frame(ar, False, False)
        except Exception:
            break
        if fr is None or ar.tell() <= b:
            break
        ndf += 1
        for p in fr.packets:
            for bn in p.bunches:
                if bn.ch_index in TARGET_CH:
                    toks = tokens(bn.raw_payload) if bn.raw_payload else []
                    hits[bn.ch_index].append((ci, ndf, bn.b_open, len(bn.raw_payload), toks))

for ch in sorted(TARGET_CH):
    lst = hits[ch]
    print(f"\n=== ch={ch}: {len(lst)} bunches, {sum(1 for x in lst if x[2])} bOpen ===")
    # show bOpen ones with tokens first
    for ci, nf, op, ln, toks in lst:
        if op and toks:
            print(f"  [chunk {ci} f{nf} bOpen len {ln}] {toks[:8]}")
    # if no bOpen-with-tokens, show first non-empty bunch
    if not any(op and toks for _,_,op,_,toks in lst):
        for ci, nf, op, ln, toks in lst:
            if toks:
                print(f"  [chunk {ci} f{nf} open={op} len {ln}] {toks[:8]}")
                break
