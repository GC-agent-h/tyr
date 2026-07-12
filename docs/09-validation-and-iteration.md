# Phase 9 — Build Order, Iteration Strategy, and Cross-Phase Validation

> **Project-status note.** This project uses Iris (confirmed in Phase 0), and no live debugging session is available. Phases 4, 6, and 7 have been rewritten for Iris's mechanisms (`FNetRefHandle`/`FNetToken`, replication protocol descriptors, `NetSerializer`s, `FNetBlob`-based RPCs) — see those documents directly rather than the legacy terminology used in older notes. Every phase's "live debugger cross-check" validation step has been replaced project-wide by the static/redundant-decode-path methodology defined once in `00-overview-and-setup.md` Step 0.3 (revised); this phase's build-order and regression-suite guidance below is otherwise unaffected by either change, since it operates one level up from the phase-specific mechanics.

## Goal

Tie the previous eight phases together into a concrete build order, and establish project-wide validation practices that catch regressions as you add features, rather than relying solely on per-phase checks done once and forgotten.

## Recommended build order (do not parallelize early phases)

1. Phase 0 (setup + debugging harness) — do not skip, even though it produces no parser code directly.
2. Phase 1 (outer container) — validate fully across all 10 files before touching Phase 2.
3. Phase 2 (demo header) — validate fully across all 10 files.
4. Phase 3 (bit primitives) — validate via unit tests and round-trips before using them "for real."
5. Phase 3.5 — **go back and re-validate Phases 1 and 2 using your Phase 3 primitives** if you took any shortcuts (e.g., ad hoc string reading) earlier. This re-validation pass is cheap and catches primitive bugs early rather than letting them masquerade as Phase 4+ bugs later.
6. Phase 4 (GUID cache + field export groups) — validate SDK coverage metric before proceeding.
7. Phase 5 (bunches/channels) — validate bit-exact packet consumption before proceeding.
8. Phase 6 (property replication) — the largest phase; validate incrementally per-type (get primitives working, then vectors, then structs, then fast arrays) rather than attempting all property types at once.
9. Phase 7 (RPCs) — reuses Phase 6 machinery heavily, should be comparatively quick once Phase 6 is solid.
10. Phase 8 (checkpoints) — implement full-checkpoint mode first, then delta mode; use the stream-replay cross-validation described in Phase 8's document as your primary regression test from this point onward.

## Why this order matters

Each phase's validation depends on the previous phase being trustworthy. If you jump ahead (e.g., start on Phase 6 before Phase 5's bit-exact consumption check passes), any bug you find could be in either phase, and you'll waste significant time debugging the wrong layer. Resist the temptation to "just get to the interesting property data" before the boring framing layers are solid — the framing layers are exactly where subtle, hard-to-detect bugs hide, because they don't crash, they just silently misalign everything downstream in a way that can still produce plausible-looking (but wrong) output.

## Project-wide regression testing strategy

Once you have Phases 1–8 all implemented at a basic level, build a standing regression suite:

1. **Full round-trip check across all 10 files**: run the complete parser pipeline (Phase 1 → 8) on all 10 sample files after every significant code change, and assert all hard invariants simultaneously:
   - Every chunk boundary lands exactly on declared sizes (Phase 1).
   - Every header is fully consumed (Phase 2).
   - Every packet/bunch/payload is fully consumed (Phases 5–7).
   - Every checkpoint's stream-replay-derived state matches its directly-decoded state (Phase 8).
   - 100% (or explained) SDK class/property/function name match rate (Phase 4).
   
   Treat any single failure across any of these 10 files as a blocking regression — do not let "it works on file 3" stand in for "it works on all files," since different files likely exercise different actor types, RPC calls, and edge cases (different players, different in-game events) even from the same build.

2. **Golden-output snapshots**: once you're confident in a given phase's correctness (backed by the static/redundant-decode-path methodology from `00-overview-and-setup.md` Step 0.3 revised — no live debugging is available on this project), serialize its decoded output (e.g., the full list of decoded property updates with timestamps) to a snapshot file per sample replay. On every subsequent code change, re-run and diff against the snapshot — any unexpected diff needs explicit review (it might be an intentional improvement, e.g., you just added handling for a previously-unrecognized custom struct, or it might be a regression).

3. **Fuzz/stress the bit reader boundary handling**: deliberately test your bit-reader primitives against truncated/corrupted inputs (not because your real files will be corrupted, but because this exposes off-by-one and boundary-condition bugs in your bit consumption logic that might otherwise only manifest rarely in real data) — assert your reader fails loudly and specifically (e.g., "ran out of bits mid-read") rather than silently returning garbage, since loud failures are far easier to debug than silent misalignment.

