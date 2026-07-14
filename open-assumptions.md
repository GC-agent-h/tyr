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

### OA-06-3 — U1: Family-A id namespace RESOLVED as u16-compacted Iris static handles; blob semantics remain OPEN (no anchor on wire)

**Status (2026-07-14):** The U1 *id-namespace* sub-question is RESOLVED
at CANDIDATE level (source-grounded + empirically cross-validated). The
*blob semantic decode* (what the serialized state bytes mean) REMAINS OPEN
because no static→class export table is present in these replay wire bytes.

**Evidence (source):**
- `UE/NetRefHandle.h`: `FNetRefHandle::GetId() = (Serial<<1)|Static`;
  `Serial`=53 bits, `Static`=1 bit, `ReplicationSystemId`=10 bits →
  64-bit value. Wire serialization is `WritePackedUint64`
  (`SerializeIntPacked64`), NOT u16 (`ObjectNetSerializer.cpp:29-57`).
- `IsStatic()` == ODD id; `IsDynamic()` == EVEN id (`NetRefHandle.h:60-64`).

**Evidence (empirical, all 10 files, `tools/carrier_decode.py` +
`tools/u1_probe*.py`):**
- Family-A keys are **u16**: max key ≤ 65535 in every file (files
  1/5/6/7/8/9 ≤ 9939; 2/3/4 ≤ 65535). → consistent with TYR's
  carrier compacting static handles to u16, NOT the raw 64-bit varint.
- **Odd parity 93.7%–100%, aggregate 98.77%** → matches the Iris
  `IsStatic()` ODD invariant by overwhelming majority. The 1.23% even keys
  are consistent with occasional dynamic (even) handles in the same stream.
- **Phase-04 NetToken indices are a DIFFERENT space** (millions, even-parity
  — e.g. 1099392, 222299456 in Checkpoint chunks). Empirically, the
  intersection of Family-A keys and the NetToken index space is **0** across
  all files. So "wire the Phase-04 handle cache and match keys" is NOT a
  viable anchor — confirmed, not assumed.
- Family-B (`cb`, 13B) lead u16 is even and has only **3 distinct values**
  across files 2/3/4 (and 0% in A-space for files 5–9) → a small
  fixed even-indexed table, NOT an object-id anchor. Also ruled out.
- The spawn (first) bunch on a channel == an `E_0100` (N=1) record whose
  body equals the channel's first Family-A body (T3: 16/19 channels share
  key+body) → keys are PERSISTENT per-object ids; the body IS the object's
  serialized state. But the body does NOT embed a class-path FString
  (`u1_probe6`: only 1/90 real path hits, and that was an enum value), so
  the key → class mapping is not recoverable from the wire bytes alone.

**2026-07-14 — OA-06-3 "Checkpoint cross-ref" path RESOLVED NEGATIVE.** Phase 08
framing (`tools/checkpoint_decode.py`, byte-exact across all 10 files) shows
every Checkpoint path FString's prefix is a UObject **export index**
(range 0..~65k, ~30% odd) — a namespace DISJOINT from Family-A's compacted
u16 static handles (~99% odd, range ~1..few-thousand). Each checkpoint
re-exports the DYNAMIC live object path set (FULL snapshot; blob path-set sizes
grow AND shrink across checkpoints in 9/10 files), not a stable key→class
dictionary. => no Family-A-key→path lookup table exists on the wire; the
Checkpoint route CANNOT bridge U1 from replay bytes.

**Remaining U1 close condition:** only (b) — **TYR binary disassembly of the
carrier body serializer** — could now close U1. That is ENVIRONMENT-BLOCKED:
no TYR executable exists in this environment (`/dumper-7` holds only SDK
headers). U1 remains OPEN; Phase-06 downstream property sub-steps stay gated.

**Conclusion:** U1's *id* question is answered — Family-A keys are Iris
**static object handles**, compacted to u16 by TYR's carrier. The *semantic*
decode of the body (positions, health, …) is BLOCKED on an external
class anchor (the static-handle→class export table) that is **not present in
these replay wire bytes** (it lives in Checkpoint chunks keyed by NetToken
index, a different namespace). This matches the plan doc's explicit note that
U1 "does NOT gate t7" but "blocks the downstream property-replication
sub-steps." The downstream sub-steps (dirty-state, NetSerializers, FastArray)
therefore remain OPEN until either (a) a Checkpoint-derived handle→class table
can be cross-bridged to the u16 key space, or (b) TYR's carrier body format
is reversed from the binary.

