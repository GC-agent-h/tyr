# Phase 0 — Overview, Scope, and Ground-Truth Setup

## Status of this phase for this project — read before anything else

Several Phase 0 items are **already resolved** for this project and should not be redone:

- **Replication backend is confirmed: Iris is in use** (not legacy `FRepLayout`-based replication). This is a load-bearing fact — it means Phases 4, 6, and 7 as originally scoped for legacy replication **do not apply as written** and have been rewritten for Iris (see the updated `04-guid-cache-netfieldexport.md`, `06-property-replication.md`, and `07-rpcs.md`). Phases 1, 2, 3, 5 (mostly), 8, and 9 remain largely engine-version-dependent rather than Iris-vs-legacy-dependent, but double-check each phase's "source of truth" section since some file paths now point at `Engine/Source/Runtime/IrisCore/` and related Iris plugin code instead of `RepLayout.cpp`/`PackageMapClient.cpp`.
- **The Dumper-7 SDK is already available** (`/dumper-7`) — do not spend time regenerating it.
- **UE 5.6 engine source is already available locally** (`/UE`) — do not ask for it again; if a specific file referenced below turns out to be missing from what's present, that's the one thing worth flagging.
- **No live debugging session is available for this project.** There is no way to attach a debugger to a running instance of the game, set breakpoints, or dump live memory. Every phase document in this project originally leaned on a "live-debugger cross-check" as its strongest/definitive validation step — **that step is not available here and must be replaced**. See "Step 0.3 (revised)" below for the replacement methodology, and note that every other phase document's "Validation" and "Suggested commit breakdown" sections have been updated accordingly (the live-debugger item is replaced with a **static cross-check**, described once here and referenced from each phase).

## Why this project is tractable

Unreal Engine's replay system (`DemoNetDriver`) is **not a proprietary black box** — it's open source, and you have:

- The exact engine version (5.6) source that produced these files.
- A Dumper-7 SDK reflecting the *exact* running build's classes, structs, and property layouts.
- Multiple sample `.replay` files from the same build/version (critical for differential analysis).
- The game executable itself, for disassembly (static analysis only — no live debugging available).

This converts "reverse engineering an unknown format" into "faithfully reimplementing a known, documented format," but without the ability to verify byte-for-byte against a live ground-truth trace — verification instead relies on internal redundancy (multiple independent decode paths that must agree), cross-file consistency, and static disassembly reading. The risk areas are narrow and well-defined:

1. Game-specific data blobs (custom header data, custom NetSerialize structs, Iris custom `NetSerializer`s).
2. Confirming which optional/version-gated code paths are actually active in this build.
3. Getting exact bit-packing order right (this is where most naive reimplementations silently produce garbage that "looks plausible" but is wrong) — this risk is **higher** than usual on this project precisely because live-debugger confirmation isn't available, so lean harder on the redundant-path and cross-file checks described throughout.

## Step 0.1 — Identify the exact engine subsystem in use — ALREADY DONE

**Resolved: this project uses Iris.** Do not re-run this decision — it was already confirmed. Skip straight to using the Iris-specific phase documents (updated `04-guid-cache-netfieldexport.md`, `06-property-replication.md`, `07-rpcs.md`; `08-checkpoints.md` and `05-bunches-and-channels.md` have Iris-relevant notes added where the wire format is affected).

For reference, the decision consequence stands as documented: the wire format for property replication (Phases 6–8) is structurally different from legacy `FRepLayout` (protocol-based serialization via `FReplicationReader`/`FReplicationWriter`/`FNetSerializationContext`, descriptor-driven rather than per-property-handle-driven, with `FNetRefHandle`/`FNetToken` replacing the legacy `FNetworkGUID`+`NetFieldExportGroup` pair for a large part of the resolution mechanism). The outer container format (Phase 1) and most of the bit-primitive layer (Phase 3) stay the same regardless of replication backend, since those are transport/container-level, not replication-protocol-level.

Since it wasn't captured before, do still produce a short written record of the evidence for "Iris confirmed" (whatever grep/string/config evidence you already have — `FReplicationSystem`, `UObjectReplicationBridge`, `FNetRefHandle`, `FNetSerializationContext`, `net.Iris.UseIrisReplication`/`net.IrisReplicationSystem` CVar strings, etc.) as the Phase 0 docs commit, since later sessions (and this document) reference it as settled fact and it should be traceable to something concrete rather than asserted.

## Step 0.3 (revised) — Build your validation methodology before writing any parsing code — NO LIVE DEBUGGING AVAILABLE

The original version of this step assumed a debuggable, controllable live session of the game. **That is not available for this project.** Every phase document's "Validation" section originally included a live-debugger cross-check as its strongest/definitive check — those checks cannot be run. Do not treat their absence as "skip validation for that item"; instead, substitute the following methodology everywhere a phase doc calls for a live-debugger diff:

