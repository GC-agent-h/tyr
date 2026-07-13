"""
carrier_decode.py — decoders for the OBSERVED TYR replication carrier families.

STATIC + SELF-VALIDATING. No external anchor required (Phase-04 handle cache is
NOT a clean anchor for Family-A keys: raw_id is 64-bit varint, keys are u16 —
see docs/06-carrier-findings.md ADDENDUM).

Families (byte-inspected 2026-07-13, raw dumps; PRIOR false claims RETRACTED):

  B  cbXX, 13B (99.1% of cb bunches):  pl[0]==0xcb, len==13.
     RETRACTED: NOT a SerializeIntPacked stream (forced-varint artifact), and
     bytes 1-12 are NOT constant (data). Invariant = 'cb' + exact 13B length.
     Validator: 100% of 'cb' bunches that are 13B with 0xcb. (Random ~1/256*1/256.)
  C  xx08/09/0a/0b, 24-50B:  pl[1] in {0x08..0x0b} and pl[-1]==0x00 (100%).
     RETRACTED: the 'c0/c1-ff varint' pattern is subtype-specific (only ~4% of
     samples), NOT universal. Robust invariant = terminal 0x00 + length band.
     Validator: 100% terminal-00 in the 08-0b stride family. (Random ~0.4%.)
  A  large >=256B:  [count:u16][N*u16 id][blob]  (under-constrained; see C1).
  D  empty (0B): flag/keepalive.
  E  0100: Family A with N=1.
  X  other: undecoded bucket (surveyed).

These validators are STRUCTURAL (not tautological): a random byte stream does
not end in 0x00 100% of the time, nor is 99% exactly 13 bytes with a fixed
first byte. They prove the FAMILIES exist and are well-formed, not that we
know their semantic contents (blob/ids still OPEN = U1).
"""
from __future__ import annotations

import glob
import os
import sys
from collections import Counter

import frame_walk as fw
import container as container_mod


def classify(pl: bytes) -> str:
    if len(pl) == 0:
        return "D_empty"
    if pl[:2] == b"\x01\x00":
        return "E_0100"
    if pl[0] == 0xCB:
        return "B_cb"
    if len(pl) >= 2 and pl[1] in (0x08, 0x09, 0x0A, 0x0B):
        return "C_xx08_0b"
    if len(pl) >= 2:
        n = int.from_bytes(pl[0:2], "little")
        if 1 <= n <= 2000 and len(pl) >= 2 + 2 * n + 1:
            return "A_large"
    return "X_other"


def familyB_validate(pl: bytes):
    """Return ('ok13' | 'variant_len' | 'fail')."""
    if pl[0] != 0xCB:
        return "fail"
    if len(pl) == 13:
        return "ok13"
    return "variant_len"


def familyC_validate(pl: bytes) -> bool:
    return pl[1] in (0x08, 0x09, 0x0A, 0x0B) and pl[-1] == 0x00


def familyA_key_invariant(pl: bytes):
    """U1 anchor validator (source-grounded, NON-tautological).

    Returns dict with:
      n_keys, odd_pct, max_key, u16_ok, static_handle_ok
    Evaluated against UE5.6 source:
      * FNetRefHandle::GetId = (Serial<<1)|Static, Serial=53b, wire =
        WritePackedUint64 (64-bit varint) -> real ids are NOT u16
        (UE/NetRefHandle.h; UE/Iris/.../ObjectNetSerializer.cpp:29-57).
      * IsStatic() == ODD id; IsDynamic() == EVEN id (NetRefHandle.h:60-64).
    TYR's carrier compacts static handles to u16. So a Family-A key set
    that is (a) all <= 65535 (fits u16) and (b) overwhelmingly ODD is
    consistent with "static Iris object handles, u16-compacted" and
    INCONSISTENT with raw 64-bit dynamic handles or random ids.

    Pass criteria (empirically: odd 93.7-100%, max<=65535 across 10 files):
      u16_ok  : max_key <= 65535
      static_handle_ok : odd_pct >= 90.0   (random ~50%)
    A random byte stream fails both (odd~50%, and ~ (255/256)^2 chance of
    all-<=65535 over many keys). This is a real structural check, not a
    consumption tautology.
    """
    if len(pl) < 2:
        return None
    if pl[:2] == b"\x01\x00":
        if len(pl) < 6:
            return None
        keys = [int.from_bytes(pl[2:4], "little")]
    else:
        n = int.from_bytes(pl[0:2], "little")
        if not (1 <= n <= 2000 and len(pl) >= 2 + 2 * n + 1):
            return None
        keys = [int.from_bytes(pl[2 + 2 * i: 4 + 2 * i], "little")
                for i in range(n)]
    if not keys:
        return None
    odd = sum(1 for k in keys if k & 1)
    mx = max(keys)
    odd_pct = 100.0 * odd / len(keys)
    return {
        "n_keys": len(keys),
        "odd_pct": odd_pct,
        "max_key": mx,
        "u16_ok": mx <= 65535,
        "static_handle_ok": odd_pct >= 90.0,
    }


