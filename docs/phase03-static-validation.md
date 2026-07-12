# Phase 03 — Static Validation of Bit-Level Primitives

**No live debugger is available on this project** (see `00-overview-and-setup.md`
Step 0.3 revised). The phase doc's validation item 3 calls for a static
disassembly / instruction-level trace of `SerializeIntPacked` and
`FBitReader::SerializeBits`, confirming bit-for-bit behavior against this
prototype. This document is that trace. It substitutes for a live register/memory
ground-truth diff by walking the actual engine C++ source line by line and
showing the prototype's logic is a faithful, bit-identical reimplementation.

All line references are to the curated `/UE` source subset present in this repo.

---

## 1. Bit ordering — the critical correction

**Finding:** The Phase-00 scaffold `BitReader.read_bit` (tools/bitreader.py as
committed under phase00) read bits **MSB-first** within each byte. That is
**WRONG** for UE5.6 and would silently corrupt every downstream phase. The
Phase-03 rewrite corrects this to **LSB-first**.

Evidence (read character by character):

- `UE/BitReader.cpp:136` (`FBitReader::ReadBit`):
  ```cpp
  Bit = !!(Buffer[(int32)(LocalPos>>3)] & Shift(LocalPos&7));
  ```
  with `Shift(Cnt) = 1 << Cnt` (`UE/BitReader.h:246-249`). So bit 0 of the
  stream reads `Buffer[byte] & (1<<0)` = the **LSB** of the byte. Bit 1 reads
  `(1<<1)`, etc. => **LSB-first**.

- `UE/BitWriter.cpp:94` (`FBitWriter::WriteBit`):
  ```cpp
  if (In) Buffer[Num>>3] |= GShift[Num&7];
  ```
  with `GShift[i] = 1<<i` (`UE/BitReader.cpp:17`). Writer sets **bit 0** of the
  byte for the first written bit. Reader/writer are symmetric => LSB-first.

- `UE/BitReader.cpp:65` (`SerializeBits`, single-bit case):
  ```cpp
  if (Buffer[(int32)(Pos>>3)] & Shift(Pos&7)) ((uint8*)Dest)[0] |= 0x01;
  ```
  The first stream bit maps to `Dest[0]` bit 0 (LSB). Confirms reassembly is
  LSB-first: first bit read -> bit 0 of the integer.

The Phase-03 prototype implements `read_bit` as
`mask = 1 << (self._pos & 7); bit = (byte & mask) != 0` — bit 0 of the byte =
LSB. **Matches source.**

---

## 2. SerializeIntPacked — bit-by-bit static trace

Source: `UE/BitReader.cpp:313-352` (`FBitReader::SerializeIntPacked`) and the
encoder `UE/BitWriter.cpp:245-281` (`FBitWriter::SerializeIntPacked`). Same
7-bit-payload + 1-bit-continuation (LSB) scheme as `FArchive::SerializeIntPacked`
(`UE/Archive.cpp:1366-1419`).

Encoding rule (BitWriter):
```
for each group (from LSB):
    chunk = value & 0x7F           // 7 payload bits
    value >>= 7
    more  = (value != 0)           // 1 if another group follows
    byte  = (chunk << 1) | more    // continuation bit is the LSB
```

Decoding rule (BitReader), bit-position aware (may straddle bytes):
```
byte       = ((Src[0] >> BitUsed) & Mask0) | ((Src[Next] & Mask1) << BitLeft)
more       = byte & 1
chunk      = byte >> 1
value     |= chunk << (7 * group_index)
```

### Trace #1: value = 128  (encoder yields bytes 0x01, 0x02)

Encoder:
- group0: chunk = 128 & 0x7F = 0; value>>=7 -> 1; more=1; byte = (0<<1)|1 = **0x01**
- group1: chunk = 1 & 0x7F = 1; value>>=7 -> 0; more=0; byte = (1<<1)|0 = **0x02**

Stream bytes: `[0x01, 0x02]`.

Decoder (byte-aligned, BitUsed=0, BitLeft=8, Mask0=0xFF, Mask1=0, Next=1):
- group0: Src[0]=0x01 -> byte=0x01; more=(0x01&1)=1; chunk=0x01>>1=0; value += 0<<0 = 0
- group1: Src[1]=0x02 -> byte=0x02; more=(0x02&1)=0; chunk=0x02>>1=1; value += 1<<7 = 128
- more==0 -> stop. **value = 128. ✓**

### Trace #2: value = 16384 = 0b100_0000_0000_0000  (bytes 0x01, 0x01, 0x02)

Encoder:
- group0: chunk = 16384 & 0x7F = 0; v=128; more=1; byte = **0x01**
- group1: chunk = 128 & 0x7F = 0; v=1; more=1; byte = **0x01**
- group2: chunk = 1 & 0x7F = 1; v=0; more=0; byte = **0x02**

Decoder:
- g0: 0x01 -> more=1, chunk=0, value=0
- g1: 0x01 -> more=1, chunk=0, value=0
- g2: 0x02 -> more=0, chunk=1, value += 1<<14 = 16384
- **value = 16384. ✓**

