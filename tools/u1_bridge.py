"""U1 bridge (path A): SDK-descriptor-driven bit decoder.

Goal: validate that the Family-A `A_large` state blob (ch=13, 1936 B) is a
well-formed Iris initial-state serialization of SOME SDK class, by consuming it
member-by-member in ClassReps order with documented UE5.6 Iris NetSerializer
widths. We do NOT know ch=13's class (no wire anchor), so we brute-force ALL
SDK classes and report those whose full-state serialization CONSUMES the blob
fully with plausible values (Phase-06 gates #1 + #3).

This is STRUCTURAL validation, not bit-exact naming. Exact widths for quantized
vectors / custom serializers come from the binary serializer vtables (see
tools/find_serializer_tables.py); here we use documented UE5.6 defaults and
flag width-sensitive types (QUANTIZED-VECTOR, ARRAY-APPROX, etc.) so a match on
a flagged class is CANDIDATE, not KNOWN.

Serializer widths (UE5.6 Iris documented defaults):
  bool                       : 1 bit
  uint8/int8                 : 8 bits
  uint16/int16               : 16
  uint32/int32               : 32
  uint64/int64               : 64
  float                      : 32 bits IEEE
  double                     : 64 bits
  FName                      : intpacked(nameIdx) + intpacked(number)
  FString/FText              : intpacked(len) + len*8 (ansi) or *16 (unicode)
  FVector                    : 96 (plain) / 90 (Quantize: 30/comp)
  FQuat                      : 59 (compressed: 2-bit index + 3x19)
  FRotator                   : 96 (plain) / 72 (Quantize: 24/comp)
  FTransform                 : 59 + 96 + 96
  object ref / TSubclassOf   : intpacked NetGUID/NetToken
  TArray<T>                  : intpacked(count) + elements  (element width
                                approximated as intpacked -> flagged ARRAY-APPROX)
  struct (S) / enum (E)      : recurse into SDK def
"""
from __future__ import annotations
import json
import os
import struct
import sys

SDK_PATH = "out/sdk_index.json"


class BitReader:
    def __init__(self, buf: bytes):
        self.buf = buf
        self.nbits = len(buf) * 8
        self.pos = 0

    def remaining(self):
        return self.nbits - self.pos

    def read_bits(self, n):
        if self.pos + n > self.nbits:
            raise EOFError("read_bits past end")
        val = 0
        for i in range(n):
            byte = self.buf[(self.pos + i) >> 3]
            bit = (byte >> ((self.pos + i) & 7)) & 1
            val |= bit << i
        self.pos += n
        return val

    def read_intpacked(self):
        val = 0
        shift = 0
        while True:
            if self.pos + 8 > self.nbits:
                avail = self.nbits - self.pos
                if avail <= 0:
                    raise EOFError("intpacked past end")
                b = self.read_bits(avail)
                val |= (b & 0x7F) << shift
                return val
            b = self.read_bits(8)
            val |= (b & 0x7F) << shift
            if not (b & 0x80):
                return val
            shift += 7

    def read_float(self):
        return struct.unpack("<f", struct.pack("<I", self.read_bits(32)))[0]

    def read_double(self):
        return struct.unpack("<d", struct.pack("<Q", self.read_bits(64)))[0]


def plausible_float(v):
    return v == v and -1e9 < v < 1e9


def plausible_intpacked(v, max_expected=1 << 24):
    return 0 <= v <= max_expected


