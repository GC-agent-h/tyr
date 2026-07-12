"""probe_phase04_iris.py — Phase 04 sub-step 1 REAL-EVIDENCE gate.

We do NOT yet have the full Iris packet walker (Phase 05). But we CAN:
  1) Parse the container of each sample replay (reuse tools.container).
  2) For each chunk, scan raw bytes for the *signature* of an Iris NetToken
     export stream: a run of [stop-bit=1][packed index][auth-bit][typeid 3 bits]
     followed by a byte-aligned FString, terminated by a stop-bit=0.
  3) Try to decode the FIRST plausible NetToken export stream we find with the
     source-verified decoder (consume_net_token_export_stream) and report what
     strings come out. If real object/name paths appear (e.g. /Game/, BP_,
     WorldGravity), that is strong evidence the layout matches the engine.

This is a discovery probe: it reports OBSERVATIONS, not conclusions. It does
not claim every chunk is Iris; it finds the best candidate and shows the decode.
"""

import glob
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from container import parse_container
from bitreader import BitReader
from iris_handles import consume_net_token_export_stream, read_token_data_fstring
from iris_netrefhandle_cache import NetRefHandleCache

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_DIR = os.path.join(REPO, "sample")


def chunk_bytes(path, ch):
    with open(path, "rb") as f:
        f.seek(ch.data_offset)
        return f.read(ch.size_in_bytes)


def try_decode_token_stream(data, start_bit):
    """Attempt to decode a NetToken export stream starting at start_bit.
    Returns (ok, decoded_list, end_bit) or (False, [], start_bit)."""
    r = BitReader(data)
    r.seek_bits(start_bit)
    decoded = []

    def on_token(tok, payload):
        decoded.append((tok.index, tok.type_id, tok.is_assigned_by_authority, payload))

    # consume_net_token_export_stream stops at first stop-bit=0.
    try:
        # We feed individual attempts: just read a bounded number of tokens.
        count = consume_net_token_export_stream(
            r, on_token,
            token_data_readers={0: read_token_data_fstring, 1: read_token_data_fstring,
                                2: read_token_data_fstring, 3: read_token_data_fstring},
        )
    except Exception:
        return False, [], start_bit
    if count == 0:
        return False, [], start_bit
    return True, decoded, r.tell_bits()


def looks_like_path(s):
    # Decoded payloads are UE FStrings and may carry a trailing null terminator;
    # strip it before classifying. Accept printable ASCII of reasonable length.
    if not isinstance(s, str):
        return False
    s = s.rstrip("\x00")
    if not (4 <= len(s) <= 200):
        return False
    return all(32 <= ord(c) < 127 for c in s) and s.strip() != ""


def main():
    for path in sorted(glob.glob(os.path.join(SAMPLE_DIR, "*.replay"))):
        c = parse_container(path)
        print(f"=== {os.path.basename(path)} : {len(c.chunks)} chunks ===")
        for ch in c.chunks:
            data = chunk_bytes(path, ch)
            # Scan byte-aligned start positions for a NetToken stream signature.
            best = None
            # Scan byte-aligned starts across the whole chunk (not just first 4KB)
            # but cap work: Iris export streams are near the front of checkpoints.
            scan_limit = min(len(data), 8192)
            for byte_off in range(0, scan_limit, 1):
                ok, decoded, end_bit = try_decode_token_stream(data, byte_off * 8)
                if ok and len(decoded) >= 2:
                    score = sum(1 for d in decoded if looks_like_path(d[3]))
                    if score >= 2 and (best is None or score > best[0]):
                        best = (score, byte_off, decoded[:20], len(decoded))
            if best is not None:
                score, off, sample, total = best
                print(f"  chunk type={ch.type_name!r} off={ch.data_offset} "
                      f"size={ch.size_in_bytes}: candidate NetToken stream @ byte {off} "
                      f"score={score}/{total}")
                for idx, tid, auth, payload in sample:
                    print(f"      tok idx={idx} type={tid} auth={int(auth)} -> {payload!r}")
            else:
                print(f"  chunk type={ch.type_name!r} off={ch.data_offset} "
                      f"size={ch.size_in_bytes}: no clear NetToken stream signature in first 4KB")
    print("\nProbe complete (observations only — not conclusions).")


if __name__ == "__main__":
    main()
