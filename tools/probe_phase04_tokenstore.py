"""probe_phase04_tokenstore.py — real-evidence validation for Phase 04 sub-step 3.

Imports genuine NetToken export streams from real Tyr replays into the standalone
NetTokenStoreCache and reports the resolved (TypeId, Index) -> payload dictionary,
verifying the typed-store resolution model against real replay bytes.

The NetToken export stream is byte-aligned inside Iris checkpoints (proven in
sub-step 1: the FString payloads are ReadAlign'd). We reuse the same byte-aligned
signature scan as probe_phase04_iris.py, then import via NetTokenStoreCache.
"""
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from container import parse_container  # noqa: E402
from bitreader import BitReader  # noqa: E402
from iris_handles import consume_net_token_export_stream, read_token_data_fstring  # noqa: E402
from iris_net_token_store import NetTokenStoreCache  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_DIR = os.path.join(REPO, "sample")


def looks_like_path(s):
    if not isinstance(s, str):
        return False
    s = s.rstrip("\x00")
    if not (4 <= len(s) <= 200):
        return False
    return all(32 <= ord(c) < 127 for c in s) and s.strip() != ""


def import_best_stream(data):
    """Byte-aligned scan; import the highest-scoring export stream into a cache."""
    best_cache = None
    best_score = 0
    best_off = None
    scan_limit = min(len(data), 8192)
    for byte_off in range(0, scan_limit):
        r = BitReader(data)
        r.seek_bits(byte_off * 8)
        cache = NetTokenStoreCache()

        def on_token(tok, payload):
            if payload is None:
                return
            cache.import_token(tok, payload)

        try:
            count = consume_net_token_export_stream(
                r, on_token,
                token_data_readers={0: read_token_data_fstring, 1: read_token_data_fstring,
                                    2: read_token_data_fstring, 3: read_token_data_fstring,
                                    4: read_token_data_fstring, 5: read_token_data_fstring,
                                    6: read_token_data_fstring, 7: read_token_data_fstring},
            )
        except Exception:
            continue
        if count == 0:
            continue
        score = sum(1 for e in cache.all_entries() if looks_like_path(e.payload))
        if score >= 2 and (best_cache is None or score > best_score
                           or (score == best_score and count > len(best_cache.all_entries()))):
            best_cache, best_score, best_off = cache, score, byte_off
    return best_cache, best_off


def main():
    for path in sorted(glob.glob(os.path.join(SAMPLE_DIR, "*.replay"))):
        print(f"\n=== {os.path.basename(path)} ===")
        try:
            c = parse_container(path)
        except Exception as e:
            print(f"  container parse failed: {e}")
            continue
        any_hit = False
        for ch in c.chunks:
            with open(path, "rb") as f:
                f.seek(ch.data_offset)
                data = f.read(ch.size_in_bytes)
            if len(data) < 32:
                continue
            cache, off = import_best_stream(data)
            if cache is None:
                continue
            any_hit = True
            st = cache.stats()
            print(f"  [{ch.type_name}] @byte {off}: {st['total_imports']} tokens, "
                  f"type_ids={st['type_ids_present']}, per_type={st['per_type_count']}")
            # Show a sample of resolved paths (genuine Tyr strings).
            sample = [e for e in cache.all_entries() if looks_like_path(e.payload)][:8]
            for e in sample:
                auth = "auth" if e.is_assigned_by_authority else "client"
                print(f"      (type={e.type_id}, idx={e.index}, {auth}) -> {e.payload!r}")
        if not any_hit:
            print("  (no clear NetToken export stream in first 8KB of any chunk)")
    print("\nProbe complete (observations only — not conclusions).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
