# Phase 8 — Checkpoints

> **Iris note.** The checkpoint chunk/save-load mechanism itself (`ReplayHelper.cpp`) is largely orthogonal to the replication backend — checkpoints are a `DemoNetDriver`-level concept regardless of Iris vs. legacy. However, the *contents* of a checkpoint (the GUID/object-reference re-export section and per-object property state) follow this project's confirmed Iris mechanisms from Phases 4 and 6 — read "GUID cache re-export" below as "`FNetRefHandle`/`FNetToken` re-export" and "per-actor property state" as "per-object Iris replicated-state re-export," per Phases 4 and 6. No live debugging is available on this project; the live-debugger validation item below is replaced by the static/redundant-path methodology in `00-overview-and-setup.md` Step 0.3 (revised) — note that this phase's stream-replay cross-validation (Validation item 4) is your single best substitute for a live diff on this entire project, since it's a redundant-decode-path check that needs no live ground truth at all.

## Goal

Decode `Checkpoint` chunks (identified in Phase 1), which contain periodic snapshots of the entire replay state (GUID cache + all actor property states at a point in time), used by the engine to support scrubbing/seeking without replaying from the very start. Correctly handling these is what lets your parser (or anything built on top of it) jump to an arbitrary point in the replay efficiently, and is also a rich independent source of full-state data for validation purposes.

## Source of truth

- `Engine/Source/Runtime/Engine/Private/ReplayHelper.cpp` — checkpoint save/load logic (search for functions with "Checkpoint" in the name, e.g. `SaveCheckpoint`/`LoadCheckpoint`-equivalent, the exact naming may differ slightly in 5.6 given the DemoNetDriver/ReplayHelper split).
- `Engine/Source/Runtime/Engine/Classes/Engine/DemoNetDriver.h` — `EReplayHeaderFlags` bit for delta checkpoints (`HasDeltaCheckpoints` or similarly named flag identified back in Phase 2 — this flag is the fork point for this entire phase).
- `Engine/Source/Runtime/Engine/Private/PackageMapClient.cpp` — checkpoint-time GUID cache serialization (checkpoints re-export the GUID cache state, since a scrub-to-checkpoint operation needs to reconstruct the full GUID mapping as of that point without replaying every prior frame).

## Two checkpoint modes — confirmed by the Phase 2 header flag

### Full checkpoints (flag not set, or not supported in this engine version's default config)

Each checkpoint chunk is self-contained: it re-exports the full GUID cache state and full property state for every currently-alive actor, structured very similarly to Phase 4 (export tables) + Phase 6 (property values), just without needing prior frame history — you can decode a full checkpoint in isolation.

### Delta checkpoints (flag set)

Each checkpoint (after the first) only encodes **changes since the previous checkpoint** — actors destroyed since last checkpoint, actors spawned since last checkpoint (full initial state for those), and properties that changed on already-existing actors since last checkpoint (only the changed properties, using the same handle-based mechanism as Phase 6, not full resends). To decode checkpoint N in isolation, you must first have fully decoded checkpoint N-1 (recursively, back to the first full checkpoint) and applied each delta in sequence — this makes delta checkpoints strictly more complex to implement but is a well-known, common pattern (essentially: keyframe + incremental diffs, familiar from video codec design).

**Confirm which mode applies to TYR's replays empirically**: check the Phase 2 flag first, then cross-validate by attempting to decode the second checkpoint chunk in a sample file both ways (as self-contained full state, and as a delta against checkpoint 1) and see which produces a byte-exact-consumed, semantically plausible result.

## Structure to implement

1. **Checkpoint chunk framing**: similar to Phase 5's frame/packet structure but checkpoint-specific — check for a checkpoint-specific header within the chunk (e.g., a checkpoint index/ID, the frame timestamp it corresponds to, and possibly (if delta) a reference to the previous checkpoint's ID).
2. **`FNetRefHandle`/`FNetToken` re-export section**: parse using the same logic as Phase 4, but expect a (for full checkpoints) complete re-listing of all currently-relevant handles/tokens, or (for delta checkpoints) only newly-introduced/removed ones since the last checkpoint.
3. **Per-object state section**: for each object alive as of this checkpoint, parse its full (or delta, depending on mode) property state using the same Iris `NetSerializer`-based deserialization logic built in Phase 6, keyed by the same replication protocol/descriptor caches from Phase 4 (checkpoints likely reuse these rather than re-deriving a separate schema — confirm this by checking whether checkpoint data references the same descriptor mapping populated from earlier in the stream, or re-exports its own copy; verify rather than assume).
4. **Destroyed actor list** (delta mode specifically): a list of NetGUIDs for actors that existed at the previous checkpoint but were destroyed before this one — needed to correctly reconstruct "who's alive" state at this checkpoint without carrying forward stale actors.

## Implementation approach

