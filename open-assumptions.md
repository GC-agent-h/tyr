# Open Assumptions — Known Residual Uncertainties

This tracker records places where a result is validated by *indirect* evidence
(empirical byte-exact consumption, round-trip, or static reasoning) rather than
by reading the authoritative engine source operator<< directly, because either
(a) no live-debugger ground-truth is available, or (b) the relevant source file
is absent from the curated `/UE` subset. Each entry is a TRUE KNOWN-UNKNOWN, not
a confirmed fact. Items are closed when direct source evidence is obtained.

Per README rule: "record any resulting uncertainty in an `open-assumptions.md`
tracker rather than silently treating it as confirmed."

---

## Phase 03 — Bit-Level Primitives

### OA-03-1 — FString::Serialize operator not source-read
- **What:** The UE5.6 `FString` archive `operator<<` (the int32-length scheme:
  0 = empty, positive = ANSI incl. null terminator, negative = UTF-16 code units)
  was **not** read from engine source — the operator is absent from the curated
  `/UE` subset (only BitReader/BitWriter/Archive/CoreNet/NetworkGuid/UnrealNames
  are present).
- **What validates it instead:** `tools/header.py` (Phase 02) achieves
  **byte-exact consumption** of the full `FNetworkDemoHeader` across all 10
  samples using this scheme, and `tools/revalidate_phase1_2.py` re-decodes those
  same FString fields through the Phase-03 `BitReader.read_fstring` and matches
  `header.py` on every file. Strong empirical confirmation, but not a direct
  source read.
- **Risk:** The negative-length = UTF-16 convention is known to have changed in
  some UE5 builds; if TYR used a different encoding, Phase-02 byte-exact would
  already have failed (it did not). Confidence: high-but-indirect (PROBABLE).
- **Close condition:** obtain `UE/Containers/UnrealString.cpp` (or
  `FString::Serialize`) from the 5.6 source and confirm the sign convention
  line by line.

### OA-03-2 — Network FName hardcoded-index version gating
- **What:** `UPackageMap::StaticSerializeName` (CoreNet.cpp:306) uses
  `SerializeInt` for the hardcoded name index when
  `EngineNetVer < FEngineNetworkCustomVersion::ChannelNames`, else
  `SerializeIntPacked`. We assume TYR is at `HISTORY_USE_CUSTOM_VERSION=19`
  (observed in ReplayTypes.h header), which is >= ChannelNames, so
  `SerializeIntPacked` is used.
- **What validates it:** the header-derived version is 19 and the
  hardcoded-index path uses `SerializeIntPacked` in the writer (CoreNet.cpp:354)
  unconditionally on the save side; the load-side branching is symmetric. We have
  not yet observed an actual on-wire FName in a replay to confirm the branch
  taken at runtime.
- **Close condition:** decode a real FName in a Phase-05/06 bunch and confirm
  the bit reads as 1 (hardcoded) followed by a packed index (or 0 + FString).

---

## Phase 06 — Property Replication (Iris)

### OA-06-1 — SDK lacks per-property COND_* / InitOnly / LifetimeConditional traits
- **What:** Iris's `FPropertyReplicationStateDescriptorBuilder::CreateDescriptorsForClass`
  (`UE/Iris/Private/Iris/ReplicationState/ReplicationStateDescriptorBuilder.cpp`,
  lines ~2870-3040) routes each replicated member into one of three
  `FReplicationStateDescriptor` *states* based on reflection traits the engine reads
  from `FProperty`:
    * **Init state** — members with `InitOnly` trait (`CPF_Init` / `RF_Init`).
    * **LifetimeConditional state** — members with `HasLifetimeConditionals` trait
      (= a non-`COND_None` `ReplicationCondition`), including `NetCullDistanceSquared`
      which the builder force-injects for Actor heirs (lines 2951-2976).
    * **Regular state** — members that are neither `InitOnly` nor conditional.
      These are the delta-updated members; each gets `ChangeMaskBits` (default 1).
  The Dumper-7 SDK dump (`out/sdk_index.json`) exposes per property only
  `{name, type, kind, offset, size, count, subtypes, iris_serializer_hint}`. A full
  tree grep of `dumper-7/Dumpspace/*.json` finds **zero** `ReplicationCondition` /
  `COND_*` / `RepIndex` / `InitOnly` metadata. So the Init/Regular/LifetimeConditional
  assignment **cannot be rebuilt from reflection alone** — only the flat member
  *order* (ClassReps / declaration order) is source-determinable from the SDK.
