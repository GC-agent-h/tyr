#!/usr/bin/env python3
"""Survey all Family-A/E blobs: collect (channel, n_handles, body_len, keys)
for every A/E bunch across all replays. Output a compact summary to support the
held-out cross-file tiling test for U1 (todo 7): each file's largest blob is its
initial-snapshot object bundle; we want to see how many distinct (n,len) pairs
exist and whether n_handles correlates with body_len.

Also dumps the largest A/E blob per file (body bytes + keys) to out/u1_blobs.json
for the tiling solver.
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


def extract(replay):
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
                fr, adv = FW.read_frame(ar, False, False)
            except Exception:
                break
            if fr is None or ar.tell() <= before:
                break
            for pkt in fr.packets:
                for b in pkt.bunches:
                    if b.ch_index < 0 or b.b_control:
                        continue
                    pl = b.reassembled_payload
                    if len(pl) < 2:
                        continue
                    n = struct.unpack_from("<H", pl, 0)[0]
                    if not (1 <= n <= 2000 and len(pl) >= 2 + 2 * n + 1):
                        continue
                    keys = [struct.unpack_from("<H", pl, 2 + 2 * i)[0]
                            for i in range(n)]
                    body = pl[2 + 2 * n:]
                    out.append((b.ch_index, n, keys, bytes(body)))
    return out


def main():
    files = sorted(glob.glob("sample/*.replay"))
    allpairs = {}
    largest_per_file = {}
    for f in files:
        bunches = extract(f)
        pairs = {}
        for ch, n, keys, body in bunches:
            pairs.setdefault((n, len(body)), 0)
            pairs[(n, len(body))] += 1
            cur = largest_per_file.get(f)
            if cur is None or len(body) > len(cur[3]):
                largest_per_file[f] = (ch, n, keys, body)
        allpairs[f] = pairs

    print("distinct (n_handles, body_len) pairs per file:")
    for f in files:
        pairs = allpairs[f]
        # show the largest few
        top = sorted(pairs.items(), key=lambda kv: -kv[0][1])[:6]
        print(f"  {os.path.basename(f):16}", top)

    print("\nLargest A/E blob per file (the U1 initial-snapshot target):")
    dump = {}
    for f in files:
        ch, n, keys, body = largest_per_file[f]
        dump[f] = {"channel": ch, "n_handles": n,
                   "keys": keys, "body": body.hex(), "body_len": len(body)}
        odd = sum(1 for k in keys if k & 1)
        print(f"  {os.path.basename(f):16} ch={ch} n={n} odd={odd}/{n} "
              f"body={len(body)}B ({len(body)*8}b) keys[:6]={keys[:6]}")

    # distinct body lens among largest blobs
    lens = sorted({v["body_len"] for v in dump.values()})
    print("\ndistinct largest-blob body lengths:", lens)
    print("distinct n_handles among largest blobs:",
          sorted({v["n_handles"] for v in dump.values()}))

    os.makedirs("out", exist_ok=True)
    with open("out/u1_blobs.json", "w") as fp:
        json.dump(dump, fp, indent=1)
    print("\nwrote out/u1_blobs.json")


if __name__ == "__main__":
    main()