1. **Redundant independent decode paths.** Wherever the format offers two ways to derive the same information, implement both and assert they agree. This is the single best substitute for ground truth on this project. The strongest existing example is Phase 8's stream-replay-vs-checkpoint cross-validation, but look for smaller instances of the same idea throughout (e.g., a class name resolved via two different export paths, a count that's both explicit and inferable by counting elements).
2. **Static disassembly reading (no live execution).** For anything requiring executable-level reverse engineering (game-specific header blobs, custom `NetSerialize`/Iris `NetSerializer` structs), use Ghidra/IDA statically: locate the function via the SDK's offsets/vtable indices, disassemble it, and read the logic by hand. You lose the ability to single-step and dump live register/memory state, so compensate by being more conservative — cross-check every inferred bit-width/constant against multiple call sites of the same function if possible, and treat any inference you can't pin down from the disassembly alone as a documented open assumption (see item 4).
3. **Cross-file structural consistency.** With 10 sample files from the same build, any field or structure that should be build-invariant (version numbers, class name resolution, quantization constants) must agree across all 10; any field expected to vary (timestamps, level names, actor counts) should vary plausibly. This doesn't prove correctness but is a strong, cheap, always-available signal.
4. **Documented open assumptions.** For anything that would normally be settled definitively by a live diff and now can't be, write it down explicitly as an assumption with your supporting (non-definitive) evidence, rather than silently treating it as confirmed. Keep a running list (`docs/open-assumptions.md` or similar) — this is the honest replacement for "confirmed via live debugger."
5. **Statistical/round-trip sanity checks.** Per-primitive round-trip tests, fuzzing, and distribution sanity checks (as already called for in Phase 3) become more important than usual — lean on them wherever a live diff would otherwise have been the plan.

Wherever a later phase document says "live debugger cross-check" or "live-debugger diff," read it as: **apply the methodology above**, and note in your commit/doc which of items 1–5 you used.

## Step 0.2 — Establish your source-of-truth file map

All of these are already available locally under `/UE` — no need to request them again. Keep them bookmarked for the entire project. All phase documents below reference them by relative path from `Engine/Source/Runtime/...` or `Engine/Plugins/...`.

| Concern | File |
|---|---|
| Outer file container (chunks, magic, compression/encryption flags) | `Engine/Plugins/Runtime/NetworkReplayStreaming/LocalFileNetworkReplayStreaming/Source/LocalFileNetworkReplayStreaming/Private/LocalFileNetworkReplayStreaming.cpp` |
| Demo header struct + read/write | `Engine/Source/Runtime/Engine/Private/ReplayHelper.cpp`, `Engine/Source/Runtime/Engine/Classes/Engine/DemoNetDriver.h` |
| Driver-level playback/record logic | `Engine/Source/Runtime/Engine/Private/DemoNetDriver.cpp` |
| Iris object reference / GUID-equivalent resolution (`FNetRefHandle`, `FNetToken`) | `Engine/Source/Runtime/IrisCore/Private/Iris/ReplicationSystem/`, `Engine/Source/Runtime/IrisCore/Private/Iris/Core/NetObjectReference*`, `Engine/Source/Runtime/IrisCore/Private/Net/Core/NetToken/` |
| Iris replication protocol / descriptor build (property send-order equivalent) | `Engine/Source/Runtime/IrisCore/Private/Iris/ReplicationSystem/ReplicationProtocolManager.cpp`, `.../ReplicationStateDescriptorBuilder.cpp` |
| Iris object replication / property serialization | `Engine/Source/Runtime/IrisCore/Private/Iris/ReplicationSystem/ObjectReplicationBridge.cpp`, `.../NetSerializers/` |
| Iris RPC/NetBlob handling | `Engine/Source/Runtime/IrisCore/Private/Iris/ReplicationSystem/RPC/`, `.../NetBlob/` |
| Bunch/channel parsing (still relevant for transport framing; verify against Iris data-stream usage in Phase 5) | `Engine/Source/Runtime/Engine/Private/DataChannel.cpp` |
| Legacy property bit-packing order — **not used on this project (Iris confirmed)**, kept only for reference/comparison | `Engine/Source/Runtime/Engine/Private/Net/RepLayout.cpp`, `Engine/Source/Runtime/Engine/Classes/Net/RepLayout.h` |
| Low-level bit primitives | `Engine/Source/Runtime/Core/Private/Serialization/BitArchive.cpp`, `Engine/Source/Runtime/Core/Public/Serialization/BitReader.h` |
| Packed integer VLQ scheme | `Engine/Source/Runtime/Core/Public/Serialization/Archive.h` (`SerializeIntPacked`) |
| Version history / feature flag gating | `Engine/Source/Runtime/Engine/Classes/Engine/DemoNetDriver.h` (`EReplayHeaderFlags`, `EReplayVersionHistory`) |

## Step 0.3 — Build your validation harness before writing any parsing code

This is the step people skip and regret. Do it first.

