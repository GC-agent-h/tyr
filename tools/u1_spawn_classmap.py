#!/usr/bin/env python3
"""Extract byte-aligned FString class-paths from every bOpen (spawn) bunch's
reassembled payload across ALL ReplayData chunks, and (a) report the spawn with
the richest subobject class list (candidate for the ch=13 blob's 31 subobjects),
(b) locate the ch=13 root actor's spawn (handle 587..639 -> classes).

Class FStrings in spawn payloads are byte-aligned: i32 length (neg=utf16),
then `length` bytes. We scan the payload for any i32 length in (0,200) whose
declared bytes are printable ASCII and contain a class-path hint
('/', 'BP_', '_C', 'Sentinel', 'AttributeSet', 'Component', 'Subsystem').
"""
import sys; sys.path.insert(0, "tools")
import frame_walk as FW, container as CM, struct, re


CLASS_HINT = (b'/', b'BP_', b'_C', b'Sentinel', b'AttributeSet',
              b'Component', b'Subsystem', b'Tyr', b'Ability', b'/Script/')


def class_paths(pl: bytes):
    """Extract class-path-like tokens from a (bit-packed, byte-sliced) bunch
    payload. We do NOT rely on FString length framing (some bunches carry the
    class string inline without a byte-aligned length prefix in our slice).
    Instead scan for printable ASCII runs that look like UE object paths:
      /Game/..., /Script/..., /.../Blueprints/...BP_..._C, *AttributeSet,
      *Component, *Subsystem, *Sentinel, *Ability*.
    """
    tokens = []
    # decode as latin1, find runs of printable chars >= 6 long
    s = pl.decode("latin1", errors="replace")
    import re
    for m in re.finditer(r"[\x20-\x7e]{6,}", s):
        tok = m.group(0).rstrip("\x00").strip()
        if any(h in tok for h in (".", "/", "BP_", "_C", "AttributeSet",
                                   "Component", "Subsystem", "Sentinel",
                                   "Ability", "Tyr", "Script")):
            # drop trailing junk after a clearly-delimited path
            tokens.append(tok)
    # de-dup preserving order
    seen = set(); out = []
    for t in tokens:
        if t not in seen:
            seen.add(t); out.append(t)
    return out


def main():
    rf = "sample/TyrReplay1.replay"
    raw = open(rf, "rb").read()
    c = CM.parse_container(rf)
    rep = [x for x in c.chunks if x.type_name == "ReplayData"]
    ranked = []
    ch13_hits = []
    for ci, ch in enumerate(rep[:1]):  # chunk 0 only (fully parseable)
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
                    if not bn.b_open:
                        continue
                    pl = bn.raw_payload
                    cps = class_paths(pl) if pl else []
                    if bn.ch_index == 13:
                        ch13_hits.append((ci, ndf, cps, pl[:120] if pl else b''))
                    if cps:
                        ranked.append((len(cps), ci, ndf, bn.ch_index, cps))
    ranked.sort(reverse=True)
    print(f"spawns with class-paths: {len(ranked)}  ch13 hits: {len(ch13_hits)}")
    print("\nTop spawns by #class-paths:")
    for n, ci, f, chn, cps in ranked[:15]:
        print(f"  chunk={ci} frame={f} ch={chn} n={n} first={cps[0][:70]}")
        if n >= 20:
            print(f"    >>> CANDIDATE(31-subobj root?) ch={chn}: {cps}")
    print("\nch=13 spawn hits:")
    for ci, f, cps, pl in ch13_hits:
        print(f"  chunk={ci} frame={f} npaths={len(cps)} asc={pl!r}")


if __name__ == "__main__":
    main()
