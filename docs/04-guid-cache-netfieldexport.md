# Phase 4 — Iris Object Reference Resolution and Replication Descriptors ("The Dictionary")

> **Rewritten for Iris.** This phase was originally scoped around legacy replication's `GuidCache` (`FNetworkGUID` → object) and `NetFieldExportGroup` (handle → property/function name) mechanisms. This project's replication backend is **confirmed to be Iris** (see `00-overview-and-setup.md`, Step 0.1), which replaces both of those mechanisms with a different pair of concepts: **`FNetRefHandle`-based object reference resolution** and **replication protocol descriptors** built from `FReplicationStateDescriptor`s. The goal of this phase is unchanged (build the lookup layer that turns opaque stream IDs into meaningful SDK-cross-referenced classes/properties/functions) but the mechanism is different throughout. No live debugging is available on this project — see the static-cross-check methodology in `00-overview-and-setup.md` Step 0.3 (revised) in place of every "live debugger cross-check" below.

## Goal

Build the lookup layer that turns opaque numeric IDs and tokens in the Iris replication stream into meaningful references to UClasses, UObjects, and specific reflected properties/functions from your Dumper-7 SDK. Without this layer, Phases 5–8 are just meaningless bits.

## Source of truth

- `Engine/Source/Runtime/IrisCore/Private/Iris/ReplicationSystem/NetRefHandleManager.cpp` — object handle allocation/resolution; the Iris equivalent of `GuidCache`. Look for how a `FNetRefHandle` gets bound to a class/archetype the first time an object is referenced (analogous to `SerializeNewActor` in legacy).
- `Engine/Source/Runtime/IrisCore/Private/Iris/Core/NetObjectReference.cpp` / associated headers — the reference resolution structures Iris uses for object/path references on the wire.
- `Engine/Source/Runtime/IrisCore/Private/Net/Core/NetToken/NetTokenStore.cpp` and `NetTokenDataStream.cpp` — **`FNetToken`** is Iris's mechanism for compactly exporting repeated strings/names (paths, `FName`s) exactly once and referencing them by token thereafter. This is the closest analog to legacy's `FName` export-table mechanism (Phase 3) and to part of the static-GUID path-name export mechanism — expect path names to flow through the token store rather than being re-serialized per-reference.
- `Engine/Source/Runtime/IrisCore/Private/Iris/ReplicationSystem/ReplicationStateDescriptorBuilder.cpp` and `ReplicationProtocolManager.cpp` — build the compiled per-class "protocol" (property/RPC layout, the Iris equivalent of `NetFieldExportGroup` + `FRepLayoutCmd` list) from a UClass's reflected properties. This is Iris's authoritative schema source — reimplementing its traversal is the Iris analog of Phase 6's `InitFromObjectClass` reimplementation, but the lookup table it produces is what this phase (4) needs to build.
- `Engine/Source/Runtime/IrisCore/Private/Iris/ReplicationSystem/ObjectReplicationBridge.cpp` — ties `FNetRefHandle`s to `UClass`/archetype at spawn time; the Iris analog of `SerializeNewActor`.

## Two distinct mechanisms — still don't conflate them, but the mechanisms themselves differ from legacy

### A. `FNetRefHandle` → Object/Class resolution

Every replicated object gets a `FNetRefHandle`. Unlike legacy's flat `FNetworkGUID`, Iris handles typically encode more structure directly (check `NetRefHandleManager.cpp`'s handle layout — e.g., an internal index plus a replication-system ID component) rather than relying purely on a side-table static/dynamic flag bit. Confirm the exact bit layout from source rather than assuming it mirrors legacy's convention.

- For objects resolved via **path** (static assets — classes, archetypes, level-placed actors), the path components are very likely to flow through the **`FNetToken` store** (see above) rather than being serialized inline as raw `FName`/string sequences per reference — confirm this by checking whether `NetObjectReference` serialization calls into the token store's read/write path.
- For **dynamically spawned** objects, `ObjectReplicationBridge.cpp`'s spawn-info handling is the Iris analog of the legacy dynamic-GUID-plus-archetype-reference mechanism — read it directly rather than assuming a 1:1 structural match with legacy.

