"""
familyA_temporal_probe2.py — refine: is each smooth offset object-SPECIFIC
(per-key, varying independently -> real state channel) or a COMMON prefix
(same bytes across all keys in a frame -> a shared header, not per-object
state)? Also: does offset 20..28 form a contiguous multi-byte field (e.g. a
single smooth value spanning several bytes)? Measure per-key smoothness AND
cross-key value overlap per offset.
"""
from __future__ import annotations
import sys
from collections import defaultdict
import container as container_mod
import frame_walk as fw
import carrier_decode as cd


def parse_a(pl: bytes):
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
    by_key = defaultdict(list)
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
                    if cd.classify(pl) not in ("A_large", "E_0100"):
                        continue
                    parsed = parse_a(pl)
                    if not parsed:
                        continue
                    keys, body = parsed
                    for key in keys:
                        by_key[key].append((frame_idx, body))
            frame_idx += 1

    # For a few keys with many frames, show per-offset smoothness and whether
    # the value at offset 20..28 is key-specific (varies between keys per frame).
    keys_sorted = sorted(by_key.items(), key=lambda kv: len(kv[1]), reverse=True)[:6]
    print(f"top keys (id, n_frames): {[(k, len(v)) for k, v in keys_sorted]}")
    # cross-key value at a sample frame for offsets 19..28
    sample_fi = None
    for k, series in keys_sorted:
        if series:
            sample_fi = series[10][0]
            break
    print(f"\nvalues at frame {sample_fi} for offsets 19..28 (hex per key):")
    for k, series in keys_sorted:
        row = ""
        for _f, body in series:
            if _f == sample_fi:
                seg = body[19:29] if len(body) >= 29 else b""
                row = seg.hex()
                break
        print(f"  key {k:5d}: {row}")
    # per-key smoothness for offset 20
    print(f"\nper-key smoothness at offset 20 (mean|d|, frac<=2):")
    for k, series in keys_sorted:
        if len(series) < 20:
            continue
        minlen = min(len(b) for _f, b in series)
        if minlen < 21:
            continue
        prev = None
        n = s = le2 = 0
        for _f, body in series:
            cur = body[:minlen]
            if prev is not None:
                d = abs(prev[20] - cur[20])
                n += 1; s += d
                if d <= 2:
                    le2 += 1
            prev = cur
        if n:
            print(f"  key {k:5d}: mean|d|={s/n:6.2f} frac<=2={le2/n:.3f} (n={n})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