- **How sub-step 1 handles it:** `tools/iris_state_builder.py` builds the source-exact
  ClassReps-order member list and the 3-state container, but classifies every member
  as **Regular** by default (the correct Iris default for an un-trait-ed property,
  lines 2939-2942) except `NetCullDistanceSquared` on Actor heirs (forced conditional).
  The precise Init/Regular split is then derived **empirically from the wire** in the
  sub-step-1 cross-validation harness (commit #2): initial-state blocks carry all
  Init+Regular members unmasked; delta blocks carry only Regular members under the
  change mask. Observed per-class membership under each block type populates
  `IrisStateBuilder.STATE_OVERRIDES`.
- **Risk:** If TYR sets `COND_InitialOnly`/`InitOnly` on any property, those members
  would be mis-routed to Regular until the wire harness reclassifies them. Until the
  cross-check runs, confidence on the *state split* is PROBABLE (source-discerned
  default) and the *member order* is KNOWN (declaration order, confirmed equal to
  offset order in the TYR dump).
- **Close condition:** complete the empirical wire cross-check (commit #2) and confirm
  Init-state blocks contain exactly the expected Init set; OR obtain the per-property
  `ReplicationCondition` from the running binary / a richer Dumper-7 dump.

### OA-06-2 — Iris `FReplicationReader` envelope refuted (option iii CLOSED); real carrier is a structured actor-bunch payload of UNKNOWN grammar

**Status (2026-07-13, updated):** The pristine UE5.6 `FReplicationReader::Read`
envelope (ReplicationReader.cpp:2924 — `[2-bit debug features][16-bit
ObjectBatchCountToRead][if>0: 16-bit DestroyedObjectCount + destroy records]`)
is **refuted as the carrier** in TYR's replays, via THREE independent static
checks (any one would be strong; all three agree):

1. **Per-bunch bit-level test** (`tools/diag_carrier.py`, TyrReplay1): every one
   of 84,536 reassembled bunch payloads was fed through a strict Iris-envelope
   prefilter (debug==0 AND ObjectBatchCount in [1,8192) AND, if>0,
   DestroyedObjectCount in sane range AND destroy records parse without
   overflow). **0** payloads passed. 71,472 payloads begin with `debug==3`
   (invalid for a shipping build where `ensure(StreamDebugFeatures==None)`),
   only 38 begin with `debug==0`, and none of those with a sane object count.
2. **Byte-aligned scan** of the ReplayData chunk (prior OA-06-2 evidence,
   `tools/_dbg_scan2.py`): 0 clean `walk_manager` decodes.
3. **Bit-aligned scan** (`tools/scan_iris_bits.py`, TyrReplay1, ~3.99M bits):
   only 20 offsets passed a *loose* prefilter — a 5e-6 hit rate consistent with
   statistical noise, not signal. A real envelope would appear at a bounded
   number of true offsets.

**Conclusion:** TYR's replication data does NOT ride in the pristine
`FReplicationReader::Read` bitstream under ANY framing (not in a separate
UDataStreamManager region, not byte-aligned inside bunches, not bit-aligned
anywhere in the chunk). Option (iii) of the original OA-06-2 ("Iris region
under a different framing") is **closed/refuted**.

**What the real carrier IS (observed, NOT yet decoded):**
- It lives **inside actor-channel bunch payloads** (`reassembled_payload`), i.e.
  the replay uses the legacy DemoNetDriver transport (frames/packets/bunches,
  Phase 05) but the bunch *contents* are neither the Iris `Read` envelope nor
  (as tested) a simple legacy `FRepLayout` count-prefixed array.
- It is **structured and regular**, with at least two recurring families seen
  in `tools/diag_dump_largest.py` + `tools/diag_channel_map.py`:
  - Family A (largest bunches, ch 228/229/13): leading `0x21`/`0x1f`
    (SerializeIntPacked-decoded small count) then a fixed-stride **u16 LE**
    stream incrementing by a constant (e.g. `1c77, 1c7f, 1c87, ...` = +8;
    or `2a22, 5a32, ...` = +0x1010). The stride-constant ramp suggests an
    index/offset table rather than raw semantic values.
  - Family B (many channels, control+open spawn bunches and updates): leading
    `0100`/`0200`/`0300`/`0400`/`0700` (SerializeIntPacked64-decoded to small
    counts 0,1,2,3,7) followed by larger u16 values in the ~0x0800–0x2200
    range (≈2000–8700), which are in the plausible **object-index / NetRefHandle
    range** (cross-reference against Phase-04 resolved handles still TBD).
- `DataChannel.cpp` in this `/UE` subset only routes Iris **control** messages
  (NMT_IrisProtocolMismatch / NMT_IrisNetRefHandleError / …) — it does NOT
  handle the Iris data stream inside actor bunches, corroborating that the
  data stream is not the standard `FReplicationReader` shape here.

**Interpretation (CANDIDATE, not confirmed):** TYR ships a **customized/older
Iris variant** OR a **game-specific replication carrier** whose wire envelope
differs from the 5.6 source we have. The Phase-06 Iris `FReplicationReader`
decoders in `tools/iris_datastream.py` / `tools/iris_datastream_manager.py`
remain source-accurate for pristine 5.6 (reusable if the real variant is ever
obtained) but do **not** match TYR's bytes.

**Next action (authorized by original OA-06-2 close-condition (i)/(ii)):**
decode the OBSERVED carrier. Concrete plan correction recorded in
`docs/06-property-replication.md` ("Plan correction — Iris envelope refuted"):
the Phase-06 work must now target the actual actor-bunch payload grammar, not
the pristine Iris `FReplicationReader`. Validation = full bit/byte consumption
of real payloads + semantic plausibility (positions in level bounds, etc.) per
the phase doc's Validation section.

**Close condition:** successfully decode Family A and/or B payloads (full
consumption + at least one semantically-plausible value anchored to a
Phase-04-resolved object), OR obtain TYR's actual Iris variant source/binary
and re-run the envelope scan against it.

- **Risk:** until the carrier grammar is decoded, sub-steps 2-6 (dirty-state,
  NetSerializers, FastArray) cannot be validated against real bytes. The
  decoder artifacts remain correct per source grammar and reusable.
- **What:** The Phase 06 handoff assumed TYR's Iris replication data appears as a
  `FReplicationReader` envelope (ReplicationReader.cpp:2924-2986:
  `[2-bit debug features][u16 ObjectBatchCountToRead][u16 DestroyCount][destroy records][batches...]`)
  either (a) inside a legacy UChannel bunch payload, or (b) in a separate
  `UDataStreamManager` region appended after the bunch stream in the same packet
  buffer (DataStreamManager.cpp:841-905). A source-faithful decoder for BOTH
  layouts was built and passes synthetic round-trip self-tests
  (`tools/iris_datastream.py`, `tools/iris_datastream_manager.py`).
- **Empirical refutation (TyrReplay1, 2026-07-13):**
  1. **Post-bunch residual:** re-walking every packet's bunch stream and
     slicing trailing bits — 0 of ~all packets had ANY residual bits
     (`tools/probe_iris_region.py`). The bunch loop consumes the entire packet
     buffer, so no separate Iris region trails the bunches.
  2. **Bunch-payload scan:** feeding every channel's reassembled-bunch payload
     (incl. the largest, 2000 bytes on ch13 @frame16) through `walk_payload` —
     the first 2 bits read as `debug_features=3` (invalid; shipping=0) and the
     16-bit batch count reads as 49159 (garbage). The payload is a real,
     substantial game payload but is NOT the Iris envelope
     (`tools/_dbg_largest.py`).
  3. **Byte-aligned brute scan:** scanning every byte offset in the ReplayData
     chunk for a clean `walk_manager` decode (strict prefilter: StreamCount in
     [1,8], mask bit0 set, debug features ∈ {0,1,2}) — 0 hits across the first
     80k offsets of the main chunk (`tools/_dbg_scan2.py`).
  4. **Chunk inventory:** the replay contains only `Header`, `ReplayData`,
     `Checkpoint` chunks — no dedicated Iris blob chunk.
- **Interpretation (PROBABLE, not confirmed):** TYR's replication does NOT use
  the pristine UE5.6 Iris `UDataStreamManager`/`FReplicationReader` packet
  region in this replay. Two candidate explanations, neither confirmed:
  (i) TYR uses the **legacy UE actor-channel property-replication** path (bunch
  payloads carry property updates directly via `UActorChannel`/RPC-style
  serialization, not Iris), so there is no Iris envelope to find; or
  (ii) TYR uses a **customized/older Iris variant** whose wire envelope differs
  from the 5.6 source in `/UE`, so the modeled grammar doesn't match the bytes.
- **Risk:** until the real carrier is identified, sub-steps 2-6 (dirty-state
  change-mask, NetSerializers, FastArray) cannot be validated against real
  bytes. The decoder artifacts remain correct per source grammar and reusable
  once the correct carrier is known.
- **Close condition:** identify the actual replication carrier — either (i)
  confirm legacy actor-channel bunch payloads ARE the property data (decode one
  as classic UE property replication), or (ii) obtain TYR's actual Iris
  `FReplicationReader`/`UDataStreamManager` variant and re-run the scan, or
  (iii) find the Iris region under a different framing (e.g. NetBlob attachment
  path, or interleaved within a specific control channel's bunch).

---

## Caveat on the Phase-00 scaffold

The Phase-00 `tools/bitreader.py` `read_bit` was **MSB-first**, which is
incorrect for UE5.6 (source: BitReader.cpp:136). This was corrected to LSB-first
in Phase 03. Any tool written between Phase 00 and Phase 03 that relied on the
scaffold's `read_bit`/`read_bits` for multi-bit values (other than the already
byte-exact Phase 01/02 `struct.unpack` paths) must be re-checked. Phase 01/02
used `struct.unpack` (byte-aligned), so they are unaffected; the correction only
matters for future bit-level work, which is exactly why Phase 03 was validated
in isolation first.
