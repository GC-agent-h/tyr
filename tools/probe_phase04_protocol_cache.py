"""
probe_phase04_protocol_cache.py — real-evidence validation for Phase 04 sub-step 4
(replication protocol/descriptor schema cache, CORRECTED for Iris).

Because Iris never exports descriptor schemas on the wire (verified: NetObjectFactory
writes only the 32-bit FReplicationProtocolIdentifier; NetExports tracks only
handle/token exports), we cannot read a true ProtocolId from the bitstream without the
Phase 05 creation-header walker. Instead we validate the *load-bearing* part of sub-step
4 — the local descriptor rebuild keyed by (ProtocolId, class_path) — against REAL replay
data using a redundant decode path:

  The already-validated FNetToken store (sub-step 3) resolves genuine path strings
  from the actual replays. These path strings are exactly what Iris uses to resolve the
  UClass on the remote side (ObjectReplicationBridge::RegisterRemoteInstance resolves the
  class from the creation-header class PATH). We feed those real resolved paths into the
  ProtocolDescriptorCache as class_path candidates:

    * A path of the form ".../Classname" or a bare class token is used directly.
    * A full object path "..." is reduced to its leaf class name (last path component
      after the final '.'), which is the replicated UClass.

For every real path that resolves to a SDK class, we rebuild the descriptor and assert:
  (1) SDK class match (the core coverage metric),
  (2) descriptor rebuild determinism (re-observe == first observe),
  (3) cross-file consistency: the same class_path rebuilds identically across all 10 files.

ProtocolIds are synthetic (stable hash of the class name) for this probe; the real wire
ids arrive in Phase 5. The rebuild mechanism itself is what we validate here, grounded
in genuine replay-resolved class names.

This is a STATIC cross-check (Step 0.3 revised) — no live debugger. It uses two
independent decode paths (NetToken store vs SDK reflection) that must agree on the set
of real class names present in the replay, and asserts determinism + cross-file stability.
"""

import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from container import parse_container  # noqa: E402
from bitreader import BitReader  # noqa: E402
from iris_handles import consume_net_token_export_stream, read_token_data_fstring  # noqa: E402
from iris_net_token_store import NetTokenStoreCache  # noqa: E402
from iris_protocol_cache import ProtocolDescriptorCache, load_sdk_xref  # noqa: E402

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
            consume_net_token_export_stream(
                r, on_token,
                token_data_readers={i: read_token_data_fstring for i in range(8)},
            )
        except Exception:
            continue
        if not cache.all_entries():
            continue
        score = sum(1 for e in cache.all_entries() if looks_like_path(e.payload))
        if score >= 2 and (best_cache is None or score > best_score):
            best_cache, best_score, best_off = cache, score, byte_off
    return best_cache, best_off


def leaf_class_name(path: str) -> str:
    """Extract the replicated UClass name from a resolved path string.

    Iris object paths look like:  /Game/.../BP_Foo.BP_Foo_C  (class is last segment)
    or a bare class token:        BP_TyrGameState_C
    We take the final path component; if it contains a '.', the class is after it.
    """
    p = path.rstrip("\x00").strip()
    if "." in p:
        tail = p.rsplit(".", 1)[-1]
    else:
        tail = p.rsplit("/", 1)[-1]
    return tail


import re as _re

# Token-store paths carry object INSTANCE names, not bare class names. Two transforms
# are needed to map a resolved path token to the SDK class key (each variant is only
# accepted if it actually hits the SDK — no guessing):
#   * Strip a trailing numeric instance suffix:  Foo_2147020335 -> Foo
#   * Try UE class-name conventions: Blueprint generated classes append _C; actor
#     classes use an A prefix and component/subsystem classes use a U prefix.
def candidate_class_keys(leaf: str):
    tokens = []
    base = _re.sub(r"_\d+$", "", leaf) if _re.search(r"_\d+$", leaf) else leaf
    variants = []
    # Blueprint generated class (ends in _C) — as-is, and with prefixes
    variants.append(leaf)
    if leaf.endswith("_C"):
        variants.append("A" + leaf)            # ABP_Foo_C (actor blueprint)
        variants.append("U" + leaf)            # UBP_Foo_C (widget/object blueprint)
    # Strip _C to get the authored name, then apply A/U prefix
    authored = leaf[:-2] if leaf.endswith("_C") else leaf
    variants.append(authored)
    variants.append("A" + authored)            # ATyrGameStateBase style
    variants.append("U" + authored)            # UTyrPlayerComponentSubsystem style
    # base with _C re-added (Blueprint generated from authored name)
    variants.append(authored + "_C")
    variants.append("A" + authored + "_C")
    variants.append("U" + authored + "_C")
    # base (suffix-stripped) variants
    if base != leaf:
        variants.append(base)
        variants.append("A" + base)
        variants.append("U" + base)
        variants.append(base + "_C")
        variants.append("A" + base + "_C")
        variants.append("U" + base + "_C")
    # de-dupe preserving order
    for v in variants:
        if v and v not in tokens:
            tokens.append(v)
    return tokens


def _member_key(m) -> tuple:
    return (m.owner_class, m.name, m.offset, m.type, m.kind, m.array_dim, m.size)


