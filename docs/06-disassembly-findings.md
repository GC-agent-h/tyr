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

## 4. Function-level disassembly: what worked, what is blocked

**Module localization — DONE (two independent methods):**

*Method A — embedded PDB path strings.* 44 Iris `*.cpp` `__FILE__` strings
survive in `.rdata` (e.g. `ReplicationOperationsInternal.cpp` @ file 0x96bca40,
in-mem VA `0x1496BD840`; `ReplicationWriter.cpp` @0x96c2260; `ReplicationReader`
@0x96bd070; `ObjectReplicationBridge` @0x96b6440; `ArrayPropertyNetSerializer`
@0x96c3eb0). ImageBase=`0x140000000`, `.text` VA=0x1000..0x945F000, `.rdata`
VA=0x945F000.

*Method B — `.reloc` DIR64 cross-references.* Parsed the full base-relocation
table (1,752,725 DIR64 entries; 550,639 distinct target VAs). Confirmed the
binary is dense with Iris **serializer function-pointer tables**: 17,648 runs
of >=4 contiguous absolute-VA pointers into `.text`, 15,940 with >=6 entries.
The largest (`RVA=0x9461348`, 39,629 entries) is the UE vtable/name-dictionary
region; the smaller tables (8–57 entries, `RVA 0x94AE9C0`…) are the per-type
NetSerializer dispatch tables (`Serialize`/`Deserialize`/`Quantize`/
`Dequantize`/`Clone` stubs). These ARE the per-type serializer implementations
U1 needs for exact on-wire widths.

**Function-level anchoring — BLOCKED (real, explained):** With `/GL` (LTCG)
Shipping, the `__FILE__` strings are **dead data** — they are referenced only
by compiled-out `check`/`UE_LOG` metadata, NOT by any live `lea reg,[rip+X]`
or `.reloc` entry. Direct string→function mapping therefore yields 0 hits (both
the `lea` scan and the reloc-string-target scan confirm this). So a specific
serializer function cannot be trivially pinned from its `__FILE__` string alone.
The correct deep-dive to identify the exact per-type `Serialize`:
  1. Take a serializer vtable run from §4 (e.g. `RVA=0x94B2530`, 51 entries).
  2. Disassemble each pointed `.text` function; classify by shape (e.g. the
     `FVector` serializer has a fixed 3×N-bit quantize loop; `uint8` is a
     `ReadBits(N)`; `FName` is an `SerializeIntPacked` name-index + number).
  3. Cross-link to the SDK descriptor (`out/sdk_index.json`) by matching the
     `FReplicationStateMemberSerializerDescriptor`'s `SerializerConfig` layout
     (the `FVectorNetSerializerConfig` carries `NbBitsPerComponent` etc.) to the
     SDK member `ctype`/`size`. This bridges SDK class → binary serializer
     widths WITHOUT needing the class name on the wire.

## 5. Replay carries NO class-name anchor (confirmed 3 independent ways)

To close U1 we need wire-key → class. I re-verified from the TyrReplay1 bytes
that this anchor is absent on the wire (consistent with prior Phase-08
"no external anchor" conclusion):

  1. **Actor open bunches** (303 of them, ch 1..N): payloads are 12–128 B,
     numeric only (e.g. `06fb52300887c144800000ea880100`). `ch_name` is the
     hardcoded channel *type* name (name_index 102 = "Actor"), NOT the class.
     **No class-path FString** in any open-bunch payload.
  2. **Package-map export bunches** (78 of them, `b_has_package_map_exports`):
     payloads carry only numeric NetGUID→export-id pairs. **No class-path
     FString** in any export bunch.
  3. **Whole-ReplayData FString scan**: 0 length-prefixed ASCII strings matching
     `Game/`, `/Script/`, `*.{uclass}_C`, or `Tyr*` anywhere in actor-open or
     export payloads.

=> The class name lives in the binary (CppSDK has all 7,372 classes; the
`.usmap` is the cooked Iris descriptor export but is proprietary/undecodable).
The replay's numeric export indices map to classes only via the binary's cooked
package data. **Therefore the U1 class-naming closure requires the binary
descriptor-registry bridge (§4 deep-dive), not further replay-byte hunting.**

## 6. Status of U1

* KNOWN (high confidence): the Family-A `A_large` `ch=13` body (1936 B, N=31 odd
  static keys = root + 30 subobjects) is **NOT a single flat class state**. A
  SDK-descriptor-driven bit decoder (`tools/u1_bridge.py`, documented UE5.6 Iris
  NetSerializer widths, brute-force over all 7,372 SDK classes) achieved
  **0 exact AND 0 near (<=64-bit-slack) full-consumption matches** against the
  1936 B blob. This is a REAL negative result (random/flat-class layouts do not
  all miss by >64 bits), confirming the blob is a *recursive hierarchical
  bundle* (root object record + per-subobject state records), not one class's
  initial state. The per-subobject classes are unknown (no wire anchor).
* KNOWN: no class-name anchor on the wire (3 confirmations, §5).
* KNOWN: all Iris serializer modules + the serializer vtable region located in
  the binary (§4).
* **SUSPECT / RETRACTED (was "SerializeIntPacked(75) reference block"):** the
  internal byte framing of `E_0100`/`A_large` bodies is NOT yet determined from
  data. The `4b00` head cannot be `SerializeIntPacked(75)` count (E_0100 bodies
  are 36 B; 75 records don't fit), and candidate recursive frames (u16
  objIdx+refCount+8 B records) consume only 5 B then desync. The exact on-wire
  framing requires the binary serializer deep-dive (§6), not data-guessing.
* CANDIDATE / OPEN: exact per-member NetSerializer bit-widths + the bundle's
  record framing — requires the §6 binary descriptor-registry bridge
  (function-level deep-dive, not yet executed). Until that bridge exists,
  `u1_decode.py` cannot produce a validated full-consumption + plausible decode,
  so U1 is NOT closed.
