# TYR `.replay` Parser — Project Handoff

**Read this file first, in full, before touching any code or any other file in this folder.** This document is written so that an agent with zero prior context on this project can pick it up and continue exactly where the previous session left off.

## Project summary

**Goal**: build a standalone parser (outside of Unreal Engine) capable of reading and analyzing `.replay` files produced by the integrated Unreal Engine Replay System (`DemoNetDriver`), for a game called **TYR**.

**The game**:
- Built with **Unreal Engine 5.6**.
- Uses **Iris**, UE5's newer replication system — **already confirmed**, not an open question (see `00-overview-and-setup.md` Step 0.1). Phases 4, 6, and 7 have been rewritten accordingly; read the Iris-specific versions of those documents, not the legacy `FRepLayout`/`GuidCache`/`NetFieldExportGroup` terminology that may still appear in older notes or chat history.
- Does **not** use Oodle or zlib compression on replay data (confirmed by the project owner — don't spend time building decompression support unless later evidence contradicts this).

**Known project constraint**: **no live debugging session is available.** There is no way to attach a debugger to a running instance of the game, set breakpoints, or capture live ground-truth traces. Every phase document's validation section originally treated a live-debugger diff as its strongest/definitive check — those steps have been replaced project-wide with a static/redundant-decode-path methodology defined once in `00-overview-and-setup.md`, Step 0.3 (revised). Do not attempt to set up a live debugging harness for this project; it is not achievable with available resources.

**Available resources** (already present in your environment — do not ask the project owner for these again; only flag if a specific referenced file turns out to be genuinely missing):
- | `README.md` | This file — start here every session. |
- | `PROGRESS.md` | **Live status tracker.** Check this immediately after this README to see exactly what's done, what's in progress, and what's next. |
- In the folder /UE : Unreal Engine 5.6 source, already available locally.
- In the folder /sample : Around 10 sample `.replay` files, all generated from the same game build and version.
- In the folder /dumper-7 : A complete SDK generated with **Dumper-7** from the running game, already available, consisting of:
  - `SDK.hpp` (master include)
  - `Basic.hpp` (core UE types: `FString`, `FName`, `TArray`, etc.)
  - `Offsets.hpp`
  - Package headers such as `Engine_classes.hpp`, `Engine_structs.hpp`, `CoreUObject_classes.hpp`, `CoreUObject_structs.hpp`, and more
  - Reflected properties, offsets, functions, and (where recoverable) virtual function info
- In the folder /docs you have : The step by step guide, consisting of:
	- | `00-overview-and-setup.md` | Phase 0: scope, confirmed Iris replication backend, source file map, static-validation methodology (no live debugging available). |
	- | `01-outer-container-format.md` | Phase 1: magic number, top-level metadata, chunk table. |
	- | `02-demo-header.md` | Phase 2: demo header fields, feature flags, game-specific header blob. |
	- | `03-bit-level-primitives.md` | Phase 3: `FBitReader`, `SerializeIntPacked`, `FString`/`FName`/`FNetworkGUID` serialization. |
	- | `04-guid-cache-netfieldexport.md` | Phase 4: NetGUID-to-object resolution, NetFieldExportGroup handle tables, SDK cross-reference database. |
	- | `05-bunches-and-channels.md` | Phase 5: frame/packet/bunch framing, channel lifecycle, partial bunch reassembly. |
	- | `06-property-replication.md` | Phase 6: the core payload — RepLayout send-order, per-type deserialization, fast arrays, custom NetSerialize. |
	- | `07-rpcs.md` | Phase 7: replicated function call decoding. |
	- | `08-checkpoints.md` | Phase 8: full and delta checkpoint decoding, stream-replay cross-validation. |
	- | `09-validation-and-iteration.md` | Phase 9: build order, regression testing strategy, executable-RE guidance. |
- In the folder deliverable/ : 1 folder per step with the deliverables
- In the folder out/ : 1 folder per step wwith the result of script from the corresponding step.

## Why this project is tractable

Unreal's replay system is **open source**, and you have the exact engine version that produced these files, plus an SDK reflecting the exact running build's classes/structs/properties. This is fundamentally a **faithful reimplementation** task, not blind reverse engineering — most of the format is fully documented in the UE5.6 source you have access to. The only parts requiring genuine executable-level reverse engineering are narrow and identified explicitly in the phase docs (game-specific header data, any game-custom `NetSerialize` structs).
Each phase file (00–09) contains, in this order: **goal**, **source of truth** (exact UE5.6 source file paths to read), **structure/implementation approach**, **validation** methodology, a **deliverables checklist**, and a **suggested commit breakdown**.

## What to do at the start of every session (including this one)

1. Read this README fully.
2. Open `PROGRESS.md` and read the "Overall status" table plus the detailed checklists underneath it. This tells you exactly which phases/sub-steps are `⬜ Not started`, `🟨 In progress`, or `✅ Done`.
3. Check the actual git log (`git log --oneline`) and confirm it agrees with what `PROGRESS.md` claims — if they've drifted apart (e.g., a commit exists that isn't reflected in `PROGRESS.md`, or vice versa), reconcile `PROGRESS.md` to match reality before doing any new work, and commit that reconciliation on its own (`docs(progress): reconcile tracker with actual git history`).
4. Identify the next unchecked sub-step in `PROGRESS.md`, in phase order (do not skip ahead — phases are ordered so that each one's validation depends on the previous one being trustworthy; see `09-validation-and-iteration.md`'s "Recommended build order" section for the full rationale).
5. Open that phase's `.md` file and read its **Goal**, **Source of truth**, and **Implementation approach** sections before writing any code.
6. Implement the sub-step, per its file's "Suggested commit breakdown" section.
7. Validate it per that file's **Validation** section — do not mark anything done without running the specific check described there (hard byte/bit-exact assertions, static cross-checks where called for, etc. — no live debugging is available on this project, see `00-overview-and-setup.md` Step 0.3 revised). A "wip:" commit is allowed for safety but does not count as done.
8. Commit and push per the git workflow rules in `PROGRESS.md` (Conventional Commits format, one commit per validated sub-step, push immediately, don't batch).
9. Update `PROGRESS.md` (tick the checklist box and, if applicable, the commit box), and commit that update **separately** from the feature commit (`docs(progress): mark phaseNN stepX done`).
10. If an entire phase's checklist becomes fully complete, flip its row in the "Overall status" table to `✅ Done`, record the branch/tag, and tag the commit (`git tag phaseNN-complete && git push --tags`) per `PROGRESS.md`'s workflow rules.

## Critical ground rules (do not violate these)

- **Do not skip phases or reorder them.** Each phase's validation assumes the previous ones are solid; working out of order makes bugs nearly impossible to localize.
- **Do not mark a checklist item or commit as done without running its actual validation check.** "Looks plausible" is not "validated." The phase docs are explicit about what validated means for each item (often: byte/bit-exact consumption assertions, or a static cross-check against source/disassembly — no live debugging is available on this project, see `00-overview-and-setup.md` Step 0.3 revised).
- **Do not batch multiple unrelated sub-steps into one commit.** Follow each phase file's "Suggested commit breakdown" section — this granularity is what makes `git bisect` useful later if a downstream phase's cross-validation (e.g., Phase 8's stream-replay check) surfaces a bug that could be anywhere upstream.
- **Iris is already confirmed as the replication backend** (Phase 0). Do not re-litigate this or fall back to legacy-replication assumptions in Phases 4–8; use the Iris-specific phase documents.
- **No live-debugging validation harness is available for this project.** Wherever a phase's validation section calls for a live-debugger cross-check, apply the static/redundant-decode-path methodology from `00-overview-and-setup.md` Step 0.3 (revised) instead, and record any resulting uncertainty in an `open-assumptions.md` tracker rather than silently treating it as confirmed.

## If you get stuck

- Re-read the relevant phase file's "Source of truth" section — the exact UE5.6 source paths are listed there; read the actual function referenced, don't rely on general UE knowledge from training data, since exact struct layouts and gating conditions are version- and build-specific.
- If something requires executable-level reverse engineering (no source available), see `09-validation-and-iteration.md`'s "When you hit something you can't resolve from source alone" section for the recommended approach.
- If you discover the plan itself needs to change (e.g., a phase's assumed structure doesn't match what you're observing in the actual files), update the relevant phase `.md` file to reflect reality, note the discrepancy and evidence in a `docs(phaseNN): correct assumption about X based on observed evidence` commit, and continue — these documents are meant to be corrected as ground truth emerges, not treated as infallible.

## If you need any ressources

REQUEST THE USER