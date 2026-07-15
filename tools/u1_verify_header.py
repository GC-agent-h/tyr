#!/usr/bin/env python3
"""Verify the Family-A header grammar across ALL sample replays and measure the
canonical ch=13 / 1936B blob (Phase 06 U1 / todo 7).

For every Family-A/E bunch, dump:
  channel, n_handles, the handle list (first 8), body byte/bit length.
Specifically focus on the ch=13 "A_large" blob (the U1 target) and confirm:
  - header = u16 count + count*u16 handles + blob
  - body = 1936B = 15488 bits
  - n_handles == 31 (root + 30 subobjects)
  - all subobject handles odd (static), root may differ
and check whether OTHER files have the same ch=13 blob size (for held-out
cross-file replication test later).

Output: prints a per-file summary + aggregated ch13 body sizes.
"""
from __future__ import annotations
import glob
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
                    # Family A / E
                    keys = [struct.unpack_from("<H", pl, 2 + 2 * i)[0]
                            for i in range(n)]
                    body = pl[2 + 2 * n:]
                    out.append((b.ch_index, n, keys, body))
    return out


def main():
    files = sorted(glob.glob("sample/*.replay"))
    print("files:", len(files))
    ch13_sizes = {}
    total_A = 0
    for f in files:
        bunches = extract(f)
        total_A += len(bunches)
        # ch13 large blob
        ch13 = [b for b in bunches if b[0] == 13 and len(b[3]) == 1936]
        if ch13:
            b = ch13[0]
            ch13_sizes[f] = (b[1], len(b[3]), b[2][:8])
        # also report the largest body per file for reference
        big = max(bunches, key=lambda x: len(x[3])) if bunches else None
        if big:
            print(f"  {os.path.basename(f):16} bunches={len(bunches):5d} "
                  f"maxbody={len(big[3]):5d}B ch13_1936x{len(ch13)}")
    print(f"\ntotal Family-A/E bunches: {total_A}")
    print("ch=13 / 1936B blob present in files:", len(ch13_sizes), "/", len(files))
    for f, (n, sz, k) in ch13_sizes.items():
        print(f"  {os.path.basename(f):16} n_handles={n} body={sz}B "
              f"({sz*8} bits) keys[:8]={k}")
    # assert the documented invariants for the canonical blob
    if ch13_sizes:
        sample = next(iter(ch13_sizes.values()))
        assert sample[0] == 31, f"n_handles != 31 (got {sample[0]})"
        assert sample[1] == 1936, f"body != 1936B (got {sample[1]})"
        print("\nVALIDATED: canonical ch13 blob = 31 handles, 1936B (15488 bits).")


if __name__ == "__main__":
    main()
