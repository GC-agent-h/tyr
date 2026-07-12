# Progress Tracker — TYR `.replay` Parser

This file is the single source of truth for project status. Update it **every time a checklist item (or a whole phase) passes its validation**, and commit that update together with the corresponding code in the same commit (see workflow below).

## Project-status note (read before updating anything below)

- **Iris confirmed as replication backend.** Phases 04, 06, 07 checklists below have been updated to Iris terminology (`FNetRefHandle`/`FNetToken`, replication protocol/descriptors, `NetSerializer`s, `FNetBlob` RPCs) — see the rewritten `04-guid-cache-netfieldexport.md`, `06-property-replication.md`, `07-rpcs.md`.
- **No live debugging session is available.** Every "live-debugger diff/cross-check" checklist item and commit across all phases has been replaced below with a static cross-check item, per `00-overview-and-setup.md` Step 0.3 (revised). Do not add live-debugger items back in.
- **SDK (`/dumper-7`) and engine source (`/UE`) are already available** — Phase 00's checklist below reflects this as already satisfied.

## Git workflow rules

1. **One commit per completed, validated sub-step.** Do not batch multiple unrelated sub-steps into one commit — each phase document now has a "Suggested Commit Breakdown" section listing the exact commit boundaries for that phase. Follow it.
2. **Never commit a sub-step that hasn't passed its validation check yet.** "Validated" means: the specific check described in that phase's "Validation" section passes (hard assertions pass, static cross-check done where called for — no live debugging is available on this project, see the project-status note above — etc.), not just "code compiles" or "looks plausible." If you must commit work-in-progress code for safety, prefix the commit message with `wip:` and do **not** tick the checklist box below — `wip:` commits are not "done."
3. **Commit message convention** (Conventional Commits style):
   ```
   <type>(phaseNN): <short imperative description>

   <optional longer body: what was implemented, what validation was run and its result>

   Validates: <checklist item(s) from the phase doc>
   ```
   Where `<type>` is one of `feat`, `fix`, `test`, `refactor`, `docs`, `chore`. Example:
   ```
   feat(phase03): implement SerializeIntPacked with round-trip tests

   Ported the packed-integer VLQ scheme from Archive.cpp. Added unit
   tests against hand-constructed byte sequences for 0, 1, 127, 128,
   16384. Round-trip encode/decode verified for 10k random values.

   Validates: SerializeIntPacked unit tests (03-bit-level-primitives.md)
   ```
4. **Push after every commit**, not in batches — this keeps the remote history granular and means nothing is ever sitting locally-only for long. Suggested sequence per sub-step:
   ```
   git add <files>
   git commit -m "..."
   git push
   ```
   Then immediately update this file's checklist/table below and commit+push that update too (a lightweight `docs(progress): mark phaseNN stepX done` commit is fine and expected — don't fold the progress-file update into the feature commit, keep them separate so the progress file's history is itself a clean audit trail of when things were actually validated).
