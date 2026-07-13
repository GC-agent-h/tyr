"""
familyC_control.py (v2) — FALSIFICATION test (set-based, fast).

Precompute each Family-C content's set of u16 values ONCE, then measure
match rate against the real A-key set and against 20 control sets via
set-intersection. Real match-frac must be SIGNIFICANTLY above control mean
else the "Family C references A-keys" link is coincidental.
"""
from __future__ import annotations

import os
import sys
import glob
import json
import random
from statistics import mean, pstdev

import container as container_mod
import frame_walk as fw
import carrier_decode as cd

random.seed(0x711201)


def parse_head(pl: bytes):
    if len(pl) < 2:
        return None
    if pl[:2] == b"\x01\x00":
        if len(pl) < 6:
            return None
        return (1, [int.from_bytes(pl[2:4], "little")], pl[4:])
    n = int.from_bytes(pl[0:2], "little")
    if 1 <= n <= 2000 and len(pl) >= 2 + 2 * n + 1:
        keys = [int.from_bytes(pl[2 + 2 * i: 4 + 2 * i], "little")
                for i in range(n)]
        return (n, keys, pl[2 + 2 * n:])
    return None


def content_value_set(content: bytes):
    s = set()
    for off in range(0, len(content) - 1):
        s.add(int.from_bytes(content[off:off + 2], "little"))
    return s


def make_control(real, nsets=20):
    odd = [k for k in real if k & 1]
    even = [k for k in real if not (k & 1)]
    po = len(odd) / len(real) if real else 0.5
    controls = []
    for _ in range(nsets):
        s = set()
        while len(s) < len(real):
            if random.random() < po:
                k = (random.choice(odd) + random.randint(-50, 50)) & 0xFFFF | 1
            else:
                k = (random.choice(even) + random.randint(-50, 50)) & 0xFFFF & ~1
            s.add(k & 0xFFFF)
        controls.append(s)
    return controls


def main(argv):
    files = argv[1:] or sorted(glob.glob("sample/*.replay"))
    out = {}
    for path in files:
        fn = os.path.basename(path)
        c = container_mod.parse_container(path)
        rep = [ch for ch in c.chunks if ch.type_name == "ReplayData"]
        raw = open(path, "rb").read()

        a_keys = set()
        c_sets = []
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
                        cls = cd.classify(pl)
                        if cls in ("A_large", "E_0100"):
                            h = parse_head(pl)
                            if h is not None:
                                a_keys.update(h[1])
                        elif cls == "C_xx08_0b" and cd.familyC_validate(pl):
                            c_sets.append(content_value_set(pl[2:-1]))

        real_set = a_keys
        real_hits = sum(1 for sval in c_sets if sval & real_set)
        real_frac = real_hits / len(c_sets) if c_sets else 0.0

        controls = make_control(a_keys, 20)
        ctrl_fracs = []
        for cs in controls:
            h = sum(1 for sval in c_sets if sval & cs)
            ctrl_fracs.append(h / len(c_sets) if c_sets else 0.0)
        cm = mean(ctrl_fracs)
        csd = pstdev(ctrl_fracs)
        verdict = "REAL" if real_frac > cm + 2 * csd else "SPURIOUS"

        out[fn] = {
            "A_keys": len(a_keys),
            "C_bunches": len(c_sets),
            "real_frac": round(real_frac, 4),
            "ctrl_frac_mean": round(cm, 4),
            "ctrl_frac_std": round(csd, 4),
            "verdict": verdict,
        }
        print(f"=== {fn} ===")
        print(f"  A-keys={len(a_keys)} C-bunches={len(c_sets)}")
        print(f"  REAL match-frac={real_frac:.4f}  CONTROL mean={cm:.4f} "
              f"std={csd:.4f}  VERDICT: {verdict}")
        sys.stdout.flush()

    with open("out/familyC_control.json", "w") as f:
        json.dump(out, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
