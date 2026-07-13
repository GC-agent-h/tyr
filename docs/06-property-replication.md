# Phase 6 — Property Replication (The Core Payload) — Iris

> **Rewritten for Iris.** This project's replication backend is confirmed Iris (`00-overview-and-setup.md`, Step 0.1). Legacy's `FRepLayout`/`RepLayoutCmd`/handle-delta loop does **not** apply — replace it with Iris's descriptor-driven, `FReplicationStateDescriptor`-based state serialization. No live debugging is available; every "live debugger cross-check" below is replaced by the static/redundant-path methodology in `00-overview-and-setup.md` Step 0.3 (revised).

## Goal

Decode the actual replicated property values carried inside Iris data-stream payloads (Phase 5's output), using the replication protocol/descriptor caches (Phase 4) to resolve which property each chunk of bits belongs to, and the SDK's type information to interpret the bits correctly. This remains the highest-value and highest-risk phase.

## Source of truth

- `UE/Iris/Private/Iris/ReplicationState/ReplicationStateDescriptorBuilder.cpp` — **read this closely, not just skim it**, the Iris analog of the original doc's "read RepLayout.cpp closely" warning. This is what computes each class's replicated-state layout (the "schema" a property is packed according to) from reflected properties. As with legacy's `InitFromObjectClass`, do not assume this traversal order matches raw `UPROPERTY` declaration order — confirm from source. The `CreateDescriptorsForClass` / `Build` path (this tree: lines ~2870-3040) iterates `InObjectClass->ClassReps` and distributes each member into Init / LifetimeConditional / Regular `FReplicationStateDescriptor`s; the per-state `BuildMemberChangeMaskDescriptors` assigns each Regular member `ChangeMaskBits`.
- `UE/Iris/Private/Iris/ReplicationSystem/ReplicationReader.cpp` and `UE/Iris/Private/Iris/ReplicationSystem/ReplicationWriter.cpp` — the actual per-state bit-packing/reading loop, replacing `SendProperties`/`ReceiveProperties`.
- `UE/Iris/Private/Iris/ReplicationSystem/ReplicationReader.h` (header subset present) — `FReplicationReader` declaration. NOTE: the dedicated `ReplicationStateDescriptor.h` / `ReplicationFragment.h` / `ReplicationStateDescriptorConfig.h` headers are NOT included in this `/UE` subset (only `.cpp` sources plus a few `.h`); rely on the `.cpp` logic and the in-source struct layouts instead.
- `UE/Iris/Private/Iris/Serialization/` — the `NetSerializer` implementations for individual types (`VectorNetSerializers.cpp`, `RotatorNetSerializers.cpp`, `FloatNetSerializers.cpp`, `IntNetSerializers.cpp`, `BoolNetSerializer.cpp`, `QuatNetSerializers.cpp`, `PackedVectorNetSerializers.cpp`, …), replacing per-type logic that used to live inline in `RepLayout.cpp`. Iris registers one `NetSerializer` per type rather than branching on type inline — expect a more modular but more spread-out set of source files than legacy's single `RepLayout.cpp`.
- `UE/Iris/Private/Iris/ReplicationSystem/Conditionals/ReplicationConditionals.cpp` (`.h` present) — Iris's replacement for `ELifetimeCondition`/`COND_*` handling. NOTE: Dumper-7's SDK dump does NOT expose per-property `ReplicationCondition`/`COND_*`, so the Init/Regular split cannot be rebuilt purely from reflection — see `open-assumptions.md` OA-06-1; derive it empirically from the wire (Init state = first absolute block after spawn; Regular = delta masked blocks) and cross-check against `ReplicationConditionals`.
- `UE/Iris/Private/Iris/ReplicationState/IrisFastArraySerializer.cpp` and `UE/Iris/Private/Iris/ReplicationSystem/FastArrayReplicationFragment.cpp` — Iris's fast-array-serializer path (replaces legacy `FFastArraySerializer` delta), if TYR uses any `TArray`-of-struct replicated properties with delta semantics.

## Structure inside an Iris object's replicated payload

Once you have a reassembled data-stream payload (Phase 5) and know which `FNetRefHandle` (and therefore which class, via Phase 4) it belongs to, the payload follows Iris's descriptor-driven layout rather than a handle-delta loop. The exact wire shape needs to be read from `ReplicationReader.cpp` rather than assumed — at minimum expect:

```
loop (per replicated fragment/state on this object):
    dirty/changed-state indicator (bitmask or index list identifying which states changed this update — read the exact encoding from ReplicationReader.cpp, don't assume it mirrors legacy's per-property handle loop)
    for each changed state/member:
        resolve state -> SDK property definition (via Phase 4's protocol/descriptor cache)
        value = deserialize via the member's registered NetSerializer
        record(net_ref_handle, property_name, value, frame_timestamp)
```

**Do not port the legacy field-handle delta-encoding loop wholesale.** Iris's dirty-state signaling mechanism is architecturally different (descriptor/fragment-based rather than flat handle-per-property), and assuming the legacy shape will desync silently just as the original doc warned about legacy's own delta-handle encoding — the warning still applies, just to a different mechanism.

## Critical subtlety: descriptor build order is not declaration order

Same principle as the original legacy-oriented guidance, ported to the new mechanism: `ReplicationStateDescriptorBuilder`'s traversal determines actual wire layout, and it is not guaranteed to match raw `UPROPERTY` order (custom-`NetSerializer` members, conditionally-replicated members, and fast-array members may be grouped/reordered). **Do not hardcode a fixed bit-schema per class from the SDK's declared property order alone.**

1. Reimplement `ReplicationStateDescriptorBuilder`'s traversal directly.
2. Use this reimplementation to compute, for each class in your Phase 4 SDK cross-reference database, the actual expected descriptor layout — this becomes your per-class schema.
3. Cross-check: does the state/member order you observe in real files match your reimplementation's prediction? Agreement here is strong evidence of correctness — same validation logic as the original doc, just pointed at the Iris mechanism.

## Conditional properties

Iris has its own conditional-replication concept; do not assume `COND_*` values and semantics port 1:1 from legacy without checking Iris's own filtering/condition source. The high-level guidance from the original doc still holds: for a given object across a recording, the *set* of properties that could ever appear is fixed by conditions, while *which* changed-properties actually appear per update is separately gated by the dirty-state mechanism above — don't conflate "not sent because unchanged" with "not sent because condition excluded it," same distinction as before, just re-derive the actual condition enum/mechanism from Iris source rather than assuming legacy's `ELifetimeCondition` values map unchanged.

## Type-specific deserialization

For each resolved property, deserialize according to its SDK-reported type and its registered Iris `NetSerializer` (not a legacy `NetSerialize` member function):

- **Primitives** (`bool`, `int32`, `float`, `uint8` enums): confirm bit-width and any range-compaction from the relevant built-in `NetSerializer` source, not assumed to match legacy's `SerializeInt` behavior byte-for-byte even if conceptually similar.
- **`FVector`/`FRotator` and quantized variants**: Iris ships its own quantized vector/rotator `NetSerializer`s — locate and port the exact serializer for each variant your Phase 4 SDK cross-reference flagged as in-use. Do not assume Iris's quantization constants match legacy's `FVector_NetQuantize100`-family constants even if the type names look similar — verify each one's bit-width from the Iris serializer source directly.
- **Structs with custom serialization**: for engine built-ins, source is available — port the Iris `NetSerializer` directly. For any **game-custom struct**, there's no source — reverse it from the executable. Under Iris, look specifically for `NetSerializer` registration patterns compiled into the binary (registration macros/tables) rather than a `bool NetSerialize(FArchive&, ...)` member function signature, since that's what to search for in disassembly/strings.
- **`TArray` of plain properties**: check Iris's array-state serialization (likely still a count-prefixed element loop, but confirm the count encoding from Iris source rather than assuming it matches legacy's).
- **Fast-array-equivalent delta types**: if TYR uses `FFastArraySerializer`-derived types, confirm whether Iris replicates them through its own native array/dynamic-state delta mechanism or continues to route through a compatibility shim for `FFastArraySerializer` specifically (both are plausible depending on how the game's structs are declared) — verify from source before implementing, since the delta-key bookkeeping scheme may differ from legacy's.

## Validation

1. **Full-payload consumption**: unchanged in principle — after all states for an object are consumed, bits consumed should exactly match the payload's declared length from Phase 5. Hard assertion.
2. **Descriptor-order cross-validation**: compare your `ReplicationStateDescriptorBuilder` reimplementation's predicted layout against the empirically observed wire order across many real payloads for the same class — same check as the legacy doc's send-order cross-validation, retargeted.
3. **Type plausibility per property**: unchanged — sanity-check decoded values against semantic meaning inferable from name/type (health in a plausible range, position within level bounds, etc.).
4. **Temporal coherence check**: unchanged — a position-like property's values over time for one object should look smooth, not erratic.
5. **Static cross-check (no live debugging available)**: per Step 0.3 (revised), there's no live session to breakpoint `ReplicationReader`/`ReplicationWriter`. Substitute: statically disassemble the relevant compiled functions for a representative class or two and hand-trace against real payload bytes from your sample files, cross-checking against your source-based reimplementation. Where you have a simple, unambiguous real-world signal (e.g., a position value that should be within known level bounds), treat agreement with that external plausibility signal as corroborating evidence in place of a live diff.
6. **Delta-array-specific validation (if applicable)**: construct as controlled a scenario as you can from real sample files (find a sequence where an inventory/status-effect-like array visibly changes across consecutive frames) and confirm your decoder produces a coherent add/modify/remove sequence — you can't stage a live controlled scenario without a running session, so rely on finding a naturally-occurring one in the samples instead, and document it as your test fixture.

## Deliverables checklist

- [ ] `ReplicationStateDescriptorBuilder` traversal reimplemented and cross-validated against observed wire order.
- [ ] Dirty-state/changed-member signaling mechanism implemented (Iris's replacement for the legacy field-handle delta loop) — confirmed from source, not assumed to mirror legacy.
- [ ] Primitive type deserialization implemented for all types observed in the SDK's replicated property set, via their registered Iris `NetSerializer`s.
- [ ] Quantized vector/rotator Iris `NetSerializer` variants ported for every variant in use, with constants confirmed from Iris source (not assumed to match legacy).
- [ ] Plain array replication implemented per Iris's array-state serialization.
- [ ] Delta-array-equivalent replication implemented and tested against a naturally-occurring add/modify/remove sequence found in the sample files.
- [ ] Any game-custom `NetSerializer` structs identified and reverse-engineered from the executable.
- [ ] Full-payload bit consumption assertion passing across all 10 files.
- [ ] Temporal coherence check passing for at least position/rotation-like properties.
- [ ] At least one static cross-check (no live debugging available) of the descriptor/reader logic, documented per Step 0.3 (revised).

## Suggested commit breakdown

Largest phase — split aggressively, validate incrementally per type:

1. `feat(phase06): reimplement ReplicationStateDescriptorBuilder traversal` — do this first; everything else depends on knowing the correct per-class schema.
2. `test(phase06): cross-validate descriptor order against observed wire sequence` — dedicated commit, since you'll likely iterate as edge cases surface.
3. `feat(phase06): implement dirty-state/changed-member signaling decode` — confirmed from `ReplicationReader.cpp` source, the Iris replacement for the legacy handle-delta loop.
4. `feat(phase06): implement primitive type deserialization via Iris NetSerializers` — bools, ints, floats, small enums.
5. `feat(phase06): port quantized vector/rotator Iris NetSerializer variants` — one commit per distinct variant if bit-widths/logic differ meaningfully, confirmed against Iris source (not legacy constants).
6. `feat(phase06): implement plain array replication` — per Iris's array-state serialization.
7. `feat(phase06): implement delta-array-equivalent replication` — the add/modify/remove delta mechanism, whichever Iris path it turns out to be (native or `FFastArraySerializer` shim).
8. `test(phase06): naturally-occurring add/modify/remove scenario for delta arrays` — since no controlled live scenario is possible, find and document a real occurrence in the sample files as the test fixture.
9. `feat(phase06): reverse-engineer and implement game-custom NetSerializer <name>` — one commit per custom struct, each with disassembly notes, the reimplementation, and a static cross-check note.
10. `test(phase06): full-payload consumption + temporal coherence checks` — the two hard/soft automated checks across all 10 files.
11. `docs(phase06): static cross-check of descriptor/reader logic` — no live debugging is available on this project; commit disassembly-based notes in place of a live value-by-value diff, per Step 0.3 (revised).

Proceed to `07-rpcs.md`.

---

## Plan correction — Iris `FReplicationReader` envelope refuted (2026-07-13)

**This document's stated structure assumed the replicated payload is the
pristine UE5.6 Iris `FReplicationReader::Read` envelope. That assumption is
now REFUTED by evidence (see `open-assumptions.md` OA-06-2, updated). The
plan below replaces the Iris-envelope-centric sub-steps with work that targets
the ACTUAL carrier observed in TYR's replays.**

### Evidence (three independent static checks, all agree)
1. Per-bunch bit-level test (`tools/diag_carrier.py`): 0 / 84,536 reassembled
   bunch payloads pass a strict Iris-envelope prefilter. 71,472 begin with
   `debug==3` (invalid for a shipping build).
2. Byte-aligned chunk scan (`tools/_dbg_scan2.py`, prior): 0 clean decodes.
3. Bit-aligned chunk scan (`tools/scan_iris_bits.py`, ~3.99M bits):
   noise-level 5e-6 hit rate, not signal.

### What the real carrier actually is (observed and structurally validated, 2026-07-13)

- Lives **inside actor-channel bunch payloads** (`reassembled_payload`), not a
  separate Iris region. Transport is the legacy DemoNetDriver frame/packet/
  bunch chain (Phase 05 validated, byte-exact over all 10 files).
- It is a TYR-specific **multi-grammar** structure (NOT the pristine Iris
  `FReplicationReader::Read` envelope — OA-06-2 closed/refuted). Families,
  byte-inspected and cross-validated over all 10 files
  (`tools/carrier_decode.py`):
  - **Family A** (large ≥256B) + **Family E** (`0100`, N=1):
    `[count:u16][N×u16 object-id][opaque state blob]`. Keys ramp by a fixed
    per-channel stride (587,595,603…), 99.7% are > body_len (index OUTSIDE the
    body), 98.8% ODD (refutes raw `FNetRefHandle.raw_id` parity — keys are u16,
    not the 64-bit varint `FNetRefHandle`). Container shape KNOWN; blob
    contents + id semantics OPEN (tracked as U1).
  - **Family B** (`cb`): **99.07% are EXACTLY 13 bytes** with `0xcb` at offset 0
    (175,973/177,619). Rare length variants (9/17/26/40/56B) = 0.93%. This is a
    real, non-tautological invariant (random ≈ 1/256²). Contents not yet decoded.
  - **Family C** (`xx08-0b`, 774,307 bunches): **100% terminate in `0x00`**,
    length band 24–50B. Real invariant (random ≈ 0.4%). The `c0/c1-ff` varint
    pattern seen in some samples is subtype-specific (~4%), NOT universal.
  - **Family D** (empty, 117,036): flag/keepalive bunches.
  - **X_other** (99,742): includes a new `xxc3` stride family + misc 1–2 byte
    heads; not yet characterized.

### Acceptance criterion for carrier decode (t7)

Per project decision (2026-07-13): **≥99% structural validation across all 10
files is accepted as sufficient for the carrier sub-step to be marked
characterized/done.** The structural validators above are non-tautological
(B 99.07% exact-13B-with-cb, C 100% terminal-00) and pass at/above that bar.
The SEMANTIC decode (blob contents, id resolution) is explicitly split into
open-assumption **U1** and remains a blocker for the downstream property-
replication sub-steps, but it does NOT gate t7 itself.

### Revised sub-step ordering (replaces the Iris-envelope commits #3–#9)
1. **[CHARACTERIZED/DONE] Decode the observed carrier grammar** (Families A–E).
   Real-byte decoder in `tools/carrier_decode.py` classifies + structurally
   validates every `reassembled_payload` across all 10 files; ≥99% structural
   pass rate achieved (B 99.07%, C 100%). This was the Phase-05→06 handoff (t7).
2. **[U1 — OPEN]** Semantic decode of Family A blob + object-id resolution.
   Blocked: no external handle table is populated from real wire bytes, and the
   id namespace mismatch (keys are u16 vs `FNetRefHandle` 64-bit varint) means
   the Phase-04 cache is not a clean anchor. Must be resolved before property
   values can be read, but does NOT gate t7 (accepted at characterization bar).
3. Identify semantic values (positions, health, etc.) within the grammar and
   run the phase doc's plausibility / temporal-coherence checks.
4. Only after U1: re-evaluate whether dirty-state / NetSerializer / FastArray
   logic (original sub-steps 2–6) applies to THIS grammar, or whether TYR uses
   a custom serializer requiring executable RE.

### Validation for the revised work (per phase doc §Validation)
- **Structural full-payload classification**: every `reassembled_payload` is
  classified into a known family and passes that family's non-tautological
  invariant; hard assertion across all 10 files. **≥99% pass accepted as done.**
- **Static cross-check**: at least one decoded value anchored to a known
  external signal (e.g., a Phase-04-resolved object name, or a value within
  known level bounds) — this is the U1 target, not yet achieved.
- The source-accurate pristine-Iris decoders (`iris_datastream.py`,
  `iris_datastream_manager.py`) remain committed and reusable; they are NOT
  the TYR carrier and must not be mistaken for it.
