# Phase 7 — RPC (Remote Procedure Call) Replication — Iris

> **Rewritten for Iris.** Legacy's in-bunch RPC-vs-property dispatch marker (a branch inside `UActorChannel::ReceivedBunch`) does not apply as originally described — Iris routes RPCs through its own **`FNetBlob`** mechanism with dedicated RPC blob types, which may be structurally separate from property-state data streams rather than interleaved within the same per-actor payload the way legacy bunches were. No live debugging is available; live-debugger validation steps below are replaced by the static/redundant-path methodology in `00-overview-and-setup.md` Step 0.3 (revised).

## Goal

Decode replicated function calls (`UFunction` invocations — gameplay events like "PlaySound," "ApplyDamage," "SpawnEffect") carried via Iris's RPC/NetBlob mechanism.

## Source of truth

- `Engine/Source/Runtime/IrisCore/Private/Iris/ReplicationSystem/RPC/RPCCallHandler.cpp` (path/name may vary slightly in 5.6 — search for "RPC" under `IrisCore`) — Iris's RPC dispatch and call-handling logic, replacing `DataChannel.cpp`'s in-bunch branch.
- `Engine/Source/Runtime/IrisCore/Private/Net/Core/NetBlob/NetBlob.cpp` and `NetBlobHandler.cpp` — `FNetBlob` is Iris's general serialized-payload unit; RPCs are one blob type among others (object replication state may be represented as blobs too, depending on configuration — confirm from source whether RPCs and property updates for the same object share a data stream or use logically separate ones on this build).
- `Engine/Source/Runtime/CoreUObject/Private/UObject/ScriptCore.cpp` — general `UFunction` parameter property list iteration; still relevant since Iris ultimately still calls through reflected `UFunction` parameter lists for RPC arguments, just with Iris's own serialization driving the bits.
- `Engine/Source/Runtime/IrisCore/Private/Iris/Serialization/` — parameter serialization reuses the same `NetSerializer` machinery as Phase 6, just keyed by `UFunction` parameter properties instead of a class's replicated member properties.

## Structure to implement

1. **Identify the RPC blob dispatch mechanism**: read `RPCCallHandler.cpp`/`NetBlobHandler.cpp` to determine how an RPC call is framed on the wire under Iris — likely a distinct blob type/tag rather than a marker interleaved within a property-update handle loop (that legacy assumption no longer applies). Confirm whether RPC blobs for a given object appear within the same data stream as that object's property updates (Phase 5/6) or as a logically distinct stream — this determines how you sequence RPC decoding relative to property decoding in your pipeline.
2. **Resolve the function**: once you've identified an RPC blob, resolve it to an actual `UFunction` on the actor's class via your SDK cross-reference (Phase 4's protocol/descriptor database should include function entries, not just properties — revisit Phase 4 if it doesn't yet).
3. **Deserialize parameters**: iterate the `UFunction`'s parameter property list (from the SDK) and deserialize each parameter using the same Iris `NetSerializer`-based logic built in Phase 6 — the type-specific wire rules are shared between property replication and RPC parameters under Iris just as they were under legacy.
4. **RPC reliability/type flags**: `Reliable`/`Unreliable`/`NetMulticast`/server-vs-client-targeted distinctions still exist conceptually under Iris; confirm whether any of this metadata is itself encoded per-call in the replay stream by reading the blob header structure in `NetBlob.cpp`, rather than assuming it matches legacy's bunch-flag placement.

## Validation

1. **Function name plausibility**: every resolved RPC function name should exist as an actual `UFUNCTION` (with `Server`/`Client`/`NetMulticast` specifiers) on the actor's class or ancestor, per your SDK. A mismatch indicates a blob-resolution bug or a property/function disambiguation bug in step 1.
2. **Parameter count/type match**: unchanged in principle — deserialized parameter count/types should exactly match the `UFunction`'s declared parameter list from the SDK.
3. **Full-payload consumption**: same hard-assertion principle as every prior phase — bits consumed for an RPC blob must exactly equal its declared length.
4. **Semantic plausibility against known gameplay**: since no controlled live test session is possible on this project, substitute by finding naturally-occurring, easily-identifiable gameplay moments in the existing sample files (a clearly weapon-fire-shaped RPC sequence, a damage-application RPC with plausible parameter values) and treating internal consistency (function name matches expected semantics, parameter values are in plausible ranges, timing lines up with other observed events like a health property drop in the same file) as your plausibility signal in place of a known-ground-truth trigger.
5. **Static cross-check (no live debugging available)**: per Step 0.3 (revised), statically disassemble the RPC blob dispatch branch (`RPCCallHandler`/`NetBlobHandler`) and confirm your parser's dispatch logic matches by hand-tracing against real sample-file bytes — this is especially important here since Iris's RPC framing is one of the least self-evidently-documented parts of this phase and there's no live diff available to fall back on if the static reading is ambiguous. Document any remaining ambiguity as an explicit open assumption rather than guessing silently.

## Deliverables checklist

- [ ] Iris RPC/NetBlob dispatch mechanism identified and implemented (not assumed to match legacy's in-bunch marker).
- [ ] Function resolution via SDK cross-reference (including function entries in the Phase 4 database).
- [ ] Parameter deserialization reusing Phase 6's Iris `NetSerializer`-based logic.
- [ ] Full-payload bit consumption assertion passing when RPCs are present.
- [ ] At least one naturally-occurring scenario (known/plausible action → matching RPC name/params/timestamp) documented as a test fixture.
- [ ] At least one static cross-check (no live debugging available) of RPC blob dispatch, documented per Step 0.3 (revised).

## Suggested commit breakdown

1. `feat(phase07): implement Iris RPC/NetBlob dispatch detection` — the blob-type/tag mechanism distinguishing RPC calls from property-state blobs; this is the trickiest, least self-evident part of this phase under Iris, so isolate it and document your source evidence explicitly.
2. `feat(phase07): implement RPC function resolution via SDK` — resolving a blob to an actual `UFunction`; depends on Phase 4's database including function entries.
3. `feat(phase07): implement RPC parameter deserialization` — reusing Phase 6's Iris `NetSerializer`-based deserialization against the function's parameter property list.
4. `test(phase07): naturally-occurring scenario RPC test` — since no controlled live session is possible, find and commit a real, identifiable scenario from the sample files (e.g., a plausible weapon-fire or damage RPC sequence) alongside the assertion that your parser surfaces it correctly.
5. `docs(phase07): static cross-check of RPC blob dispatch` — no live debugging is available on this project; commit disassembly-based notes in place of a live-captured dispatch log diff, per Step 0.3 (revised).

Proceed to `08-checkpoints.md`.
