"""Phase 06 — empirical U1-closure bootstrap (Tier 3 from the U1 plan).

OA-06-2 REFUTED the pristine UE5.6 FReplicationReader envelope as TYR's carrier.
TYR's real carrier (docs/06-carrier-findings.md) is a multi-grammar structure
inside actor-channel bunch payloads:
  Family A : [count:u16][N*u16 key][blob]   (large state bunches)
  Family E : Family A with N=1 (spawn bunch)
  Family B : 13-byte bit-packed control/reference records
  Family C : xx0a name/arg blocks

This tool performs the decisive empirical test for U1: take a real spawn
(Family A/E, N=1) body, and decode it against candidate class schemas built by
iris_schema.build_class_schema, using IRIS-FAITHFUL per-type NetSerializer widths
(read from UE/Iris/Private/Iris/Serialization/*NetSerializers.cpp), scoring each
candidate by:
  (1) FULL CONSUMPTION  - bits consumed == declared body length  (phase gate #1)
  (2) TYPE PLAUSIBILITY - decoded values fall in semantically sane ranges
                           (phase gate #3: health in range, etc.)

If ANY candidate class yields full consumption + plausible values, U1 is
empirically CLOSED for that object: we have mapped a wire u16 key -> class ->
decoded property values, without any live debugger.

Iris NetSerializer widths used (source-grounded):
  bool                 -> BoolNetSerializer        : 1 bit
  uint8 / int8 / enum  -> 8 bits (enum: ceil(log2(count)) bits, min 1)
  uint16/int16         -> 16 bits
  uint32/int32         -> 32 bits
  uint64/int64         -> 64 bits
  float                -> FloatNetSerializer        : 32 bits (raw IEEE)
  double               -> 64 bits
  FName                -> SerializeIntPacked name index (var bits) -- approximated
                          as 16-bit for bootstrap scoring only.
"""
from __future__ import annotations
import os
import struct
import sys
import math
import json
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(__file__))
import iris_schema as S          # noqa: E402
import frame_walk as FW           # noqa: E402
import container as CM            # noqa: E402
import carrier_decode as CD       # noqa: E402


# ----------------------------------------------------------------------------
# Minimal Iris-faithful bit reader
# ----------------------------------------------------------------------------
class BitReader:
    def __init__(self, data: bytes):
        self.data = data
        self.bitpos = 0
        self.nbits = len(data) * 8

    def read_bits(self, n: int) -> int:
        if self.bitpos + n > self.nbits:
            raise EOFError(f"read_bits({n}) past end at {self.bitpos}/{self.nbits}")
        val = 0
        for i in range(n):
            byte = self.data[self.bitpos >> 3]
            bit = (byte >> (self.bitpos & 7)) & 1
            val |= bit << i
            self.bitpos += 1
        return val

    def read_bytes_aligned(self, n: int) -> bytes:
        # align to next byte then read
        if self.bitpos & 7:
            self.bitpos += (8 - (self.bitpos & 7))
        if self.bitpos + n * 8 > self.nbits:
            raise EOFError("read_bytes_aligned past end")
        out = self.data[self.bitpos >> 3: (self.bitpos >> 3) + n]
        self.bitpos += n * 8
        return out

    def remaining(self) -> int:
        return self.nbits - self.bitpos


def _enum_bits(sdk, ctype: str) -> int:
    e = sdk.get("enums", {}).get(ctype)
    if not e:
        return 8
    n = len(e.get("values", {}))
    return max(1, (n - 1).bit_length())


def member_bitwidth(sdk, m: S.Member) -> int:
    """Iris NetSerializer bit-width for a member (bootstrap approximation)."""
    if m.kind == "E":
        return _enum_bits(sdk, m.ctype)
    if m.kind != "D":
        return -1   # not a plain primitive we can lay out byte/bit-wise
    t = m.ctype
    return {
        "bool": 1, "uint8": 8, "int8": 8, "uint16": 16, "int16": 16,
        "uint32": 32, "int32": 32, "uint64": 64, "int64": 64,
        "float": 32, "double": 64,
    }.get(t, m.size * 8 if m.size else -1)


@dataclass
class DecodedValue:
    name: str
    ctype: str
    value: object
    bits: int