Build a `NetRefHandleCache` structure: `Map<NetRefHandle, ResolvedInfo>`, populated incrementally in file order (handles are exported lazily throughout the stream and inside checkpoints, same principle as legacy — this part of the original phase's guidance still holds).

### B. Replication protocol descriptors — property/function handle tables

Independently, for each class that gets replicated, Iris compiles a **replication protocol** from the class's `FReplicationStateDescriptor`(s) — the property/RPC layout schema. This is conceptually the same *purpose* as legacy's `NetFieldExportGroup` (a compact per-class schema referenced by handle/index thereafter) but the construction mechanism is `ReplicationStateDescriptorBuilder`/`ReplicationProtocolManager`, not `FRepLayout::InitFromObjectClass`. Read `ReplicationStateDescriptorBuilder.cpp` closely — this is Iris's equivalent of the "read RepLayout.cpp closely, not just skim it" warning from the original Phase 6 doc, just pointed at a different file.

**Build a second cache**: `Map<ClassName, ProtocolSchema>` where `ProtocolSchema` captures whatever handle/index scheme the protocol descriptor uses to reference individual replicated states/properties on the wire — confirm from source whether this is still a small-integer handle scheme (as in legacy) or something else (e.g., a descriptor-relative member index) before assuming the legacy handle-loop shape carries over unchanged into Phase 6.

## Cross-referencing against your SDK

Unchanged in spirit from the original phase: for every resolved class name and field/state name from the two caches above, look it up in your Dumper-7-generated headers and record offset, declared type, array dimension, and whether the type has custom serialization — except under Iris, "custom serialization" primarily means a custom **`NetSerializer`** (Iris's structured serializer registration, distinct from legacy's `NetSerialize` member function convention) rather than a `bool NetSerialize(FArchive&, ...)`-shaped function. Check the SDK/executable for `NetSerializer` registration patterns (e.g., `UE_NET_IMPLEMENT_SERIALIZER`-style registration macros compiled into the binary, searchable as symbol/string fragments) for any game-custom struct, and build your quantized-vector/rotator lookup table against Iris's built-in serializers (`FVectorNetSerializer` family, quantized variants) rather than the legacy `FVector_NetQuantize*` `NetSerialize` implementations — the bit-level quantization schemes may coincidentally match legacy's but must be confirmed from the Iris serializer source, not assumed.

Build this as a normalized, queryable data structure exactly as the original phase describes (JSON/SQLite: ClassName → PropertyName → {offset, type, arrayDim, isCustomSerialize, customSerializeKind}) — this part of the guidance is backend-agnostic and unchanged.

## Implementation approach

1. As you scan chunks in file order (interleaving with Phases 5/8), whenever you encounter a `FNetRefHandle` export, `NetToken` export, or replication protocol/descriptor export, parse and insert into the respective cache immediately — single forward streaming pass, caches populated and consulted interleaved, same principle as the original phase's guidance.
2. For every class name you resolve, immediately attempt an SDK lookup and flag any miss — same reasoning as before (your SDK is dumped from the exact same running build).
3. Since Iris's protocol/descriptor construction is more structurally rigid than legacy's traversal-based `InitFromObjectClass`, treat a mismatch between your descriptor-builder reimplementation's predicted layout and the observed wire handle sequence as a stronger bug signal than the equivalent legacy check would have been — Iris protocols are typically deterministic compiled layouts, so disagreement is less likely to be explained away by an "order variance" excuse.

## Validation

1. **SDK coverage check**: unchanged in spirit — after processing all 10 sample files, every resolved class name should have a 100% match rate against your Dumper-7 SDK class list. Track this as an explicit metric.
2. **Field/state name plausibility per class**: cross-check every exported state/field name against an actual `UPROPERTY`/`UFUNCTION` on the class or an ancestor, same as before.
3. **NetToken/path consistency**: since path/name data is expected to flow through the `FNetToken` store rather than per-reference inline strings, verify token indices are stable and monotonically assigned within a file, and that the same token index always resolves to the same string within that file — a token resolving to different strings at different points is a strong bug signal specific to this mechanism.
4. **Static cross-check (no live debugging available)**: per Step 0.3 (revised), statically disassemble `NetRefHandleManager`'s resolution path and `ReplicationStateDescriptorBuilder`'s descriptor construction for a representative class or two, and confirm your reimplementation's output matches by hand-tracing rather than via live diff.
5. **Cross-file consistency for shared assets**: unchanged — static/path-resolved handles for level geometry, game classes, etc. should resolve to the same class/path names across all 10 sample files.

## Deliverables checklist

- [x] `NetRefHandleCache` implemented and populated via streaming pass, with static/dynamic distinction confirmed from Iris source (not assumed to mirror legacy).
      - Sub-step 1 (static path-name resolution): DONE — `consume_net_token_export_stream` + token store + static handle binding.
      - Sub-step 2 (dynamic spawn-info resolution): DONE — `read_net_object_reference` (ObjectReferenceCache.cpp:1524) + `observe_object_reference` (even-Id dynamic handle + inline path token WITHOUT TypeId on wire + recursive outer chain). Real-evidence validated on 7/10 replays (41 clean decodes of genuine Tyr object paths).
- [x] `FNetToken` store cache implemented for path/name resolution. `iris_net_token_store.py::NetTokenStoreCache` — typed stores (TypeId 0..7, per NetToken.h:32,37), (TypeId,Index)->payload resolution mirroring FNetTokenStoreState, import via UNetTokenDataStream::ReadData (NetTokenDataStream.cpp:194). Real-evidence validated across replays (genuine Tyr subsystem/Blueprint paths resolved with correct two-dimensional keys).
- [ ] Replication protocol/descriptor schema cache implemented, keyed by class, populated via streaming pass.
- [ ] SDK cross-reference database built (ClassName → PropertyName → {offset, type, arrayDim, customSerializeKind}), including Iris `NetSerializer` identification (not legacy `NetSerialize` detection).
- [ ] 100% (or explained near-100%) class-name match rate against the SDK across all 10 files.
- [ ] Field-name plausibility check passing for all resolved classes.
- [ ] At least one static cross-check (no live debugging) of `FNetRefHandle` resolution and protocol descriptor construction against source, documented per Step 0.3 (revised).

## Suggested commit breakdown

1. `feat(phase04): implement NetRefHandleCache with static path-name resolution` — get static/path-resolved handles working first, confirming the Iris bit-layout/path-resolution mechanism from source rather than assuming legacy's shape.
2. `feat(phase04): add dynamic NetRefHandle resolution (spawn-info path)` — layer dynamic resolution on top via `ObjectReplicationBridge.cpp`'s spawn-info handling.
3. `feat(phase04): implement FNetToken store cache` — the path/name token resolution mechanism, kept separate since it's conceptually distinct from handle resolution.
4. `feat(phase04): implement replication protocol/descriptor schema cache` — the Iris analog of the NetFieldExportGroup cache, built from `ReplicationStateDescriptorBuilder`/`ReplicationProtocolManager` reading.
5. `feat(phase04): build SDK cross-reference database (properties + functions, incl. NetSerializer detection)` — the normalized JSON/SQLite database; include function entries (Phase 7 depends on this) and Iris `NetSerializer` tagging (Phase 6 depends on this).
6. `test(phase04): SDK coverage metric report across 10 samples` — the automated "N/N classes matched" metric; wire into the Phase 9 regression suite as soon as it exists.
7. `docs(phase04): static cross-check of NetRefHandle resolution and protocol descriptors` — no live debugging is available on this project; commit disassembly-based notes in place of a live diff, per Step 0.3 (revised).

Note: item 5 is a natural point to split further if the SDK cross-reference logic grows large, same as originally noted — e.g., a sub-commit specifically for Iris `NetSerializer` registration detection/tagging, separate from basic offset/type/arrayDim extraction.

Proceed to `05-bunches-and-channels.md`.