**Validation artifact:** `tools/carrier_decode.py::familyA_key_invariant`
asserts (non-tautologically) that 100% of keys fit u16 and the aggregate
odd rate ≥95% (random ~50%); the hard assertion in `main()` prints
`VERDICT: U1 key-namespace RESOLVED (CANDIDATE)` when both hold. This
passed across all 10 files (commit 555303f).

**Close condition (for full U1, blob semantics):** obtain a handle→class
mapping bridgeable to the u16 key space (Checkpoint export table cross-ref,
or TYR binary disassembly of the carrier body serializer), then decode ≥1 body
to a semantically-plausible value within known level bounds.

---

## Phase 08 — Checkpoints

### OA-08-1 — Checkpoint trailing state block is Iris-encoded (env-blocked, parallel to U1)

**Status (2026-07-14):** The Checkpoint chunk is decoded into 4 sections (header
FStrings / export-list front-matter / object-list `[HDR][path FString][payload]` /
trailing state block). Sections 1–3 are byte-exact-validated across all 10 files
(94 checkpoints). The **trailing state block** (≈16k–55k B, FString-free, 0
embedded path FStrings across all 94 checkpoints) is the per-object replicated
property-state serialization — structurally a continuous Iris `NetSerializer`
blob (observed: zero-padded state buffers + subobject-handle lists
`03 ?? ?? 01` patterns, identical grammar to the Phase-06 Family-A/B/C carrier
body).

**What validates the partition instead of source:** the trailing block contains
**ZERO path FStrings across all 94 checkpoints** (`tools/checkpoint_full.py` gate
G3). A spurious object-list/trailing boundary would leak real object-path
FStrings into the trailing region; the observed 0 count is the non-tautological
proof the partition is real. Object-list tiling to the trailing start is further
confirmed by the clean payload=`-bytes-to-next-anchor` framing.

**Why the trailing block is NOT semantically decoded:** it is the SAME territory
as Phase-06 **U1 (OA-06-3)** — Iris `NetSerializer` property state that requires
the TYR class layout / handle→class export table to name. No such anchor is
present in the replay wire bytes (the Checkpoint object path set is keyed by
UObject export index, a namespace disjoint from Family-A's u16 static handles;
the OA-06-3 Checkpoint cross-ref path was RESOLVED NEGATIVE). TYR binary
disassembly is ENVIRONMENT-BLOCKED (`/dumper-7` holds only SDK headers).

**Risk:** the FULL-CHECKPOINT replay state (object-list + trailing state) cannot
be turned into named property values without the env-blocked anchor. The
structural decode (sections 1–3 + partition) IS complete and validated; only the
trailing block's *content* is OPEN. This mirrors exactly how Phase-06 t7 was
characterized (structural pass ≥99%, semantic decode split OPEN as U1).

**Validation artifact:** `tools/checkpoint_full.py` asserts (non-tautologically)
G1 header invariants (Group=='checkpoint', even Metadata), G2 export-list
self-termination, G3 zero-FString trailing partition. **RETRACTION (2026-07-14):**
the previously-claimed G4 "full chunk consumption to TotalSize" is **NOT** actually
asserted in `decode_full_checkpoint` — the partition is definitional (trailing =
remainder) and a ~25-byte prefix region after the 3 FStrings is silently dropped
(header FStrings end at offset 37; first export-list head FString `/TyrMap…`
begins at offset 68). So "byte-exact-validated 94/94" was overstated. The
structural decode is real and consistent (object counts 707–1548, FString-free
trailing in all 94), but consumption to `TotalSize` is NOT proven.

**2026-07-14 static cross-check (docs/phase08-static-crosscheck.md):** the
source-faithful UE5.6 `LoadCheckpoint` envelope (3 FStrings + `u64 PacketOffset`
+ `i32 LevelForCheckpoint`, then demo-frame body) is **empirically refuted** — a
source-faithful decoder desyncs on 94/94 checkpoints with garbage multi-MB reads
(the UE5.6 `u64` field does not parse; it reads as 128849018910000). This confirms
TYR uses a **CUSTOM checkpoint format**, not pristine UE5.6. The committed decoder
is a sound *structural* anchor but is not byte-exact to `TotalSize`.

**Close condition:** same as OA-06-3 — obtain a handle→class mapping bridgeable
to the wire namespaces, or reverse the Iris state-blob serializer from the TYR
binary, then decode ≥1 trailing-block state record to a semantically-plausible
value. (Also, to restore the "byte-exact" claim, model the ~25-byte prefix region
and assert consumption to `TotalSize`.)

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