1. Implement full-checkpoint decoding first (it's simpler and, if delta checkpoints are used, the *very first* checkpoint in any replay is still typically a full checkpoint even in delta mode — this gives you a testable starting point regardless of which mode the rest of the file uses).
2. Once full-checkpoint decoding is solid (validated per below), implement the delta-application logic on top: maintain an in-memory "current full state" object (a `Map<ActorGUID, Map<PropertyName, Value>>`) that you initialize from the first full checkpoint and then mutate according to each subsequent delta checkpoint's changed-properties/destroyed-actors lists, in file order.
3. Cross-check: after applying a delta checkpoint, the resulting reconstructed full state should be self-consistent (every actor referenced by a live GUID from Phase 4's cache, every property matching its class's known property list) — treat any dangling/orphaned reference as a bug signal.

## Validation

1. **Full-payload consumption**: standard hard check — bits consumed for a checkpoint chunk (or its sub-sections, if internally chunked) should exactly match declared size(s) from Phase 1.
2. **First-checkpoint-is-full invariant**: verify empirically across all 10 files that the first checkpoint chunk decodes correctly under "full checkpoint" assumptions regardless of the delta-checkpoint flag's setting — if this invariant doesn't hold for your files, revisit the Phase 2 flag interpretation.
3. **Delta-mode consistency check**: for files using delta checkpoints, reconstruct full state after each checkpoint in sequence and confirm no actor ever "reappears" after being marked destroyed without an intervening spawn event, and no property update ever references an actor not currently considered alive — either would indicate a delta-application bug.
4. **Cross-validation against Phase 5/6/7 decoded stream**: this is the single most powerful validation available for this entire project. A checkpoint's reconstructed full state at timestamp T should **exactly match** the state you'd derive by replaying all property updates (Phase 6) and relevant spawn/destroy events from the start of the file up through timestamp T using the frame-by-frame stream alone (independent of ever reading a checkpoint chunk). Implement this as an explicit automated cross-check: run your parser in "stream-replay" mode (Phases 5–7 only, ignoring checkpoints) up to each checkpoint's timestamp, then compare that derived state against the checkpoint chunk's directly-decoded state, actor by actor, property by property. **Any discrepancy here pinpoints a bug in one of the two independent code paths** (since they should be redundant representations of the same underlying data) — this is an extremely strong internal consistency check that doesn't even require external ground truth, and you should run it across all 10 files and all checkpoints within each file as a standard regression test once both paths are implemented.
5. **Static cross-check (no live debugging available)**: per Step 0.3 (revised), there's no running session to trigger a manual checkpoint save or breakpoint against. Substitute: statically disassemble the checkpoint save/load path (`ReplayHelper.cpp`'s checkpoint functions) and confirm your framing/field reads match by hand-tracing against real checkpoint chunk bytes from the sample files. This item is lower-priority than item 4 above (stream-replay cross-validation) since item 4 doesn't depend on live ground truth at all and is the stronger check available on this project.

## Deliverables checklist

- [ ] Checkpoint chunk framing implemented.
- [ ] Full-checkpoint decoding implemented and validated in isolation.
- [ ] Delta-checkpoint mode confirmed (or ruled out) via the Phase 2 flag and empirical cross-check.
- [ ] Delta-application logic implemented (if applicable), including destroyed-actor handling.
- [ ] Cross-validation harness built: stream-replay-derived state vs. checkpoint-decoded state, matching exactly across all checkpoints in all 10 files.
- [ ] At least one static cross-check (no live debugging available) of a checkpoint save/load path, documented per Step 0.3 (revised).

## Suggested commit breakdown

1. `feat(phase08): implement checkpoint chunk framing` — the checkpoint-specific header (index/ID, timestamp, previous-checkpoint reference if applicable).
2. `feat(phase08): implement full-checkpoint decoding` — GUID re-export + per-actor full property state, reusing Phase 4/6 logic; get this working and validated in isolation before touching delta mode.
3. `test(phase08): validate full-checkpoint decoding in isolation` — a dedicated commit for validating the very first checkpoint in each of the 10 files decodes correctly under the full-checkpoint assumption.
4. `feat(phase08): confirm delta-checkpoint mode via header flag + empirical check` — the flag interpretation plus the "try both hypotheses on checkpoint 2" experiment described in this phase's doc; commit your findings and decision even before delta-decoding logic exists.
5. `feat(phase08): implement delta-application logic incl. destroyed-actor handling` — only if delta mode is confirmed active; the in-memory full-state reconstruction mechanism.
6. `test(phase08): stream-replay vs checkpoint-decoded cross-validation harness` — arguably the single most valuable commit in the entire project; keep it isolated and make sure it runs across all checkpoints in all 10 files as an automated check, not a one-off manual comparison.
7. `docs(phase08): static cross-check of a checkpoint save/load path` — no live debugging is available on this project; supporting validation via disassembly notes in place of a live diff, per Step 0.3 (revised).

Once commit 6 passes cleanly, strongly consider wiring it directly into the Phase 9 regression suite as a permanent, always-run check — it's cheap to run and catches regressions across nearly the entire pipeline at once.

Proceed to `09-validation-and-iteration.md`.
