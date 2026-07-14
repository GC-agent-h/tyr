"""Parse the TYR `.usmap` via a faithful port of UAssetAPI's ReadUSMAP.

File layout: a 16-byte wrapper, then a raw ZSTD frame (magic 0x28B52FFD).
Decompressing yields the Usmap BODY with NO magic/version byte (the version
lives in the wrapper, which we do not decode). The body is exactly the
post-header stream that UAssetAPI.Unversioned.Usmap.ReadUSMAP parses:

  names : i32 numNames
          x numNames: i16 len (LongFName), len bytes ASCII
  enums : i32 numEnums
          x numEnums: i32 nameIdx
                      u16 numEntries            (LargeEnums)
                      x numEntries: i64 value, i32 nameIdx   (ExplicitEnumValues)
  schema: i32 numSchemas
          x numSchemas: i32 nameIdx, i32 superIdx,
                        u16 numProps, u16 serializablePropCount
                        x serCount: u16 schemaIdx, u8 arraySize,
                                    i32 nameIdx, DeserializePropData
  (optional "CEXT" extension block follows)

Version flags are inferred from the data:
  - names use u16 lengths            -> LongFName = True
  - enum0 = EAutomationEventType -> [(0,Info),(1,Warning),(2,Error),(3,MAX)]
    parses cleanly with u16 count + i64/name entries -> LargeEnums + ExplicitEnumValues = True
  (validated empirically; matches UE5.6 usmap produced by Zen/Iris).

This is the authoritative runtime TYPE schema: each object/struct -> ordered
(property name, property type, inner type, schemaIdx, arraySize). It is the
anchor for decoding Iris replication blobs (negates the earlier mistaken
"usmap is undecodable" conclusion).
"""
from __future__ import annotations
import struct
import zstandard as zstd

E_PROP = ["ByteProperty","BoolProperty","IntProperty","FloatProperty","ObjectProperty",
    "NameProperty","DelegateProperty","DoubleProperty","ArrayProperty","StructProperty",
    "StrProperty","TextProperty","InterfaceProperty","MulticastDelegateProperty",
    "WeakObjectProperty","LazyObjectProperty","AssetObjectProperty","SoftObjectProperty",
    "UInt64Property","UInt32Property","UInt16Property","Int64Property","Int16Property",
    "Int8Property","MapProperty","SetProperty","EnumProperty","FieldPathProperty",
    "OptionalProperty","Utf8StrProperty","AnsiStrProperty"]
# index aliases for DeserializePropData recursion
T_ARRAY, T_STRUCT, T_MAP, T_SET, T_ENUM, T_OPTIONAL = 8, 9, 24, 25, 26, 28


