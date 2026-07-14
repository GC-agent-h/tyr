# Phase 06 — Binary Disassembly Findings (TYR carrier serializer)

**Trigger:** user supplied `Binaries/Win64/TyrClient-Win64-Shipping.exe` (220 MB
Shipping build). Prior U1 blocker was "no TYR executable in env". That is now
lifted. This doc records what the binary yields toward closing U1.

## 1. dumper-7 contains NO runtime anchor triple (DEFINITIVE)

Audited every artifact in `dumper-7/`:

| Artifact | Content | Is it a (handle→class→value) anchor? |
|---|---|---|
| `GObjects-Dump-WithProperties.txt` | **static** class→property layout (name/type/offset only). Diff vs `GObjects-Dump.txt` shows `WithProperties` = the property *list*, not instance values. | NO — layout only, no instance values |
| `GObjects-Dump.txt` | same, no property list | NO |
| `Dumpspace/OffsetsInfo.json` | live-process memory base offsets (`OFFSET_GOBJECTS` etc.) for runtime capture | NO — capture config, not snapshots |
| `CppSDK/SDK/*.hpp` | static class/struct/function layout (mirrors SDK) | NO — layout only |
| `Dumpspace/{Classes,Structs,Enums,Functions}Info.json` | static reflection metadata | NO — layout only |
| `Mappings/*.usmap` | proprietary Iris ReplicationStateDescriptor export. **No UE magic** (first u32 = 0x430c4), **no plaintext**, zlib/raw-inflate both fail. Engine source has NO `.usmap` reader/writer (grep of `UE/` → 0 hits for a parser). Produced by an external TYR tool. | NO — undecodable without reversing that tool |
| `IDAMappings/*.idmap` | global **name dictionary only** (EObjectFlags, COND_*, PF_*, enum names). 7.4 MB of names, **no addresses**. | NO — symbol names, no address→code map |

Conclusion: a runtime anchor triple (wire key → class → a *decoded game-state
value*) does **not** exist in dumper-7. The static layout was already bridged
to the SDK at 97% (GObjects→`out/sdk_index.json`, 1846/1916). Proceeding to
binary disassembly per user directive.

## 2. Binary module map (EVIDENCE — embedded PDB __FILE__ path strings)

Shipping strips symbols, but 44 Iris `.cpp` path strings survive
(`D:\HordeAgent\Sandbox\++Tyr+release+Incremental\Sync\Engine\Source\Runtime\Experimental\Iris\...\X.cpp`).
These are emitted by the linker near each module's code, giving coarse module
localization. Key landmarks (file offset of the path string; code precedes it):

| Module | Path-string file offset |
|---|---|
| IrisCoreModule | 0x096a7aa0 |
| ReplicationStateDescriptorBuilder | 0x096a9b90 |
| ReplicationStateDescriptorRegistry | 0x096aaf30 |
| ReplicationReader | 0x096bd070 |
| ReplicationProtocolManager | 0x096bcc50 |
| ReplicationOperationsInternal | 0x096bca40 |
| ReplicationWriter | 0x096c2260 |
| ObjectReplicationBridge | 0x096b6440 |
| NetRefHandleManager | 0x096b3e60 |
| ArrayPropertyNetSerializer | 0x096c3eb0 |
| NetBitStreamUtil | 0x096c5450 |

Harness: `tools/binary_harness.py` (pefile PE parse + capstone x86-64, path-
string landmark scanner). `.text` at VA 0x1000, raw 0x600, size 0x945dc00.

## 3. Carrier body is a HIERARCHICAL OBJECT BUNDLE (reframing from data)

Re-examined real `A_large` / `E_0100` bodies (TyrReplay1). The "body" is NOT
flat class property state. Observed sub-grammars:

* `E_0100` (N=1) and `A_large` N=2: head `4b00 a8XX 80 29 81 12 00 …`.
  `4b` = `SerializeIntPacked(75)` = number of sub-references, then repeating
  `(u16 refIndex, 28 01 a0, u16, 81 12 00)` records. This is the **object-
  reference resolution block** (`SerializeObjectReplicatedReferences` /
  `WriteContentBlock`), wiring this object's members to OTHER replicated
  objects by index. Naive primitive decode of these fails by construction.
* `A_large` N=31 (`ch=13`): keys `[587,595,…,1043]` (all ODD = static handles;
  root + 30 subobjects/components), body 1936 B, head `0c` =
  `SerializeIntPacked(12)` then a state blob. This is the **actor's full
  replicated state** (root + subobject states).
* `A_large` `ch=53/25`: different heads (`e5189c…`, `850894…`) = the **property
  STATE serializer** (per-member NetSerializers), distinct from the reference
  block.

Implication for U1: the wire u16 key → class mapping is NOT recoverable from
these bodies alone (they carry reference indices + per-object state, not the
class name). The class is established at **actor spawn** (a separate spawn
bunch carrying the UClass path / subobject class), which TYR serializes outside
the Family-A reference block. To close U1 we must:
  (a) identify TYR's spawn-bunch class-path writer (disassemble the
      `ReplicateActor`/`SerializeNewActor` path), and/or
  (b) extract per-member NetSerializer widths from the property-state serializer
      (disassemble `ReplicationOperationsInternal` / the `ch=53/25` blob writer).

## 4. Next disassembly target (not yet executed)

Pinpoint the function that emits the `SerializeIntPacked(count)` + per-
object block by:
  1. Locating `SerializeIntPacked` (distinctive varint loop: `test al,al / jnz`
     for the 7-bit-group continuation) — unique, easy to find in `.text`.
  2. Tracing its callers into the bundle writer (near `ReplicationWriter.cpp`
     @0x96c2260 and `ReplicationOperationsInternal.cpp` @0x96bca40).
  3. Extracting the per-member serialization dispatch to learn exact
     NetSerializer bit-widths for the property-state blob.

This is the remaining work to make `tools/u1_decode.py` produce a validated
full-consumption + plausible decode (Phase 06 validation gates #1 + #3).