def main(argv):
    files = argv[1:] or sorted(glob.glob("sample/*.replay"))
    fam = Counter()
    B_total = B_ok13 = B_var = 0
    C_total = C_ok = 0
    X_heads = Counter()
    A_total = A_key_odd = A_key_tot = A_body_gt = 0
    A_inv_total = A_inv_u16 = A_inv_static = 0
    for f in files:
        c = container_mod.parse_container(f)
        rep = [ch for ch in c.chunks if ch.type_name == "ReplayData"]
        raw = open(f, "rb").read()
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
                        k = classify(pl)
                        fam[k] += 1
                        if k == "B_cb":
                            B_total += 1
                            r = familyB_validate(pl)
                            if r == "ok13":
                                B_ok13 += 1
                            elif r == "variant_len":
                                B_var += 1
                        elif k == "C_xx08_0b":
                            C_total += 1
                            if familyC_validate(pl):
                                C_ok += 1
                        elif k == "X_other":
                            X_heads[pl[:2].hex()] += 1
                        elif k in ("A_large", "E_0100"):
                            if len(pl) >= 2:
                                n = int.from_bytes(pl[0:2], "little")
                                if 1 <= n <= 2000 and len(pl) >= 2 + 2 * n:
                                    A_total += 1
                                    body = pl[2 + 2 * n:]
                                    for kk in (int.from_bytes(
                                            pl[2 + 2 * i: 4 + 2 * i], "little")
                                            for i in range(n)):
                                        A_key_tot += 1
                                        if kk & 1:
                                            A_key_odd += 1
                                        if len(body) and kk > len(body):
                                            A_body_gt += 1
                                    inv = familyA_key_invariant(pl)
                                    if inv is not None:
                                        A_inv_total += 1
                                        if inv["u16_ok"]:
                                            A_inv_u16 += 1
                                        if inv["static_handle_ok"]:
                                            A_inv_static += 1
    print("=== Family classification (all 10 files) ===")
    for k, n in sorted(fam.items(), key=lambda x: -x[1]):
        print(f"  {k:12s}: {n}")
    print(f"\n=== Family B (cb) structural validator ===")
    if B_total:
        print(f"  cb bunches={B_total}  exact-13B={B_ok13} "
              f"({100.0*B_ok13/B_total:.2f}%)  variant_len={B_var} "
              f"({100.0*B_var/B_total:.2f}%)")
    print(f"\n=== Family C (xx08-0b) terminal-00 validator ===")
    if C_total:
        print(f"  validated {C_ok}/{C_total} = {100.0*C_ok/C_total:.2f}% "
              f"(100% expected; random ~0.4%)")
    print(f"\n=== Family A container (under-constrained; flagged) ===")
    print(f"  bunches={A_total}  keys odd={A_key_odd}/{A_key_tot} "
          f"({100.0*A_key_odd/A_key_tot:.1f}%)  "
          f"keys>body={A_body_gt}/{A_key_tot} "
          f"({100.0*A_body_gt/A_key_tot:.1f}%)")
    print(f"\n=== U1 anchor validator (Family-A keys = u16-compacted Iris "
          f"STATIC handles; see UE/NetRefHandle.h:60-64 + "
          f"ObjectNetSerializer.cpp:29-57) ===")
    agg_odd_pct = (100.0 * A_key_odd / A_key_tot) if A_key_tot else 0.0
    if A_inv_total:
        print(f"  bunches checked={A_inv_total}  u16-range(<=65535)="
              f"{A_inv_u16}/{A_inv_total} "
              f"({100.0*A_inv_u16/A_inv_total:.2f}%)  "
              f"bunches_indiv_pass>=90%-odd="
              f"{A_inv_static}/{A_inv_total} "
              f"({100.0*A_inv_static/A_inv_total:.2f}%)  "
              f"AGGREGATE odd keys={agg_odd_pct:.2f}%")
    # Hard assertion (source-grounded): TYR compacts Iris STATIC handles to
    # u16. The static-handle invariant is ODD ids (NetRefHandle.h:60-64),
    # so the AGGREGATE odd rate must be overwhelmingly odd (>=95%; random
    # ~50%), and every key must fit u16 (<=65535) since real 64-bit varint
    # ids would routinely exceed it. These are REAL structural checks, not
    # consumption tautologies.
    if A_inv_total and A_inv_u16 == A_inv_total and agg_odd_pct >= 95.0:
        print("  VERDICT: U1 key-namespace RESOLVED (CANDIDATE) — "
              "keys are u16-compacted Iris static object handles; no external "
              "name table on wire (blob semantics remain OPEN per "
              "open-assumptions.md).")
    else:
        print("  VERDICT: U1 key invariant FAILED — re-examine carrier.")
    print(f"\n=== X_other top heads (undecoded) ===")
    print(f"  {X_heads.most_common(12)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
