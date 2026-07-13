"""
probe_phase05_iris_channel.py — Phase 05 -> Phase 06 payload handoff.

Empirically locates which legacy bunch channel(s) carry Iris replication data
streams. We do NOT assume a channel index; instead we replay every reassembled
bunch payload (from frame_walk.py's framing) through the Iris data-stream
decoder (iris_datastream.IrisDataStreamWalker) and record which channels decode
to a clean, fully-consumed multi-batch stream.

Why empirical: Iris rides inside the legacy DemoNetDriver bunch payload (the
outer replay framing is replay/transport-level, orthogonal to the replication
backend). The exact channel carrying the Iris stream is a runtime dispatch
decision, not specified in the framing alone.

A payload is classified "Iris" when the decoder:
  * consumes ALL of its bits (bits_consumed == payload_bits),
  * and parses >= 1 batch without overflow.

Output (stdout): per file, the dominant Iris-candidate channel + stats, then a
full JSON map channel->stats. The channel with the most fully-decoded payloads
is the Iris channel.

No live debugging available; this is a static/redundant-path cross-check
(README 00-overview Step 0.3 revised): the same bytes are framed two ways
(legacy bunch vs Iris stream) and we require both to agree (byte-exact on both).
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

import frame_walk as fw
import container as container_mod
from bitreader import BitReader
from iris_datastream import IrisDataStreamWalker


def scan_file(path: str, has_streaming_fixes: bool, has_game_specific: bool):
    c = container_mod.parse_container(path)
    rep_chunks = [ch for ch in c.chunks if ch.type_name == "ReplayData"]
    stats = defaultdict(lambda: {"hits": 0, "total": 0, "max_batches": 0,
                                 "bytes_seen": 0, "frames": set()})
    for ch in rep_chunks:
        raw = open(path, "rb").read()
        data = raw[ch.data_offset: ch.data_offset + ch.size_in_bytes]
        ar = fw.ByteArchive(data)
        ar.bytes(16)  # one-time chunk header
        frame_idx = 0
        while not ar.at_end() and (len(data) - ar.tell()) >= 12:
            fstart = ar.tell()
            try:
                fr, _ = fw.read_frame(ar, has_streaming_fixes, has_game_specific)
            except Exception:  # noqa: BLE001
                break
            if fr is None or ar.tell() <= fstart:
                break
            for pkt in fr.packets:
                for b in pkt.bunches:
                    if b.data_bits <= 0:
                        continue
                    bits = b.reassembled_payload
                    if len(bits) == 0:
                        continue
                    d = stats[b.ch_index]
                    d["total"] += 1
                    d["bytes_seen"] += len(bits)
                    walker = IrisDataStreamWalker()
                    try:
                        info = walker.walk_payload(bits)
                    except Exception:  # noqa: BLE001
                        continue
                    # Clean decode = all declared batches parsed, no overflow,
                    # and consumed content bits == payload bit length (real
                    # Iris payloads are byte aligned, so exact == consumed==len*8).
                    nbits = len(bits) * 8
                    if (not info.overflow
                            and info.object_batch_count > 0
                            and info.consumed_bits == nbits):
                        d["hits"] += 1
                        d["max_batches"] = max(d["max_batches"], len(info.batches))
                        d["frames"].add(frame_idx)
            frame_idx += 1
    return stats


def main(argv):
    has_streaming_fixes = False
    has_game_specific = False
    files = argv[1:] or sorted(__import__("glob").glob("sample/*.replay"))
    all_stats = {}
    for f in files:
        try:
            st = scan_file(f, has_streaming_fixes, has_game_specific)
        except Exception as e:  # noqa: BLE001
            print(f"ERROR scanning {f}: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        cleaned = {}
        for ch, d in st.items():
            cleaned[str(ch)] = {
                "hits": d["hits"], "total": d["total"],
                "max_batches": d["max_batches"], "bytes_seen": d["bytes_seen"],
                "frames_with_iris": len(d["frames"]),
            }
        all_stats[os.path.basename(f)] = cleaned
        best = max(cleaned.items(), key=lambda kv: kv[1]["hits"]) if cleaned else (None, {})
        print(f"{os.path.basename(f)}: Iris-candidate channel={best[0]} "
              f"hits={best[1].get('hits')} total_payloads={best[1].get('total')} "
              f"max_batches={best[1].get('max_batches')}")
    print(json.dumps(all_stats, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