def decode_body_against_schema(sdk, br: BitReader, schema: S.ClassSchema):
    """Sequentially deserialize the schema's primitive members in ClassReps
    order, exactly as Iris would for an initial/spawn state (full member list,
    no change-mask gating for the INITIAL state path). Returns (values, ok)."""
    values = []
    for m in schema.members:
        w = member_bitwidth(sdk, m)
        if w <= 0:
            # struct/container member -> cannot lay out as primitive; stop.
            return values, False, f"non-primitive member {m.name} ({m.ctype})"
        try:
            raw = br.read_bits(w)
        except EOFError as e:
            return values, False, f"EOF at {m.name}: {e}"
        # interpret
        if m.ctype == "float":
            val = struct.unpack("<f", struct.pack("<I", raw & 0xFFFFFFFF))[0]
        elif m.ctype == "double":
            val = struct.unpack("<d", struct.pack("<Q", raw))[0]
        elif m.ctype in ("int8", "int16", "int32", "int64"):
            # sign-extend
            if raw & (1 << (w - 1)):
                val = raw - (1 << w)
            else:
                val = raw
        else:
            val = raw
        values.append(DecodedValue(m.name, m.ctype, val, w))
    return values, True, ""


def plausibility_score(values) -> float:
    """Higher = more plausible. Rewards in-range floats/ints, penalizes NaN/inf
    and wild out-of-range magnitudes."""
    if not values:
        return 0.0
    score = 0.0
    for v in values:
        x = v.value
        if isinstance(x, float):
            if math.isnan(x) or math.isinf(x):
                score -= 5.0
            elif abs(x) > 1e12:
                score -= 2.0
            elif abs(x) > 1e6:
                score -= 0.5
            else:
                score += 1.0
        elif isinstance(x, int):
            if x < 0 and v.ctype.startswith(("uint",)):
                score -= 3.0
            elif x > (1 << 40):
                score -= 1.0
            else:
                score += 1.0
    return score / len(values)


def extract_spawn_bodies(path: str):
    """Walk the replay; for each channel keep its FIRST (spawn) Family A/E body
    + the u16 key. Returns list of (ch_index, key, body_bytes)."""
    out = []
    seen_channels = set()
    c = CM.parse_container(path)
    rep = [ch for ch in c.chunks if ch.type_name == "ReplayData"]
    raw = open(path, "rb").read()
    for ch in rep:
        data = raw[ch.data_offset: ch.data_offset + ch.size_in_bytes]
        ar = FW.ByteArchive(data)
        ar.bytes(16)  # chunk header
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
                    if b.ch_index in seen_channels:
                        continue
                    pl = b.reassembled_payload
                    if len(pl) < 4:
                        continue
                    fam = CD.classify(pl)
                    # Family E_0100 = Family A with N=1 (spawn bunch); A_large =
                    # large replicated-state bunch. Both carry a [count:u16][keys]
                    # head; body starts after count + N*u16 keys.
                    if fam in ("A_large", "E_0100"):
                        n = struct.unpack_from("<H", pl, 0)[0]
                        key_start = 2
                        body = pl[key_start + 2 * n:]
                        # for N==1 the single key is the object's static handle
                        key = struct.unpack_from("<H", pl, 2)[0] if n >= 1 else 0
                        out.append((b.ch_index, key, body, fam))
                        seen_channels.add(b.ch_index)
    return out


def main(argv):
    sdk = S.load_sdk()
    replay = argv[1] if len(argv) > 1 else "sample/TyrReplay1.replay"
    anchors = argv[2:] or ["APlayerState", "ACharacter", "APawn", "AActor",
                           "APlayerController", "AGameStateBase", "AGameModeBase"]
    print(f"Replay: {replay}")
    print(f"Anchor classes: {anchors}")
    bodies = extract_spawn_bodies(replay)
    print(f"Spawn (N=1) bodies extracted: {len(bodies)}")
    schemas = {}
    for a in anchors:
        sc = S.build_class_schema(sdk, a)
        if sc:
            schemas[a] = sc
    print(f"Schemas built: {list(schemas)}")
    # For each body, try each schema; require full consumption (bits used ==
    # body bit length) and a positive plausibility score.
    hits = []
    for ch, key, body, fam in bodies:
        for aname, sc in schemas.items():
            br = BitReader(body)
            nbits = len(body) * 8
            try:
                vals, ok, err = decode_body_against_schema(sdk, br, sc)
            except Exception as e:
                continue
            consumed = br.bitpos
            full = (consumed == nbits)
            if not ok:
                continue
            score = plausibility_score(vals)
            if full and score > 0.5:
                hits.append((ch, key, aname, consumed, nbits, score, vals[:12]))
    print(f"\n=== U1 bootstrap HITS (full consumption + plausible): {len(hits)} ===")
    for ch, key, aname, cons, tot, score, vals in hits[:10]:
        print(f"  ch={ch} key=0x{key:04x} class={aname} bits={cons}/{tot} "
              f"score={score:.2f}")
        for v in vals:
            print(f"      {v.ctype:8} {v.name} = {v.value}")
    if not hits:
        print("  (no full-consume+plausible hit yet; see notes)")
        # diagnostic: show first few bodies' sizes + first float decode attempts
        for ch, key, body, fam in bodies[:5]:
            print(f"  ch={ch} key=0x{key:04x} bodylen={len(body)}")


if __name__ == "__main__":
    main(sys.argv)