class Usmap:
    def __init__(self, path):
        raw = open(path, "rb").read()
        off = raw.find(b"\x28\xb5\x2f\xfd")
        if off < 0:
            raise ValueError("no zstd frame in usmap")
        self.body = zstd.ZstdDecompressor().decompress(raw[off:])
        self._read()

    def _u8(self, p):  return self.body[p]
    def _u16(self, p): return struct.unpack_from("<H", self.body, p)[0]
    def _u32(self, p): return struct.unpack_from("<I", self.body, p)[0]
    def _i64(self, p): return struct.unpack_from("<q", self.body, p)[0]

    def _read(self):
        b = self.body
        pos = 0
        # ---- names (LongFName: u16 length) ----
        nc = self._u32(pos); pos += 4
        names = []
        for _ in range(nc):
            L = self._u16(pos); pos += 2
            names.append(b[pos:pos + L].decode("latin-1")); pos += L
        self.names = names
        N = len(names)

        # ---- enums ----
        ec = self._u32(pos); pos += 4
        enums = []
        for _ in range(ec):
            nidx = self._u32(pos); pos += 4
            cnt = self._u16(pos); pos += 2          # LargeEnums -> u16
            vals = []
            for _2 in range(cnt):                    # ExplicitEnumValues
                v = self._i64(pos); pos += 8
                ni = self._u32(pos); pos += 4
                vals.append((v, names[ni] if 0 <= ni < N else f"?{ni}"))
            enums.append((names[nidx] if 0 <= nidx < N else f"?{nidx}", vals))
        self.enums = enums

        # ---- schemas ----
        sc = self._u32(pos); pos += 4
        structs = []
        for _ in range(sc):
            nidx = self._u32(pos); pos += 4
            snidx = self._u32(pos); pos += 4
            num_props = self._u16(pos); pos += 2
            ser = self._u16(pos); pos += 2
            props = []
            for _2 in range(ser):
                sid = self._u16(pos); pos += 2
                ar = self._u8(pos); pos += 1
                pnidx = self._u32(pos); pos += 4
                ptype, inner = self._deser_prop(pos, N)
                pos = inner["pos"]
                props.append((names[pnidx] if 0 <= pnidx < N else f"?{pnidx}",
                              ptype, sid, ar, inner))
            structs.append((names[nidx] if 0 <= nidx < N else f"?{nidx}",
                            names[snidx] if 0 <= snidx < N else "", num_props, props))
        self.structs = structs

        # ---- optional extension block (CEXT / legacy) ----
        self.tail_pos = pos
        self.ext = None
        remaining = len(b) - pos
        if remaining >= 8:
            magic = self._u32(pos)
            if magic == 0x54585445:  # "CEXT"
                pos += 4
                layout = self._u8(pos); pos += 1
                n_ext = self._u32(pos); pos += 4
                self.ext = {"layout": layout, "extensions": []}
                for _e in range(n_ext):
                    ext_id = b[pos:pos + 4].decode("ascii", "replace"); pos += 4
                    ext_len = self._u32(pos); pos += 4
                    pos += ext_len  # skip extension body for now
                    self.ext["extensions"].append((ext_id, ext_len))
            elif magic == 1:
                self.ext = {"legacy": True}

    def _deser_prop(self, p, N):
        b = self.body
        t = self._u8(p); p += 1
        inner = {"type": t}
        name = E_PROP[t] if t < len(E_PROP) else f"T{t}"
        if t == T_ENUM:  # EnumProperty: inner underlying type, then enum name idx
            _, sub = self._deser_prop(p, N); p = sub["pos"]
            ni = self._u32(p); p += 4
            inner["enum"] = self.names[ni] if 0 <= ni < N else f"?{ni}"
        elif t == T_STRUCT:  # StructProperty: struct name idx
            ni = self._u32(p); p += 4
            inner["struct"] = self.names[ni] if 0 <= ni < N else f"?{ni}"
        elif t in (T_ARRAY, T_SET, T_OPTIONAL):  # Array / Set / Optional: inner type
            _, sub = self._deser_prop(p, N); p = sub["pos"]
        elif t == T_MAP:  # Map: key type, value type
            _, sub = self._deser_prop(p, N); p = sub["pos"]
            _, sub2 = self._deser_prop(p, N); p = sub2["pos"]
        inner["pos"] = p
        return name, inner

    def describe(self):
        e = ""
        if self.ext:
            e = f" ext={self.ext}"
        return (f"names={len(self.names)} enums={len(self.enums)} "
                f"structs={len(self.structs)} tail@{self.tail_pos}/{len(self.body)}{e}")

    def struct_records(self):
        out = []
        for nm, super_, num_props, props in self.structs:
            rec = []
            for (pn, ptype, sid, ar, inner) in props:
                extra = ""
                if inner.get("struct"): extra = f"<{inner['struct']}>"
                elif inner.get("enum"): extra = f"<{inner['enum']}>"
                rec.append((pn, ptype + extra, sid, ar))
            out.append((nm, super_, num_props, rec))
        return out


if __name__ == "__main__":
    import sys, glob
    path = sys.argv[1] if len(sys.argv) > 1 else glob.glob("dumper-7/Mappings/*.usmap")[0]
    u = Usmap(path)
    print("DESCRIBE:", u.describe())
    print("\nFirst 5 enums:")
    for nm, vals in u.enums[:5]:
        print(f"  {nm} ({len(vals)}):", [(v, n) for v, n in vals[:6]])
    print("\nFirst 8 structs:")
    for nm, super_, np_, props in u.struct_records()[:8]:
        print(f"  {nm} : super={super_ or '-'} props={len(props)}")
        for pr in props[:14]:
            print("     ", pr)
    # TYR-relevant structs
    tyr = [(nm, super_, np_, props) for nm, super_, np_, props in u.struct_records()
           if "Tyr" in nm or nm.endswith("_C")]
    print(f"\nTYR/BP structs: {len(tyr)} (showing 30)")
    for nm, super_, np_, props in tyr[:30]:
        print(f"  {nm} : super={super_ or '-'} props={len(props)}")