5. **Branching**: work phase-by-phase on `phase00-setup`, `phase01-container`, etc. branches if you want isolation, merging into `main` once a full phase's checklist is 100% complete and its "Deliverables checklist" box is ticked in this file. If you prefer trunk-based development (commit straight to `main`), that's fine too as long as rule #1 (one commit per validated sub-step) is respected — pick whichever you're already comfortable with, but be consistent.
6. **Tag phase completion**: once an entire phase's deliverables checklist is complete and merged, tag it: `git tag phase03-complete && git push --tags`. This gives you cheap checkpoints to `git bisect` against if a later phase's cross-validation (e.g., Phase 8's stream-replay check) turns up a bug that could be anywhere in the earlier pipeline.

## Overall status

| Phase | Status | Branch/Tag | Last updated |
|---|---|---|---|
| 00 — Overview & Setup | ✅ Done (validated + merged + tagged) | `master` @ `phase00-complete` | 2026-07-12 |
| 01 — Outer Container Format | ⬜ Not started | | |
| 02 — Demo Header | ⬜ Not started | | |
| 03 — Bit-Level Primitives | ⬜ Not started | | |
| 03.5 — Re-validate Phase 1/2 with Phase 3 primitives | ⬜ Not started | | |
| 04 — Iris NetRefHandle / Replication Protocol Descriptors | ⬜ Not started | | |
| 05 — Bunches & Channels | ⬜ Not started | | |
| 06 — Property Replication | ⬜ Not started | | |
| 07 — RPCs | ⬜ Not started | | |
| 08 — Checkpoints | ⬜ Not started | | |
| 09 — Regression Suite / Iteration | ⬜ Not started | | |

Status values: `⬜ Not started` / `🟨 In progress` / `✅ Done (validated + merged + tagged)`.

---

## Phase 00 — Overview & Setup

> **Reconciliation note (2026-07-12):** This repo began as a fresh `git init`
> with **no prior commits** — the commit list implied by this section's
> checkboxes never existed. The checklist below has been brought into line
> with what was actually committed on `master`. Two documentation deliverables
> (Iris evidence, no-live-debugging note + open-assumptions tracker) were
> authored as part of the bootstrap baseline commit rather than as separate
> commits; they exist on disk and are real, but are not separate commit
> objects. The two tooling deliverables (BitReader, SDK dump) are separate,
> validated commits. No content is missing or faked.

- [x] Confirmed Iris replication, with evidence written up (`docs/iris-evidence.md`)
- [x] Reference source files (`/UE`) and SDK (`/dumper-7`) available locally (committed as baseline)
- [x] ~~Reproduced replay + live-debugger ground-truth trace captured~~ — not available; replaced by `open-assumptions.md` + Step 0.3 (revised) methodology
- [x] Bit-level trace helper built (`tools/bitreader.py` + `tools/selftest_bitreader.py`, S1–S6 passing)
- [x] SDK class/property JSON dump built (`tools/dump_sdk.py` → `out/sdk_index.json`)

**Commits:**
- [x] `chore(phase00): bootstrap repo structure and language choice` (incl. Iris evidence + no-live-debugging note as docs; reference baseline)
- [x] `chore(phase00): add bit-level trace helper scaffold` (deliverable #3)
- [x] `chore(phase00): add SDK reflection dump tool (JSON export)` (deliverable #4)

---

## Phase 01 — Outer Container Format

- [x] Magic + version reader, asserted across all 10 files
- [x] Top-level metadata block parsed (incl. bCompressed/bEncrypted confirmed false)
- [x] Chunk table walker lands exactly on EOF for all 10 files
- [x] Chunk-table report printed and eyeballed per file
- [ ] Field-by-field static cross-check (no live debugging available)

**Commits:**
- [ ] `feat(phase01): parse magic number and file version`
- [ ] `feat(phase01): parse top-level metadata block`
- [ ] `feat(phase01): implement chunk table skeleton walker with EOF assertion`
- [ ] `test(phase01): cross-file consistency report across 10 samples`
- [ ] `docs(phase01): static cross-check of header/metadata fields`

---

## Phase 02 — Demo Header

- [ ] Standard header fields decoded, correctly version-gated
- [ ] Byte-exact consumption of Header chunk across all 10 files
- [ ] Level name / version plausibility check passed
- [ ] Feature flags identified, cross-referenced against Phase 8 behavior
- [ ] Static cross-check (no live debugging available) resolving game-specific blob question

**Commits:**
- [ ] `feat(phase02): parse standard demo header fields with version gating`
- [ ] `feat(phase02): implement feature flag bitmask decoding`
- [ ] `feat(phase02): detect and parse game-specific header blob (if present)`
- [ ] `test(phase02): byte-exact chunk consumption assertion across samples`
- [ ] `docs(phase02): static cross-check of header fields incl. custom blob`
- [ ] `docs(phase02): note feature-flag cross-reference to revisit after phase08`

---

## Phase 03 — Bit-Level Primitives

- [ ] BitReader + absolute bit-position tracking, unit tested
- [ ] SerializeIntPacked implemented, unit tested, static-disassembly validated (no live debugging available)
- [ ] FString serialization (narrow/wide sign convention)
- [ ] FName network-specific serialization
- [ ] FNetworkGUID-equivalent serialization (static/dynamic distinction) — note: confirm against Iris's `FNetRefHandle`/`FNetToken` framing (Phase 4) rather than assuming a raw legacy `FNetworkGUID` is what appears on the wire
- [ ] Round-trip tests passing for all primitives
- [ ] Phase 1/2 re-validated using these primitives

**Commits:**
- [ ] `feat(phase03): implement BitReader core with bit-position tracking`
- [ ] `feat(phase03): implement SerializeIntPacked with hand-constructed unit tests`
- [ ] `docs(phase03): static disassembly validation of SerializeIntPacked`
- [ ] `feat(phase03): implement FString serialization`
- [ ] `feat(phase03): implement FName network-specific serialization`
- [ ] `feat(phase03): implement FNetworkGUID/FNetRefHandle-equivalent serialization`
- [ ] `test(phase03): round-trip tests for all primitives`
- [ ] `refactor(phase03): re-validate phase01/02 parsing using new primitives`

---

## Phase 04 — Iris NetRefHandle / Replication Protocol Descriptors

> Rewritten for Iris — see updated `04-guid-cache-netfieldexport.md`.

- [ ] `NetRefHandleCache` implemented (static + dynamic resolution), streaming pass
- [ ] `FNetToken` store cache implemented for path/name resolution
- [ ] Replication protocol/descriptor schema cache implemented, streaming pass
- [ ] SDK cross-reference database built (class → property/function → metadata, incl. Iris `NetSerializer` tagging)
- [ ] 100% (or explained) SDK class-name match rate across all 10 files
- [ ] Field-name plausibility check passing
- [ ] Static cross-check (no live debugging available) of NetRefHandle resolution / protocol descriptors

**Commits:**
- [ ] `feat(phase04): implement NetRefHandleCache with static path-name resolution`
- [ ] `feat(phase04): add dynamic NetRefHandle resolution (spawn-info path)`
- [ ] `feat(phase04): implement FNetToken store cache`
- [ ] `feat(phase04): implement replication protocol/descriptor schema cache`
- [ ] `feat(phase04): build SDK cross-reference database (properties + functions, incl. NetSerializer detection)`
- [ ] `test(phase04): SDK coverage metric report across 10 samples`
- [ ] `docs(phase04): static cross-check of NetRefHandle resolution and protocol descriptors`

---

## Phase 05 — Bunches & Channels

- [ ] Frame loop with timestamp extraction, monotonicity-checked
- [ ] Packet loop, byte-exact consumption
- [ ] Bunch header parsing (all flags)
- [ ] Channel state table, open/close/actor-association lifecycle
- [ ] Partial bunch reassembly implemented + validated
- [ ] Control channel behavior confirmed for this build
- [ ] Iris data-stream framing verified against source (not assumed to match legacy `FInBunch` layout)
- [ ] Static cross-check (no live debugging available) of bunch/data-stream header sequences

**Commits:**
- [ ] `feat(phase05): implement demo frame loop with timestamp extraction`
- [ ] `docs(phase05): verify Iris data-stream framing against legacy bunch-header assumption`
- [ ] `feat(phase05): implement packet loop with byte-exact consumption`
- [ ] `feat(phase05): implement bunch header parsing`
- [ ] `feat(phase05): implement channel state table and lifecycle tracking`
- [ ] `feat(phase05): implement partial bunch reassembly`
- [ ] `docs(phase05): document control channel behavior findings for this build`
- [ ] `docs(phase05): static cross-check of bunch/data-stream header sequence`

---

## Phase 06 — Property Replication (Iris)

> Rewritten for Iris — see updated `06-property-replication.md`.

- [ ] `ReplicationStateDescriptorBuilder` traversal reimplemented, cross-validated against observed wire order
- [ ] Dirty-state/changed-member signaling decode implemented
- [ ] Primitive type deserialization implemented via Iris `NetSerializer`s
- [ ] Quantized vector/rotator Iris `NetSerializer` variants ported
- [ ] Plain array replication implemented
- [ ] Delta-array-equivalent replication implemented + tested against a naturally-occurring scenario (no controlled live scenario possible)
- [ ] Game-custom `NetSerializer` structs identified and reversed
- [ ] Full-payload bit consumption assertion passing across all 10 files
- [ ] Temporal coherence check passing
- [ ] Static cross-check (no live debugging available) of descriptor/reader logic

**Commits:**
- [ ] `feat(phase06): reimplement ReplicationStateDescriptorBuilder traversal`
- [ ] `test(phase06): cross-validate descriptor order against observed wire sequence`
- [ ] `feat(phase06): implement dirty-state/changed-member signaling decode`
- [ ] `feat(phase06): implement primitive type deserialization via Iris NetSerializers`
- [ ] `feat(phase06): port quantized vector/rotator Iris NetSerializer variants`
- [ ] `feat(phase06): implement plain array replication`
- [ ] `feat(phase06): implement delta-array-equivalent replication`
- [ ] `test(phase06): naturally-occurring add/modify/remove scenario for delta arrays`
- [ ] `feat(phase06): reverse-engineer and implement game-custom NetSerializer <name>` (repeat per struct)
- [ ] `test(phase06): full-payload consumption + temporal coherence checks`
- [ ] `docs(phase06): static cross-check of descriptor/reader logic`

---

## Phase 07 — RPCs (Iris NetBlobs)

> Rewritten for Iris — see updated `07-rpcs.md`.

- [ ] Iris RPC/NetBlob dispatch mechanism identified and implemented
- [ ] Function resolution via SDK cross-reference
- [ ] Parameter deserialization reusing Phase 6 Iris `NetSerializer` logic
- [ ] Full-payload consumption assertion passing with RPCs present
- [ ] Naturally-occurring scenario test (plausible action → matching RPC) documented (no controlled live scenario possible)
- [ ] Static cross-check (no live debugging available) of RPC blob dispatch

**Commits:**
- [ ] `feat(phase07): implement Iris RPC/NetBlob dispatch detection`
- [ ] `feat(phase07): implement RPC function resolution via SDK`
- [ ] `feat(phase07): implement RPC parameter deserialization`
- [ ] `test(phase07): naturally-occurring scenario RPC test`
- [ ] `docs(phase07): static cross-check of RPC blob dispatch`

---

## Phase 08 — Checkpoints

- [ ] Checkpoint chunk framing implemented
- [ ] Full-checkpoint decoding implemented + validated in isolation
- [ ] Delta-checkpoint mode confirmed/ruled out via flag + empirical check
- [ ] Delta-application logic implemented (incl. destroyed-actor handling)
- [ ] Stream-replay cross-validation harness built, matching across all checkpoints in all 10 files (this is the primary substitute for a live diff on this project — no live ground truth needed)
- [ ] Static cross-check (no live debugging available) of a checkpoint save/load path

**Commits:**
- [ ] `feat(phase08): implement checkpoint chunk framing`
- [ ] `feat(phase08): implement full-checkpoint decoding`
- [ ] `test(phase08): validate full-checkpoint decoding in isolation`
- [ ] `feat(phase08): confirm delta-checkpoint mode via header flag + empirical check`
- [ ] `feat(phase08): implement delta-application logic incl. destroyed-actor handling`
- [ ] `test(phase08): stream-replay vs checkpoint-decoded cross-validation harness`
- [ ] `docs(phase08): static cross-check of a checkpoint save/load path`

---

## Phase 09 — Regression Suite / Iteration

- [ ] Full round-trip check across all 10 files, all hard invariants asserted together
- [ ] Golden-output snapshot system built
- [ ] Bit-reader fuzz/boundary tests added
- [ ] Ongoing cross-file structural diffing wired into the regression suite
- [ ] Documentation of any game-custom serialization reversed, with validation evidence

**Commits:**
- [ ] `test(phase09): full pipeline regression suite across 10 samples`
- [ ] `chore(phase09): golden-output snapshot tooling`
- [ ] `test(phase09): bit-reader fuzz/boundary condition tests`
- [ ] `docs(phase09): document reversed game-custom serialization logic and evidence`

---

## How to update this file

After each validated sub-step:
1. Tick the corresponding checklist box under the phase.
2. Tick the corresponding commit box once that commit is pushed.
3. If all boxes under a phase are ticked, flip that phase's row in the "Overall status" table to `✅ Done`, fill in the branch/tag name, and set "Last updated" to the date.
4. Commit this file by itself: `git add PROGRESS.md && git commit -m "docs(progress): mark phaseNN stepX done" && git push`.