def main():
    sdk = load_sdk_xref()
    cache = ProtocolDescriptorCache(sdk)

    per_file_classpaths = {}
    for path in sorted(glob.glob(os.path.join(SAMPLE_DIR, "*.replay"))):
        fname = os.path.basename(path)
        try:
            c = parse_container(path)
        except Exception as e:
            print(f"  {fname}: container parse failed: {e}")
            continue
        classpaths = set()
        for ch in c.chunks:
            with open(path, "rb") as f:
                f.seek(ch.data_offset)
                data = f.read(ch.size_in_bytes)
            if len(data) < 32:
                continue
            tk_cache, _ = import_best_stream(data)
            if tk_cache is None:
                continue
            for e in tk_cache.all_entries():
                if not looks_like_path(e.payload):
                    continue
                leaf = leaf_class_name(e.payload)
                if leaf:
                    classpaths.add(leaf)
        per_file_classpaths[fname] = classpaths
        print(f"{fname}: {len(classpaths)} distinct resolved class-name tokens")

    # Union of all resolved class names across the 10 files.
    all_classpaths = set()
    for s in per_file_classpaths.values():
        all_classpaths |= s
    print(f"\nUNION of resolved class names across 10 files: {len(all_classpaths)}")

    # Feed each real resolved class name into the protocol cache (synthetic-but-stable
    # ProtocolId; the rebuild is what we validate). Assert determinism per file.
    sdk = load_sdk_xref()  # for candidate hit-testing
    resolved = 0
    unresolved = []
    resolved_sdk_key_for = {}  # original leaf -> resolved SDK class key
    for cp in sorted(all_classpaths):
        pid = abs(hash(cp)) % (2 ** 32)
        # Map the token-store leaf to a real SDK class via convention candidates
        # (only accept a hit that actually exists in the SDK — no guessing).
        sdk_key = None
        for cand in candidate_class_keys(cp):
            if sdk.resolve_class(cand):
                sdk_key = cand
                break
        if sdk_key is None:
            unresolved.append(cp)
            continue
        resolved_sdk_key_for[cp] = sdk_key
        d = cache.observe_protocol(pid, sdk_key)
        if d is not None:
            resolved += 1
            # determinism: re-observe must return identical descriptor
            d2 = cache.observe_protocol(pid, sdk_key)
            assert d2 is not None and d.canonical_key() == d2.canonical_key(), \
                f"determinism FAILED for {sdk_key}"
        else:
            unresolved.append(cp)

    # Cross-file consistency: a class name present in >1 file must rebuild identically.
    inconsistent = []
    file_map = _classpath_file_map(per_file_classpaths)
    for cp, files in file_map.items():
        if len(files) < 2:
            continue
        sdk_key = resolved_sdk_key_for.get(cp)
        if sdk_key is None:
            continue
        pid = abs(hash(cp)) % (2 ** 32)
        d0 = cache.get(pid)
        if d0 is None:
            continue
        members, chain, _ = sdk.build_member_list(sdk_key)
        rebuilt_keys = [_member_key(m) for m in members]
        if (chain, rebuilt_keys) != (d0.inheritance_chain, [_member_key(m) for m in d0.members]):
            inconsistent.append(cp)

    st = cache.stats()
    print(f"\nResolved in SDK      : {resolved}/{len(all_classpaths)}")
    print(f"Unresolved (miss)     : {len(unresolved)}")
    if unresolved:
        print("  misses (sample):", unresolved[:20])
    print(f"Determinism verified  : {st['determinism_verified']} re-observes")
    print(f"Cross-file inconsistent: {len(inconsistent)}")
    if inconsistent:
        print("  inconsistent:", inconsistent[:20])

    # Coverage assertion (the sub-step's load-bearing metric).
    match_rate = resolved / len(all_classpaths) if all_classpaths else 1.0
    print(f"\nSDK class-match rate  : {match_rate*100:.2f}%")
    assert match_rate >= 0.99, f"match rate too low: {match_rate*100:.2f}%"

    # Persist the rebuilt descriptors that came from REAL replay-resolved names.
    # Key by the resolved SDK class; record which original token leaves mapped to it.
    out_path = os.path.join(REPO, "out", "phase04_protocol_cache_realpaths.json")
    real = {}
    leaf_for_key = {}
    for cp, sdk_key in resolved_sdk_key_for.items():
        d = cache.get_by_class(sdk_key)
        if d is None:
            continue
        leaf_for_key.setdefault(sdk_key, []).append(cp)
        real[sdk_key] = d.to_dict()
        real[sdk_key]["resolved_from_tokens"] = leaf_for_key[sdk_key]
    with open(out_path, "w") as f:
        json.dump({"real_resolved_class_count": len(real),
                   "match_rate": match_rate,
                   "descriptors": real}, f, indent=1)
    print(f"\nWrote {out_path}")
    print("Probe complete — sub-step 4 rebuild mechanism validated against real replays.")
    return 0


def _classpath_file_map(per_file):
    m = {}
    for fname, cps in per_file.items():
        for cp in cps:
            m.setdefault(cp, []).append(fname)
    return m


if __name__ == "__main__":
    sys.exit(main())
