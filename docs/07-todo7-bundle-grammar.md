# Phase 06 — Todo 7: U1 bundle wire grammar (binary deep-dive)

STATUS: IN PROGRESS (2026-07-14). Not yet closed. Validated negatives so far;
no validated positive decoder yet.

## What is known (PROVEN)
- The TYR `.usmap` is a real, fully-parsed runtime type table: 57,561 names,
  2,659 enums, 14,050 structs (606 TYR-specific). [tools/usmap_parse.py,
  out/usmap_schema.json]
- A single-class (flat or recursive) decode of the 1936B ch=13 blob against
  the FULL .usmap struct set yields ZERO full-consumption matches
  (tools/u1_decode_usmap.py, MODE2: 0/5347). => the blob is a HIERARCHICAL
  OBJECT BUNDLE, not one class's serialized state. (todo 8, validated
  negative.)
- The 1936B blob is a ONE-TIME initial snapshot: ch=13 appears in 90 frames
  with 86 distinct bodies; the 1936B form occurs once (frame 1), and later
  frames carry 32..174B deltas. => initial vs delta path is real on the wire.

## Empirical observations (OBSERVATIONS, not yet hypotheses — need source/anvil)
Replay: sample/TyrReplay1.replay. Family-A/E bunches extracted via
frame_walk + carrier_decode (same extraction as prior phases).

1. `A_large` size classes (all 10 files consistent shape):
   - n=31, body=1936B : 1 occurrence (ch=13, initial snapshot)
   - n=2,  body=39/47B : 490 occurrences (clean two-subobject delta case)
   The n=2 bodies are the tractable decode target.

2. n=2 body keys are a stable subobject PAIR, e.g. [595, 603] (ch=13/30/35/45/46),
   [1611,1611] (ch=53), [595,1259] (ch=51). The two static handles identify the
   two subobjects whose state is bundled. Per OA-06-2, these are Iris static
   handles (odd => static; 98%+ odd).

3. IntPacked-linearization of a typical n=2 body (ch=13, frame 5):
   75, 0, 672008, 2305, 0, 12354, 75, 544, 1212416, 0, 70664, 1214464, 0, 8,
   554, 1217536, 0, 0
   - `75` (0x4b) recurs as a mid-stream delimiter in 95/490 n=2 bodies.
     The remaining 395 start with other lead bytes (229, 133, 53, 213, 180, 11,
     69, 65, 117, ...). => `75` is a record-TYPE tag / subobject-record marker
     for a specific sub-record subtype, NOT a universal subobject delimiter.
   - Values cluster: small ints (0..2305), large ints (672008, 1212416,
     1214464, 1217536 — these look like SERIALIZED FLOATS: 1212416 = 0x128400
     is not a clean IEEE32, but 0x4980ee00/0x4980... patterns recur; needs
     bit-level (not intpacked) decode).
   - Trailing `0, 0` in many bodies: likely a terminator / end-of-state marker.

4. IMPORTANT CORRECTION of the prior "count:u16 + N*u16 + body" framing: the
   `count` is the number of subobject HANDLES, and each handle indexes a
   subobject whose state is serialized as a SEPARATE sub-record inside the body
   (not a flat concatenation). The body is a SEQUENCE OF SUBOBJECT RECORDS, one
   per handle, each with its own internal header (the recurring `75`/type tag).

## Binary Iris module anchor map (authoritative, from PDB path strings)
These are the .rdata RVA positions of embedded PDB path strings for the Iris
replication modules in `Binaries/Win64/TyrClient-Win64-Shipping.exe`. They
localize the compiled code region for each module (coarse landmark; exact
function offsets need the .reloc serializer tables). Verified present:

  Engine/Private/Net/Iris/ReplicationSystem/ReplicationSystemUtil.cpp  0xa08bc00
  Engine/Private/Net/Iris/.../DataStreamChannel.cpp                   0xa089c70
  Engine/Private/Net/Iris/ReplicationSystem/EngineReplicationBridge.cpp 0xa089e90
  Engine/Private/Net/Iris/ReplicationSystem/NetActorFactory.cpp       0xa08a820
  Engine/Private/Net/Iris/ReplicationSystem/NetSubObjectFactory.cpp    0xa08b140
  Engine/Private/DataReplication.cpp                                  0x9f55da0
  Engine/Private/GameFramework/CharacterNetworkSerializationPackedBitsNetSerializer.cpp 0x9f8fe90
  Engine/Private/Engine/HitResultNetSerializer.cpp                    0x9f8bc40
  Engine/Private/GameFramework/UniqueNetIdReplNetSerializer.cpp        0x9f95270

NOTE: the trailing QWORD runs after each path string (e.g. `0x0100...E&A`
patterns) are the vtable/serializer dispatch pointers for that module —
this is where the per-type NetSerializer Serialize/Deserialize stubs live,
keyed by the 17,648 .reloc-derived function-pointer tables.

The `CharacterNetworkSerializationPackedBitsNetSerializer` module maps
DIRECTLY to the `CharacterNetworkSerializationPackedBits` struct seen in the
usmap schema (606 TYR structs + UE primitives). This is the bridge point:
that NetSerializer's bit-width is exactly what we need to decode the
per-subobject records.

## Source-research cross-check (UE5.6)
A source-research subagent is reading /home/gcurr/tyr/UE to fix the EXACT
Iris snapshot/initial-state wire grammar (change-mask bits, member order,
per-type widths, subobject batching). Its findings will pin the disassembly
target precisely so todo-7 step (c) disassembles the right serializer stubs.
Result pending — see appended notes when it lands.

## The binary deep-dive (todo 7) — pending
Goal: recover the per-subobject-record serialization grammar (member bit
layout, change-mask, serializer widths) from TYR's Shipping binary so the
usmap property lists can be mapped onto the blob bytes.

Anchors available (from prior commits ad3c315/d080ff1; treat VA labels with
skepticism — `/GL` + .rdata reloc means raw VAs in prior notes may be stale):
- 44 embedded Iris `*.cpp` PDB path strings (binary_harness.py landmarks).
- 17,648 serializer function-pointer-table runs in `.rdata` via `.reloc`
  DIR64 (find_serializer_tables.py) — the authoritative anchor for the
  NetSerializer Serialize/Deserialize dispatch region.

Plan:
  (a) Use UE5.6 source (subagent) to fix the EXACT Iris snapshot/initial
      state grammar (change-mask bits, member order, per-type widths,
      subobject batching) — so the binary disassembly has a precise target.
  (b) Anchor the serializer-region VAs from /tmp/serializer_tables.json.
  (c) Disassemble each subobject-record serializer; recover the byte/bit
      layout for the recurring record subtypes (the `75`-led one and the
      other lead-byte families).
  (d) Build a structural validator: re-segment each n=2 body into subobject
      records, decode each with the recovered layout, assert clean
      consumption + non-tautological invariants (NOT "any bytes consume").

## Honesty note
No claim of U1 closure until (d) passes a non-tautological validator across
all 10 files. The 36 "MODE1 hits" tautology (random/zero controls) remains
the anti-pattern to avoid.