1. **Get a debuggable session of the actual game.** If the executable ships with any debug symbols (even partial), load it in x64dbg/IDA/Ghidra with the Dumper-7 SDK's offsets as an annotation source (Dumper-7 output includes field offsets — turn these into structure definitions in your disassembler so memory reads are labeled).
2. **Reproduce a replay recording under controlled conditions.** If you can run the game and force a replay recording (many UE games expose `demorec` / `demoplay` console commands, sometimes gated behind cheat protection — check the executable's command list via the SDK's `UConsole`/`UCheatManager`-derived classes, or the `exec`-flagged UFunctions in the SDK for anything resembling `StartRecording`), do a short, simple recording: one map, one player, minimal actors. This becomes your reference file where you *know* the ground truth of what happened.
3. **Set breakpoints at the exact compiled locations of**:
   - `UDemoNetDriver::WriteDemoHeader` / `ReadDemoHeader` in `ReplayHelper.cpp`
   - `UPackageMapClient::SerializeNewActor`
   - `FRepLayout::SendProperties` / `ReceiveProperties`
   - `UActorChannel::ReceivedBunch`
   
   Use the SDK to locate these by pattern: virtual functions can be found by matching vtable slot index between source declaration order and the disassembled vtable (Dumper-7 often records vtable index if virtual function info was recoverable — check `Offsets.hpp` and per-class function declarations for index annotations).
4. **Dump live values at each breakpoint** (property offsets being written, NetGUIDs being assigned, bit positions in the archive) and log them to a side file. This becomes your "expected output" to diff your parser's output against, field by field, for the exact same replay file.

### Why this matters for every subsequent phase

Every phase document below ends with a "Validation" section. Most of those validations boil down to: *decode phase N's structures from the file, then confirm the values against either (a) another independent decode path, (b) known invariants from source, or (c) live-captured ground truth from a debugging harness.* **(c) is not available on this project.** You are relying on (a) and (b) plus the Step 0.3 (revised) substitutes (static disassembly reading, cross-file consistency, documented assumptions, statistical/round-trip checks). This is inherently weaker than a live diff at catching certain classes of subtle bugs (e.g., correct-looking values that are coincidentally plausible but wrong — very common with bit-packed data), so lean harder than usual on redundant independent decode paths wherever the format allows constructing one, since that's the closest substitute for ground truth available here.

## Step 0.4 — Environment and tooling choices

- **Language**: Use whatever you're fastest in for iterative binary parsing (Python for the exploratory/validation harness, since you'll be re-running byte-offset experiments constantly; C++/Rust for the final parser if performance matters, since it also lets you reuse UE source snippets almost verbatim). Recommendation: prototype every phase in Python first (structure understanding is the hard part, not speed), then port the finalized logic to C++/Rust once each phase is validated.
- **Hex viewer with bit-level annotation**: standard hex editors only get you to the byte level; since much of this format is *bit-packed* (not byte-aligned), build a small helper early that can print "byte offset, bit offset, N bits consumed, interpreted value" for every read your prototype parser does. You'll use this constantly for debugging phases 3–8.
- **Diffing tool for reflected structures**: write a quick script that dumps Dumper-7's per-class property list (name, offset, type, array dim) into a normalized JSON/CSV so you can programmatically cross-reference exported property names from the replay against the SDK, rather than manually grepping headers each time.

## Deliverables checklist for Phase 0

- [x] Confirmed Iris replication is in use (evidence to be written up as commit 2 below, even though the conclusion is already known).
- [x] Reference source (`/UE`) and SDK (`/dumper-7`) already available — no action needed.
- [ ] ~~At least one "known good" reproduced replay file with a logged ground-truth trace from a live debugging session~~ — **not available on this project.** Replaced by: a written `open-assumptions.md` tracker and adoption of the Step 0.3 (revised) methodology across all phases.
- [ ] A bit-level trace helper ready to use.
- [ ] A normalized JSON/CSV dump of the SDK's reflected class/property data for fast cross-referencing.

## Suggested commit breakdown

This phase produces mostly scaffolding/docs rather than parser logic, but still split it into separate, independently-pushable commits rather than one giant "initial commit":

1. `chore(phase00): bootstrap repo structure and language choice` — repo skeleton, chosen prototyping language (e.g., Python) and eventual target language (e.g., Rust/C++), README stub, dependency setup.
2. `docs(phase00): confirm iris replication with evidence` — write up whatever grep/string/config evidence supports the already-known conclusion that Iris is in use, as a short markdown note in the repo, not just as chat/scratch notes.
3. `chore(phase00): add bit-level trace helper scaffold` — the "byte offset, bit offset, N bits consumed, value" debug printer described in Step 0.4.
4. `chore(phase00): add SDK reflection dump tool (JSON/CSV export)` — the script that normalizes Dumper-7's headers into a queryable JSON/CSV, used constantly from Phase 4 onward.
5. `docs(phase00): document no-live-debugging constraint and adopt static validation methodology` — a short note recording that no live/debuggable game session is available for this project, and that Step 0.3 (revised)'s methodology (redundant decode paths, static disassembly, cross-file consistency, documented open assumptions, statistical/round-trip checks) replaces every subsequent phase's live-debugger validation step. Start the `open-assumptions.md` tracker in this commit — you'll append to it throughout the project instead of closing items out via live diff.

Do not proceed to Phase 1 commits until items 3 and 4 above are pushed — both are dependencies used by every later phase's validation commits.

Proceed to `01-outer-container-format.md` once all boxes are checked.
