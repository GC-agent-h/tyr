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