class Bridge:
    def __init__(self, sdk):
        self.classes = sdk.get("classes", {})
        self.structs = sdk.get("structs", {})

    def _get_def(self, ctype):
        return self.classes.get(ctype) or self.structs.get(ctype)

    def _eat_member(self, m, br: BitReader, depth=0):
        """Consume one SDK prop. Return (ok, note). Advances br."""
        ctype = m.get("type", "")
        kind = m.get("kind", "D")
        size = m.get("size", 0)
        count = m.get("count", 1) or 1
        if ctype == "bool":
            br.read_bits(1); return (True, "")
        if ctype in ("uint8", "int8"):
            br.read_bits(8 * count); return (True, "")
        if ctype in ("uint16", "int16"):
            br.read_bits(16 * count); return (True, "")
        if ctype in ("uint32", "int32"):
            br.read_bits(32 * count); return (True, "")
        if ctype in ("uint64", "int64"):
            br.read_bits(64 * count); return (True, "")
        if ctype == "float":
            for _ in range(count):
                if not plausible_float(br.read_float()):
                    return (False, "float range")
            return (True, "")
        if ctype == "double":
            v = br.read_double()
            if v != v or abs(v) > 1e15:
                return (False, "double range")
            return (True, "")
        if ctype == "FName":
            ni = br.read_intpacked()
            if not plausible_intpacked(ni):
                return (False, "FName idx")
            br.read_intpacked()
            return (True, "")
        if ctype in ("FString", "FText"):
            ln = br.read_intpacked()
            if not plausible_intpacked(ln, 1 << 20):
                return (False, "FString len")
            neg = ln < 0
            length = -ln if neg else ln
            br.read_bits(8 * length * (2 if neg else 1))
            return (True, "")
        if ctype.startswith("FVector"):
            if "Quantize" in ctype:
                br.read_bits(30 * 3 * count); return (True, "QUANTIZED-VECTOR")
            br.read_bits(96 * count); return (True, "PLAIN-VECTOR")
        if ctype == "FQuat":
            br.read_bits(59 * count); return (True, "")
        if ctype == "FRotator":
            if "Quantize" in ctype:
                br.read_bits(24 * 3 * count); return (True, "QUANTIZED-ROT")
            br.read_bits(96 * count); return (True, "")
        if ctype == "FTransform":
            br.read_bits(59 + 96 + 96); return (True, "")
        # object reference / sub-class / container
        if (kind == "C" or ctype == "UObject" or ctype.startswith(("U", "A"))
                or "SubclassOf" in ctype or ctype in ("TArray",)
                or ctype.startswith(("TArray", "TMap", "TSet"))):
            if ctype in ("TArray",) or ctype.startswith("TArray"):
                n = br.read_intpacked()
                if not plausible_intpacked(n):
                    return (False, "TArray count")
                for _ in range(n):
                    br.read_intpacked()
                return (True, "ARRAY-APPROX")
            if ctype.startswith(("TMap", "TSet")):
                n = br.read_intpacked()
                if not plausible_intpacked(n):
                    return (False, "TMap count")
                for _ in range(n):
                    br.read_intpacked(); br.read_intpacked()
                return (True, "MAP-APPROX")
            g = br.read_intpacked()
            if not plausible_intpacked(g):
                return (False, "objref")
            return (True, "OBJREF")
        if kind in ("S", "E"):
            return self._eat_struct(ctype, br, depth + 1)
        if size:
            br.read_bits(8 * size * count); return (True, "RAW-SIZE-FALLBACK")
        return (False, "unknown type " + ctype)

    def _eat_struct(self, ctype, br: BitReader, depth=0):
        if depth > 8:
            return (False, "struct recursion limit")
        d = self._get_def(ctype)
        if not d:
            return (False, "missing struct " + ctype)
        props = d.get("props") or d.get("properties") or []
        for p in props:
            ok, note = self._eat_member(p, br, depth)
            if not ok:
                return (False, "struct %s: %s" % (ctype, note))
        return (True, "")

    def class_bits(self, cname, br: BitReader):
        """Consume full super-chain (base-first) + self, all members.
        Returns (bits, ok, note)."""
        e = self._get_def(cname)
        if not e:
            return (0, False, "missing class " + cname)
        chain = []
        seen = set()
        for s in e.get("super", []):
            if s not in seen:
                seen.add(s); chain.append(s)
        chain.append(cname)
        start = br.pos
        flagged = []
        for cls in chain:
            d = self._get_def(cls)
            if not d:
                return (0, False, "missing " + cls)
            props = d.get("props") or d.get("properties") or []
            for p in props:
                ok, note = self._eat_member(p, br, 0)
                if not ok:
                    return (0, False, "%s.%s: %s" % (cls, p.get("name"), note))
                if note in ("QUANTIZED-VECTOR", "QUANTIZED-ROT", "ARRAY-APPROX",
                            "MAP-APPROX", "RAW-SIZE-FALLBACK"):
                    flagged.append((cls, p.get("name"), note))
        return (br.pos - start, True, ";".join("%s:%s" % (n[1], n[2]) for n in flagged[:6]))


def main():
    sdk = json.load(open(SDK_PATH, encoding="latin-1"))
    b = Bridge(sdk)
    sys.path.insert(0, "tools")
    import frame_walk as FW, container as CM, carrier_decode as CD
    path = "sample/TyrReplay1.replay"
    c = CM.parse_container(path)
    rep = [ch for ch in c.chunks if ch.type_name == "ReplayData"]
    raw = open(path, "rb").read()
    target_ch = 13
    bodies = {}
    for ch in rep:
        data = raw[ch.data_offset: ch.data_offset + ch.size_in_bytes]
        ar = FW.ByteArchive(data); ar.bytes(16)
        while not ar.at_end() and (len(data) - ar.tell()) >= 12:
            before = ar.tell()
            try:
                fr, adv = FW.read_frame(ar, False, False)
            except Exception:
                break
            if fr is None or ar.tell() <= before:
                break
            for pkt in fr.packets:
                for bun in pkt.bunches:
                    if bun.b_control or bun.ch_index != target_ch:
                        continue
                    pl = bun.reassembled_payload
                    if len(pl) < 4:
                        continue
                    if CD.classify(pl) == "A_large":
                        n = struct.unpack_from("<H", pl, 0)[0]
                        body = pl[2 + 2 * n:]
                        # keep the longest (reassembled logical bunch)
                        if target_ch not in bodies or len(body) > len(bodies[target_ch]):
                            bodies[target_ch] = body
    target = bodies.get(target_ch)
    if target is None:
        print("ch=13 A_large body not found")
        return
    total_bits = len(target) * 8
    print("ch=13 body len =", len(target), "bits =", total_bits)

    exact, near = [], []
    for cname in list(b.classes.keys()):
        br = BitReader(target)
        try:
            bits, ok, note = b.class_bits(cname, br)
        except EOFError:
            continue
        if not ok:
            continue
        if bits == total_bits:
            exact.append((cname, note))
        elif abs(bits - total_bits) <= 64:
            near.append((cname, bits, total_bits - bits, note))
    print("EXACT full-consumption matches:", len(exact))
    for cname, note in exact[:40]:
        print("  ", cname, note)
    print("\nNEAR matches (<=64 bits slack):", len(near))
    for cname, bits, slack, note in sorted(near, key=lambda x: -x[2])[:40]:
        print("  ", cname, "consumed", bits, "slack", slack, note)


if __name__ == "__main__":
    main()
