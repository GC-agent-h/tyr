"""
familyA_temporal_probe3.py — per-key smoothness over offsets 0..40 for the
top persistent keys, to LOCALIZE the smooth scalar region and check whether it
is a contiguous multi-byte field (e.g. offsets 19..28 a single value) or
scattered single bytes. Reports per-key which contiguous run is smooth.
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
                    if not pl or cd.classify(pl) not in ("A_large", "E_0100"):
                        continue
                    parsed = parse_a(pl)
                    if not parsed:
                        continue
                    for key in parsed[0]:
                        by_key[key].append((frame_idx, parsed[1]))
            frame_idx += 1

    for key, series in sorted(by_key.items(), key=lambda kv: len(kv[1]), reverse=True)[:4]:
        if len(series) < 100:
            continue
        minlen = min(len(b) for _f, b in series)
        # per-offset smoothness
        stats = {}
        for off in range(minlen):
            prev = None
            n = s = le2 = 0
            for _f, body in series:
                cur = body[:minlen]
                if prev is not None:
                    d = abs(prev[off] - cur[off])
                    n += 1; s += d
                    if d <= 2:
                        le2 += 1
                prev = cur
            if n:
                stats[off] = (s / n, le2 / n)
        # find contiguous runs with frac<=2 >= 0.9
        runs = []
        run = []
        for off in range(minlen):
            if stats.get(off, (99, 0))[1] >= 0.9:
                run.append(off)
            else:
                if run:
                    runs.append((run[0], run[-1], len(run)))
                run = []
        if run:
            runs.append((run[0], run[-1], len(run)))
        print(f"\nkey {key} (n={len(series)}, body_minlen={minlen}):")
        print(f"  smooth runs (off_start..off_end, len) [frac<=2>=0.9]: {runs[:10]}")
        # show a couple sample frames of the main run
        if runs:
            a, b, _ = runs[0]
            for _f, body in series[::max(1, len(series)//6)][:6]:
                print(f"    f{_f:6d}: off{a}..{b} = {body[a:b+1].hex()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