These match the hand-constructed vectors asserted in
`tools/selftest_bitreader.py` (S3a) and the module `__main__` smoke test.

### Non-aligned straddle (the part the Phase-00 scaffold got WRONG)

The Phase-00 scaffold's `serialize_int_packed` did `if not byte_aligned(): pad
to next byte`. That is incorrect: `FBitReader::SerializeIntPacked` reads at the
**current bit position** (`Src = Buffer + (Pos>>3); BitUsed = Pos&7`) and
straddles bytes via `MaskByte0`/`MaskByte1`. The Phase-03 reader reproduces the
exact mask logic, verified by `selftest_bitreader.py` S3c (decode at alignment
offsets 0/1/3/7 round-trips correctly).

---

## 3. SerializeIntPacked64 — FNetworkGUID

Source: `UE/Archive.cpp:1421-1445` (`FArchive::SerializeIntPacked64`), identical
7/1 encoding with a 64-bit accumulator and up to 10 groups. Used by
`FNetworkGUID::operator<<` (`UE/NetworkGuid.h:34-38`).

Static check of the static/dynamic bit convention (`UE/NetworkGuid.h`):
- `IsStatic()`    => `ObjectId & 1`  (LSB is the static flag)
- `IsValid()`     => `ObjectId > 0`
- `CreateFromIndex(NetIndex, bIsStatic)` => `NetIndex << 1 | (bIsStatic ? 1 : 0)`

Trace: NetIndex=5, static=true -> ObjectId = (5<<1)|1 = 11 (0x0B).
- IsStatic: 11 & 1 = 1 ✓
- IsDynamic: (11>0) && !(11&1) = false ✓
- IsValid: 11 > 0 = true ✓

The prototype's `read_network_guid` returns `{object_id, is_static, is_valid,
is_dynamic}` with identical logic; round-tripped in `selftest_bitreader.py` S7.

---

## 4. FString

The UE5.6 `FString::Serialize` operator is **not present** in the curated `/UE`
subset, so it cannot be read line-by-line here. Instead this is validated by
**empirical byte-exact consumption**: `tools/header.py` (Phase 02) decodes the
full `FNetworkDemoHeader` for all 10 samples and asserts byte-exact consumption
(consumed == chunk size), using the `int32 len` scheme (0 empty; positive =
ANSI incl. null terminator; negative = UTF-16 code units). The Phase-03
`read_fstring` uses that same scheme and is independently re-validated against
`header.py` in `tools/revalidate_phase1_2.py` (Phase-2 re-decode, all 10 files
match). This is recorded as a *known residual assumption* in `open-assumptions.md`
(see Phase 03 note) because the operator<< itself was not source-read.

---

## 5. Network FName

Source: `UE/CoreNet.cpp:306-365` (`UPackageMap::StaticSerializeName`).
- 1 bit `bHardcoded`.
- If set: `SerializeIntPacked(NameIndex)` -> `EName`; hardcoded names carry no
  Number. (Version gating: `EngineNetVer < ChannelNames` used `SerializeInt`;
  TYR is at `HISTORY_USE_CUSTOM_VERSION=19` >= `ChannelNames`, so
  `SerializeIntPacked`.)
- Else: `Ar << InString << InNumber` (FString + int32 Number), **after
  `EatByteAlign()`** before the FString (`UE/BitReader.cpp:193-205` —
  `EatByteAlign` pads to byte boundary; the hardcoded branch leaves the reader
  bit-aligned because SerializeIntPacked runs at the current bit pos, so the
  string branch must re-align).

The prototype's `read_fname`/`write_fname` implements exactly this, including
the `read_align()` before the FString, verified by `selftest_bitreader.py` S6.

---

## Validation summary

| Check | Source | Result |
|---|---|---|
| Bit order LSB-first | BitReader.cpp:136, BitWriter.cpp:94 | ✓ (S1, S2; corrected scaffold bug) |
| SerializeIntPacked hand vectors | BitReader.cpp:313, Archive.cpp:1366 | ✓ (S3a) |
| SerializeIntPacked 10k random RT | — | ✓ (S3b) |
| SerializeIntPacked non-aligned | BitReader.cpp:321-339 | ✓ (S3c) |
| SerializeInt range-compacted | BitReader.cpp:81, BitWriter.cpp:142 | ✓ (S4) |
| FString RT | empirical (Phase 02 byte-exact) | ✓ (S5) |
| Network FName RT | CoreNet.cpp:306 | ✓ (S6) |
| FNetworkGUID static/dynamic | NetworkGuid.h:45-94 | ✓ (S7) |
| SerializeIntPacked64 | Archive.cpp:1421 | ✓ (S8) |
| Phase 1/2 re-validation | header.py + container.py | ✓ (revalidate_phase1_2.py) |

**Residual known-unknown:** the `FString::Serialize` operator<< itself was not
read from source (absent from `/UE` subset); its scheme is instead confirmed
only via byte-exact Phase-02 consumption + Phase-03 re-validation. Tracked in
`open-assumptions.md`.
