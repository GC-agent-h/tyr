"""Phase 06 — U1 bootstrap re-run against the TYR .usmap schema (todo 8).

Prior state (commit b258db3): `u1_bridge.py` tested the ch=13 Family-A blob
against `out/sdk_index.json` (7,372 base-UE classes) with a FLAT primitive
decoder and got 0/7372 full-consumption+plausible hits. That established the
blob is a RECURSIVE OBJECT BUNDLE, not a flat class state.

This tool replaces the candidate set with the FULL .usmap schema (14,050
structs, incl. 606 TYR-specific) and runs TWO decode modes:

  MODE 1 (flat, faithful to the original u1_decode.py premise):
    decode the body as one class's primitive members in order; stop at the
    first non-primitive/non-enum member. Require full bit consumption + a
    positive plausibility score.

  MODE 2 (recursive structs):
    StructProperty members are RECURSED into their inner struct's members
    (the usmap supplies those). ArrayProperty reads a u32 count then recurses
    inner items. This is a best-effort approximation of Iris state layout and
    is used to probe whether the blob's TOTAL width matches any single large
    struct (e.g. a root actor's full ReplicationStateDescriptor).

RESULT INTERPRETATION (honest):
  - If MODE 1 still yields 0 hits against the COMPLETE TYR set, the 0/7372
    negative is CONFIRMED independent of class-set coverage -> the body is
    genuinely a recursive bundle, and the meaningful U1 target is the
    large-bunch (ch=13-style) blob decoded as a subobject tree, not a flat
    spawn state.
  - The spawn (E_0100) bodies are object-REFERENCE bundles per the carrier
    reframe, so the primary U1 target is the A_large 1936B blob.

No claim of U1 closure is made unless a real full-consumption+plausible
decode is observed AND cross-checked.
"""
from __future__ import annotations
import os
import sys
import struct
import math
import json

sys.path.insert(0, os.path.dirname(__file__))
import frame_walk as FW          # noqa: E402
import container as CM           # noqa: E402
import carrier_decode as CD      # noqa: E402

USMAP = "out/usmap_schema.json"


# ---------------------------------------------------------------------------
# Minimal Iris-faithful bit reader (identical semantics to u1_decode.py)
# ---------------------------------------------------------------------------
class BitReader:
    def __init__(self, data: bytes):
        self.data = data
        self.bitpos = 0
        self.nbits = len(data) * 8

    def read_bits(self, n: int) -> int:
        if n == 0:
            return 0
        if self.bitpos + n > self.nbits:
            raise EOFError(f"read_bits({n}) past end at {self.bitpos}/{self.nbits}")
        val = 0
        for i in range(n):
            byte = self.data[self.bitpos >> 3]
            bit = (byte >> (self.bitpos & 7)) & 1
            val |= bit << i
            self.bitpos += 1
        return val

    def remaining(self) -> int:
        return self.nbits - self.bitpos


def _enum_bits(enums, ename):
    e = enums.get(ename)
    if not e:
        return 8
    n = len(e.get("values", []))
    return max(1, (n - 1).bit_length())


# primitive width table (Iris NetSerializer bits)
_PRIM = {
    "BoolProperty": 1,
    "ByteProperty": 8,
    "Int8Property": 8,
    "UInt8Property": 8,
    "Int16Property": 16,
    "UInt16Property": 16,
    "IntProperty": 32,
    "UInt32Property": 32,
    "Int64Property": 64,
    "UInt64Property": 64,
    "FloatProperty": 32,
    "DoubleProperty": 64,
}


def member_width(enums, t):
    """Return (width_bits, kind) for a usmap type string. kind in
    {P, E, S, A, V} (primitive / enum / struct / array / variable-stop)."""
    if t in _PRIM:
        return _PRIM[t], "P"
    if t.startswith("EnumProperty<"):
        ename = t.split("<", 1)[1].rstrip(">")
        return _enum_bits(enums, ename), "E"
    if t.startswith("StructProperty<"):
        return 0, "S"
    if t in ("ArrayProperty", "SetProperty", "MapProperty"):
        return 0, "A"
    # Name/Object/Text/Str/Utf8/Optional/FieldPath -> variable length, stop
    return 0, "V"


def is_primitive_like(enums, t):
    w, k = member_width(enums, t)
    return k in ("P", "E")


# ---------------------------------------------------------------------------
# Recursive member decoder
# ---------------------------------------------------------------------------
def decode_members(enums, structs_by_name, members, br, recursive, depth=0):
    """Decode `members` (list of {name,type}) in order. If `recursive`, recurse
    into StructProperty inner structs and attempt ArrayProperty (count + inner).
    Returns (ok, n_consumed_bits, values) where ok=False means a member could
    not be laid out (hit a variable-length/unknown type in flat mode)."""
    values = []
    if depth > 8:  # guard against pathological recursion
        return False, br.bitpos, values
    for m in members:
        t = m["type"]
        w, k = member_width(enums, t)
        if k == "P":
            try:
                raw = br.read_bits(w)
            except EOFError:
                return False, br.bitpos, values
            values.append((m["name"], t, raw))
        elif k == "E":
            try:
                raw = br.read_bits(w)
            except EOFError:
                return False, br.bitpos, values
            values.append((m["name"], t, raw))
        elif k == "S" and recursive:
            inner = t.split("<", 1)[1].rstrip(">")
            inner_members = structs_by_name.get(inner)
            if not inner_members:
                return False, br.bitpos, values
            ok, _, sub = decode_members(enums, structs_by_name, inner_members,
                                        br, recursive, depth + 1)
            if not ok:
                return False, br.bitpos, values
            values.extend(sub)
        elif k == "A" and recursive:
            # best-effort: u32 count, then inner type repeated
            try:
                cnt = br.read_bits(32)
            except EOFError:
                return False, br.bitpos, values
            values.append((m["name"], t + f"[x{cnt}]", cnt))
            # unknown inner element width -> cannot continue deterministically
            return False, br.bitpos, values
        else:
            # flat mode hits a struct/array/var type -> stop (cannot lay out)
            return False, br.bitpos, values
    return True, br.bitpos, values