4. **Cross-file structural diffing as an ongoing practice**, not just a Phase-1-only check: as you add more decoding capability, periodically re-run your cross-file consistency checks (e.g., "do all 10 files resolve the same set of static GUIDs to the same class names") — this is a cheap, high-signal check to run repeatedly throughout the project, not just once.

## When you hit something you can't resolve from source alone

Given the phases above, the two places you're most likely to need executable-level reverse engineering (rather than source reimplementation) are:

- **Game-specific header data** (Phase 2) — if TYR overrides the game-specific demo header hook.
- **Game-custom `NetSerializer`-registered structs** (Phase 6) — any struct not part of base engine source that implements custom Iris network serialization.

For both, the approach is the same (note: no live debugging is available on this project, so step 4 below is static-only, per `00-overview-and-setup.md` Step 0.3 revised):
1. Use the SDK to identify the exact function/struct in question and its surrounding context (what class owns it, what other properties/functions are nearby, what the struct's declared member fields are — even without serializer source, the plain reflected field layout often gives strong hints about what the custom serialization is likely packing, e.g., if a struct has three float members, a custom serializer for it is very likely just packing those three floats, possibly quantized).
2. Locate the compiled function in the executable (via the SDK's virtual/function table info where available, or via string/pattern matching near related code — for Iris, also search for `NetSerializer` registration-table patterns).
3. Disassemble and read the logic directly — at this scale (a single function, not a whole system) this is very tractable even without source, especially with the SDK telling you the exact field layout the function is operating on.
4. Validate statically: hand-trace the disassembled logic against real bytes pulled from your sample files for a case where you can predict or plausibility-check the expected output (e.g., a position-like struct should decode to values within known level bounds). Since there's no live session to generate a controlled test case with known inputs, document any residual uncertainty explicitly as an open assumption rather than treating the static read as fully confirmed.

## Final deliverable shape

By the end of this plan, you should have:
- A parser library capable of ingesting a `.replay` file and producing a structured, timestamped event stream: actor spawns/destroys, property changes, RPC calls — each attributable to a specific actor/class from your SDK.
- A checkpoint-based random-access capability (decode game state as of an arbitrary timestamp without replaying from the start), if you completed Phase 8's delta/full checkpoint handling.
- A regression test suite covering all 10 sample files with hard structural invariants plus golden-output snapshots.
- A documented list of any game-custom serialization logic you had to reverse from the executable, with your reimplementation and its validation evidence, for future maintainability if TYR's build changes and you need to re-verify assumptions still hold.

## Suggested commit breakdown

Phase 9's own deliverables (as opposed to the cross-project build-order guidance above, which isn't itself a commit) split as:

1. `test(phase09): full pipeline regression suite across 10 samples` — the consolidated test that runs Phases 1–8 end-to-end against all 10 files and asserts every hard invariant simultaneously (chunk boundaries, header consumption, packet/bunch/payload consumption, checkpoint cross-validation, SDK match rate). Wire this into CI if you set one up, or at minimum into a single runnable script — this becomes the check you run after every subsequent change to any phase.
2. `chore(phase09): golden-output snapshot tooling` — the snapshot serialization + diff mechanism; commit an initial set of snapshots for all 10 files alongside the tooling.
3. `test(phase09): bit-reader fuzz/boundary condition tests` — deliberately truncated/corrupted input tests for the Phase 3 bit reader, asserting loud, specific failures rather than silent garbage.
4. `docs(phase09): document reversed game-custom serialization logic and evidence` — a consolidated reference doc listing every game-custom struct/blob you had to reverse from the executable (cross-referencing the individual per-struct commits from Phase 6/2), with a summary of the validation evidence for each — this is the document you'll come back to first if a future TYR patch breaks something, so make it thorough.

From this point forward, every change to any earlier phase's code should be followed by re-running commit 1's regression suite before pushing — treat it as a standing gate, not a one-time deliverable.

## A note on schema drift across game updates

Since this entire plan is keyed to one specific build's SDK dump, be aware that any future TYR patch that changes replicated classes/properties (adding fields, changing types, reordering `UPROPERTY` declarations in ways that affect `InitFromObjectClass`'s computed order) will require re-running Dumper-7 against the new build and re-validating your Phase 4/6 SDK cross-reference database — the framing-layer phases (1, 2, 3, 5, 8's structural logic) should remain stable across patches since they're pure engine-version-dependent, not game-content-dependent, but Phases 4, 6, and 7's per-class/per-property specifics are inherently tied to the current game build's reflection data and will need periodic re-validation as the game updates.
