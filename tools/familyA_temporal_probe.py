"""
familyA_temporal_probe.py — temporal-coherence extraction from Family A blobs
(plan-doc sub-step 3 validation: "temporal-coherence check", NO external anchor).

Method: Group Family-A bunches by object KEY (u16 static handle, U1-resolved).
For each key present across many frames, take its blob (the opaque state after
the id list) and, for each byte-offset, measure the TEMPORAL smoothness of that
byte across frames: mean |delta| and fraction of steps with |delta|<=2.

A real scalar channel (position/rotation/health) is smooth (small deltas);
random padding is not. This surfaces WHICH blob offsets carry semantic state,
without naming them. Non-tautological: a random byte stream shows mean|delta|~85.

Only the FIRST file is scanned (observation); if good offsets appear we extend.
"""
from __future__ import annotations
import sys, glob
from collections import defaultdict, Counter
import container as container_mod
import frame_walk as fw
import carrier_decode as cd


def parse_a(pl: bytes):
    """Return (keys_list, body_bytes) for a Family A/E bunch, or None."""
    if len(pl) < 6:
        return None
    if pl[:2] == b"\x01\x00":
        keys = [int.from_bytes(pl[2:4], "little")]
        body = pl[4:]
    else:
        n = int.from_bytes(pl[0:2], "little")
        if not (1 <= n <= 2000 and len(pl) >= 2 + 2 * n + 1):
            return None
        keys = [int.from_bytes(pl[2 + 2 * i: 4 + 2 * i], "little")
                for i in range(n)]
        body = pl[2 + 2 * n:]
    return keys, body


def main(argv):
    files = argv[1:2] or ["sample/TyrReplay1.replay"]
    # per key: list of (frame_idx, body) in frame order
    by_key = defaultdict(list)
    # also per key: per-frame first-blob-byte series
    frame_idx = 0
    c = container_mod.parse_container(files[0])
    rep = [ch for ch in c.chunks if ch.type_name == "ReplayData"]
    raw = open(files[0], "rb").read()
    for ch in rep:
        data = raw[ch.data_offset: ch.data_offset + ch.size_in_bytes]
        ar = fw.ByteArchive(data)
        ar.bytes(16)
        while not ar.at_end() and (len(data) - ar.tell()) >= 12:
            fstart = ar.tell()
            try:
                fr, _ = fw.read_frame(ar, False, False)
            except Exception:
                break
            if fr is None or ar.tell() <= fstart:
                break
            for pkt in fr.packets:
                for b in pkt.bunches:
                    pl = b.reassembled_payload
                    if not pl:
                        continue
                    k = cd.classify(pl)
                    if k not in ("A_large", "E_0100"):
                        continue
                    parsed = parse_a(pl)
                    if not parsed:
                        continue
                    keys, body = parsed
                    for key in keys:
                        by_key[key].append((frame_idx, body))
            frame_idx += 1

    # For keys present in >=20 frames, find smooth byte offsets.
    offset_smooth = defaultdict(lambda: [0, 0, 0])  # off -> [n_seq, sum_abs, le2]
    n_keys_used = 0
    for key, series in by_key.items():
        if len(series) < 20:
            continue
        n_keys_used += 1
        # align by min body length
        minlen = min(len(b) for _f, b in series)
        if minlen < 2:
            continue
        prev = [b[:minlen] for _f, b in series]
        for i in range(1, len(prev)):
            a = prev[i - 1]
            c = prev[i]
            for off in range(minlen):
                d = abs(a[off] - c[off])
                rec = offset_smooth[off]
                rec[0] += 1
                rec[1] += d
                if d <= 2:
                    rec[2] += 1
    print(f"file={files[0]} keys_with>=20_frames={n_keys_used}")
    results = []
    for off, (n, s, le2) in offset_smooth.items():
        if n < 100:
            continue
        mean_abs = s / n
        frac_le2 = le2 / n
        results.append((off, mean_abs, frac_le2, n))
    results.sort(key=lambda r: r[2], reverse=True)
    print(f"blob offsets (top15 by smoothness frac_le2):")
    print(f"  {'off':>4} {'mean|d|':>8} {'frac<=2':>8} {'n':>7}")
    for off, mean_abs, frac_le2, n in results[:15]:
        print(f"  {off:4d} {mean_abs:8.2f} {frac_le2:8.3f} {n:7d}")
    print("\n(random baseline: mean|d|~85, frac<=2~0.03; smooth scalar: mean|d|<<85)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