def plausibility(values):
    if not values:
        return 0.0
    score = 0.0
    for name, t, v in values:
        if isinstance(v, float):
            if math.isnan(v) or math.isinf(v):
                score -= 5.0
            elif abs(v) > 1e12:
                score -= 2.0
            elif abs(v) > 1e6:
                score -= 0.5
            else:
                score += 1.0
        else:
            if isinstance(v, int):
                if v < 0 and t.startswith("UInt"):
                    score -= 3.0
                elif v > (1 << 40):
                    score -= 1.0
                else:
                    score += 1.0
            else:
                score += 0.5
    return score / len(values)


def extract_bodies(replay):
    out = []
    seen = set()
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
                    if b.b_control or b.ch_index < 0:
                        continue
                    if b.ch_index in seen:
                        continue
                    pl = b.reassembled_payload
                    if len(pl) < 4:
                        continue
                    fam = CD.classify(pl)
                    if fam in ("A_large", "E_0100"):
                        n = struct.unpack_from("<H", pl, 0)[0]
                        body = pl[2 + 2 * n:]
                        key = struct.unpack_from("<H", pl, 2)[0] if n >= 1 else 0
                        keys = [struct.unpack_from("<H", pl, 2 + 2 * i)[0]
                                for i in range(n)] if n >= 1 else []
                        out.append((b.ch_index, key, body, fam, n, keys))
                        seen.add(b.ch_index)
    return out


def main(argv):
    replay = argv[1] if len(argv) > 1 else "sample/TyrReplay1.replay"
    mode_flag = argv[2] if len(argv) > 2 else "both"   # flat|rec|both
    schema = json.load(open(USMAP))
    enums = {e["name"]: e for e in schema["enums"]}
    structs_by_name = {s["name"]: s["props"] for s in schema["structs"]}
    # restrict candidate structs to those with a sane primitive count
    candidates = []
    for s in schema["structs"]:
        prims = sum(1 for p in s["props"] if is_primitive_like(enums, p["type"]))
        if 1 <= prims <= 60:
            candidates.append(s)
    print(f"[usmap] names={len(schema['names'])} enums={len(enums)} "
          f"structs={len(schema['structs'])} candidates={len(candidates)}")
    print(f"[replay] {replay}")
    bodies = extract_bodies(replay)
    print(f"[bodies] extracted {len(bodies)} (A_large/E_0100, first-per-channel)")

    do_flat = mode_flag in ("flat", "both")
    do_rec = mode_flag in ("rec", "both")

    flat_hits = []
    rec_hits = []
    for ch, key, body, fam, n, keys in bodies:
        nbits = len(body) * 8
        for s in candidates:
            # MODE 1: flat, stop at first non-primitive
            if do_flat:
                br = BitReader(body)
                ok, consumed, vals = decode_members(
                    enums, structs_by_name, s["props"], br, recursive=False)
                if ok and consumed == nbits:
                    sc = plausibility(vals)
                    if sc > 0.5:
                        flat_hits.append((ch, key, fam, s["name"], consumed, nbits, sc))
            # MODE 2: recursive structs (best-effort)
            if do_rec:
                br = BitReader(body)
                ok, consumed, vals = decode_members(
                    enums, structs_by_name, s["props"], br, recursive=True)
                if ok and consumed == nbits:
                    sc = plausibility(vals)
                    if sc > 0.5:
                        rec_hits.append((ch, key, fam, s["name"], consumed, nbits, sc))

    print(f"\n=== MODE1 (flat) full-consumption+plausible HITS: {len(flat_hits)} ===")
    for ch, key, fam, nm, c, tot, sc in flat_hits[:20]:
        print(f"  ch={ch} key=0x{key:04x} {fam} class={nm} bits={c}/{tot} score={sc:.2f}")
    print(f"\n=== MODE2 (recursive-struct) full-consumption+plausible HITS: {len(rec_hits)} ===")
    for ch, key, fam, nm, c, tot, sc in rec_hits[:20]:
        print(f"  ch={ch} key=0x{key:04x} {fam} class={nm} bits={c}/{tot} score={sc:.2f}")
    if not flat_hits and not rec_hits:
        print("  (no full-consume+plausible hit -> body is NOT a flat/recursive-single-class state)")
        # diagnostic: show body sizes + first-struct primitive widths for ch13
        for ch, key, body, fam, n, keys in bodies:
            if ch == 13:
                print(f"  ch13: n={n} keys={keys[:8]}... bodylen={len(body)}")
    return flat_hits, rec_hits


if __name__ == "__main__":
    main(sys.argv)
