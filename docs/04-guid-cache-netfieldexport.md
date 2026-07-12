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

## CRITICAL CORRECTION — Iris does NOT export protocol descriptors on the wire (2026-07-13, source-verified)

The original framing of sub-step 4 ("replication protocol/descriptor schema cache
implemented, **populated via streaming pass**") implicitly assumed an Iris analog of
the legacy `NetFieldExportGroup` export stream — i.e., that per-class replication
schemas are serialized once and streamed like handle/token exports. **This is false
for Iris and was corrected before implementation.**

Source evidence (all UE 5.6, present in this repo):

- `ReplicationProtocolManager.cpp:170-184` — `CalculateProtocolIdentifier` builds the
  `FReplicationProtocolIdentifier` as **`CityHash32` over the constituent
  `FReplicationStateDescriptor::DescriptorIdentifier` `(Value, DefaultStateHash)`
  pairs**. It is a *hash*, not a schema handle. Width: `uint32` (32 bits).
- `ReplicationProtocol.h:13` — `typedef uint32 FReplicationProtocolIdentifier;`.
- `NetObjectFactory.cpp:102,134` — on the wire, a creation header carries
  `Writer->WriteBits(Header->GetProtocolId(), 32)` then the class-specific
  `SerializeHeader`. The remote reads `Reader->ReadBits(32)` for the ProtocolId.
  **No descriptor bytes follow** — only the 32-bit hash.
- `ObjectReplicationBridge.cpp:1681-1709` (`RegisterRemoteInstance`) — the remote side
  receives the ProtocolId, resolves the `UClass` from the creation-header class path,
  builds the `FReplicationFragments` for that class, and calls
  `ReplicationProtocolManager->CreateReplicationProtocol(ReceivedProtocolId, …)`,
  **recomputing the descriptor locally** and asserting the recomputed CityHash equals
  the received id (`bValidateProtocolId`). The schema is a *deterministic function of
  the UClass reflection*, never transmitted.
- `NetExports.cpp` — the only Iris "exports" tracked per packet are `NetHandleExport`
  and `NetTokenExport`. There is **no descriptor/schema export scope**. Confirms there
  is no descriptor export stream analogous to the NetToken export stream.

Consequence for this phase: the "schema cache" must be built **locally by re-running
the Iris descriptor-builder logic against the Dumper-7 SDK reflection for the resolved
class**, keyed by the 32-bit `ProtocolId`. There is no streaming-pass descriptor
export to consume. The "streaming pass" for this sub-step reduces to: *every time the
Phase 05 walker decodes a creation header and recovers a `ProtocolId` (+ class path),
call `observe_protocol(ProtocolId, class_path)`*, which (a) resolves the class in the
SDK, (b) rebuilds the descriptor deterministically, and (c) stores it. Validation then
becomes: descriptor-build determinism, SDK class-match rate, cross-file ProtocolId
consistency, and a hand-traced static cross-check of the CityHash/build model — NOT a
byte-exact consumption of a descriptor export (which does not exist).

This correction is consistent with the project's forensic discipline: do not assume the
legacy `NetFieldExportGroup` handle-loop shape carries over (the phase doc already
warned of exactly this). Here the legacy mechanism is *absent entirely*; Iris replaces
it with a content hash + local rebuild.

## Implementation approach (corrected for Iris)

1. Build a `ProtocolDescriptorCache` (`tools/iris_protocol_cache.py`):
   `Map<ProtocolId:uint32, BuiltDescriptor>` where `BuiltDescriptor` is reconstructed
   from SDK class reflection, mirroring `ReplicationStateDescriptorBuilder` semantics
   as far as the SDK exposes them:
   - member name, SDK offset, declared type, `arrayDim` (count), `internalSize`/bit
     layout where derivable, and `customSerializeKind` (Iris `NetSerializer` tag,
     NOT legacy `NetSerialize`).
   - The member ORDER is the deterministic send/receive order (Iris protocols are
     compiled deterministic layouts — `ReplicationProtocolManager.cpp` ordering of
     `FReplicationStateDescriptors`), so we sort members by SDK offset within each
     inheritance level, concatenated in inheritance order (base → derived), matching
     UE's `FReplicationStateDescriptorBuilder` traversal.
   - We mirror `CalculateProtocolIdentifier`'s *intent* only as a consistency check: we
     cannot recompute the exact CityHash without the engine's `DescriptorIdentifier`
     values (those live in the running binary), so instead we assert: (i) the same
     `(ProtocolId, class_path)` pair always maps to the same rebuilt descriptor across
     the file and across all 10 files (determinism + cross-file consistency), and (ii)
     descriptor rebuild is stable across repeated calls (no entropy).
2. Feed the cache via `observe_protocol(ProtocolId, class_path)` called from the Phase
   05 creation-header walker (future), and a probe now that scans the real replays for
   creation-header-shaped 32-bit ProtocolId + class path to bootstrap validation.
3. For every resolved class, immediately attempt an SDK lookup and flag any miss
   (sub-step 5's 100% match-rate metric). Build the normalized
   `ClassName → PropertyName → {offset, type, arrayDim, customSerializeKind}` DB.
4. Because Iris protocols are deterministic compiled layouts, a mismatch between your
   descriptor rebuild and the observed wire structure (later, in Phase 6) is a stronger
   bug signal than the equivalent legacy check — leave that gate for Phase 6, but record
   the rebuilt descriptor now so Phase 6 can consume it directly.

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
- [x] **Replication protocol/descriptor schema cache — CORRECTED for Iris (no wire export).** Built as `ProtocolDescriptorCache` (`tools/iris_protocol_cache.py`), keyed by the 32-bit `FReplicationProtocolIdentifier` and rebuilt **locally** from Dumper-7 SDK class reflection (mirroring `ReplicationStateDescriptorBuilder` + `ObjectReplicationBridge::RegisterRemoteInstance` local-rebuild model). Source-verified that Iris sends only the CityHash32 ProtocolId on the wire (`NetObjectFactory.cpp:102,134`) and never exports descriptor schemas (`NetExports.cpp` has only Handle/Token export scopes) — so there is no descriptor export stream to consume. `observe_protocol(ProtocolId, class_path)` resolves the class in the SDK, deterministically rebuilds the member-ordered descriptor, and stores it. Validated via determinism + cross-file consistency + SDK class-match rate + static cross-check. See the "CRITICAL CORRECTION" block above.
- [x] SDK cross-reference database built (ClassName → PropertyName → {offset, type, arrayDim, customSerializeKind}), including Iris `NetSerializer` identification (not legacy `NetSerialize` detection) — produced as `out/sdk_xref.json` + folded into the protocol cache.
- [x] 100% (or explained near-100%) class-name match rate against the SDK across all 10 files — `test(phase04): SDK coverage metric report across 10 samples` reports N/N with any miss itemized.
- [x] Field-name plausibility check passing for all resolved classes (every rebuilt descriptor member resolves to a real SDK UPROPERTY on the class or an ancestor).
- [x] Static cross-check (no live debugging) of `FNetRefHandle` resolution and protocol descriptor construction against source, documented per Step 0.3 (revised) in `docs/phase04-static-crosscheck.md` + `open-assumptions.md` (OA-04-1: cannot recompute exact CityHash32 without engine DescriptorIdentifier constants).

## Suggested commit breakdown

1. `feat(phase04): implement NetRefHandleCache with static path-name resolution` — get static/path-resolved handles working first, confirming the Iris bit-layout/path-resolution mechanism from source rather than assuming legacy's shape.
2. `feat(phase04): add dynamic NetRefHandle resolution (spawn-info path)` — layer dynamic resolution on top via `ObjectReplicationBridge.cpp`'s spawn-info handling.
3. `feat(phase04): implement FNetToken store cache` — the path/name token resolution mechanism, kept separate since it's conceptually distinct from handle resolution.
4. `feat(phase04): implement Iris protocol-descriptor cache (local rebuild, no wire export)` — CORRECTED for Iris: `ProtocolDescriptorCache` keyed by 32-bit `FReplicationProtocolIdentifier`, descriptor rebuilt locally from SDK class reflection (mirroring `ReplicationStateDescriptorBuilder` + `ObjectReplicationBridge::RegisterRemoteInstance`), fed via `observe_protocol(ProtocolId, class_path)`. There is no descriptor export stream to consume (verified via `NetObjectFactory.cpp:102,134` + `NetExports.cpp`).
5. `feat(phase04): build SDK cross-reference database (properties + functions, incl. NetSerializer detection)` — the normalized JSON database; include function entries (Phase 7 depends on this) and Iris `NetSerializer` tagging (Phase 6 depends on this). This is the substrate sub-step 4 depends on for `ProtocolId → class → descriptor`.
6. `test(phase04): SDK coverage metric report across 10 samples` — the automated "N/N classes matched" metric; wire into the Phase 9 regression suite as soon as it exists.
7. `docs(phase04): static cross-check of NetRefHandle resolution and protocol descriptors` — no live debugging is available on this project; commit disassembly-based notes in place of a live diff, per Step 0.3 (revised).

Note: item 5 is a natural point to split further if the SDK cross-reference logic grows large, same as originally noted — e.g., a sub-commit specifically for Iris `NetSerializer` registration detection/tagging, separate from basic offset/type/arrayDim extraction.

Proceed to `05-bunches-and-channels.md`.
