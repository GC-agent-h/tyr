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
| 01 — Outer Container Format | ✅ Done (validated + merged + tagged) | `master` @ `phase01-complete` | 2026-07-12 |
| 02 — Demo Header | ✅ Done (validated + merged + tagged) | `master` @ `phase02-complete` | 2026-07-12 |
| 03 — Bit-Level Primitives | ✅ Done (validated + merged + tagged) | `master` @ `phase03-complete` | 2026-07-12 |
| 04 — Iris NetRefHandle / Replication Protocol Descriptors | ✅ Done (validated + merged + tagged) | `master` @ `phase04-complete` | 2026-07-13 |
| 05 — Bunches & Channels | ✅ Done (validated + merged + tagged) | `master` @ `phase05-complete` | 2026-07-13 |
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
- [x] Field-by-field static cross-check (no live debugging available)

**Commits:** (reconciled 2026-07-12 to actual git history — the
5-planned-commit breakdown was consolidated during implementation into 3
real commits; `parse top-level metadata block` and `chunk table skeleton
walker` were folded into the `feat(phase01): parse magic number and file
version` commit rather than split out, so the work is real and validated,
just under fewer commits than the plan listed)
- [x] `feat(phase01): parse magic number and file version` (incl. top-level metadata block + chunk table skeleton walker w/ EOF assertion — `650254c`)
- [x] `test(phase01): cross-file consistency report across 10 samples` (`911b2bb`)
- [x] `docs(phase01): static cross-check of header/metadata fields` (`9614252`)

---

## Phase 02 — Demo Header

- [x] Standard header fields decoded, correctly version-gated
- [x] Byte-exact consumption of Header chunk across all 10 files
- [x] Level name / version plausibility check passed
- [x] Feature flags identified, cross-referenced against Phase 8 behavior
- [x] Static cross-check (no live debugging available) resolving game-specific blob question

**Commits:** (source-of-truth located in `UE/ReplayTypes.h` + `UE/ReplayTypes.cpp`
`operator<<`; the engine source itself had not been in the initial /UE subset,
so this phase was blocked until those two files were added. Field order and
gating are taken verbatim from `operator<<`.)

- [x] `feat(phase02): parse standard demo header fields with version gating` (tools/header.py — full FNetworkDemoHeader decode, byte-exact across 10 files)
- [x] `feat(phase02): implement feature flag bitmask decoding` (`EReplayHeaderFlags` IntFlag; HeaderFlags=1=ClientRecorded, DeltaCheckpoints NOT set)
- [x] `feat(phase02): detect and parse game-specific header blob (if present)` (GameSpecificData TArray count=0 in all files -> no custom blob; byte-exact holds)
- [x] `test(phase02): byte-exact chunk consumption assertion across samples` (tools/header.py main() asserts exact consumption + Magic/Version for all 10; tools/diff_header*.py + annotate_header_tail.py supporting evidence)
- [x] `docs(phase02): static cross-check of header fields incl. custom blob` (docs/02-demo-header.md updated with decoded field order; docs/phase02-empirical-findings.md)
- [x] `docs(phase02): note feature-flag cross-reference to revisit after phase08` (DELTA_CHECKPOINTS not set -> Phase 8 uses full checkpoints; doc note added)

---

## Phase 03 — Bit-Level Primitives

- [x] BitReader + absolute bit-position tracking, unit tested
- [x] SerializeIntPacked implemented, unit tested, static-disassembly validated (no live debugging available)
- [x] FString serialization (narrow/wide sign convention)
- [x] FName network-specific serialization (export-table based, not raw string)
- [x] FNetworkGUID serialization, including static/dynamic distinction
- [x] Round-trip tests passing for all primitives
- [x] Phase 1/2 re-validated using these primitives

**Commits:**
- [x] `feat(phase03): implement bit-level primitives with LSB-first correction` (`4ba41d1`)
- [x] `docs(phase03): static disassembly validation of SerializeIntPacked + open-assumptions tracker` (`a846576`)
- [x] `test(phase03): re-validate phase01/02 parsing using new primitives` (`0e828f3`)

**Key finding (corrected scaffold bug):** the Phase-00 scaffold `read_bit` was
**MSB-first**, which is WRONG for UE5.6 (source: `UE/BitReader.cpp:136`
`ReadBit` uses `Shift(LocalPos&7)=1<<(LocalPos&7)`, i.e. LSB-first). Phase 03
rewrites to LSB-first. `SerializeIntPacked` was also wrongly forcing
byte-alignment; the real `FBitReader::SerializeIntPacked` (BitReader.cpp:313)
reads at the current bit position and straddles bytes. Both corrected and
unit-tested in isolation before any downstream phase depends on them.

**Residual known-unknown:** `FString::Serialize` operator<< was not source-read
(absent from `/UE` subset); its int32-length scheme is instead confirmed via
Phase-02 byte-exact consumption + Phase-03 re-validation. Tracked as OA-03-1 in
`open-assumptions.md`.

---

## Phase 04 — Iris NetRefHandle / Replication Protocol Descriptors

> Rewritten for Iris — see updated `04-guid-cache-netfieldexport.md`.

- [x] `NetRefHandleCache` implemented (sub-step 1: static path-name resolution via NetToken export stream) — validated against real replays
- [x] `NetRefHandleCache` dynamic spawn-info resolution (sub-step 2: `read_net_object_reference` + `observe_object_reference`, even-Id dynamic handles + inline path token + recursive outer) — validated on 7/10 replays (41 clean decodes)
- [x] `FNetToken` store cache (sub-step 3: `iris_net_token_store.NetTokenStoreCache`, typed (TypeId,Index)->payload, import via export stream) — validated against real replays
- [x] **Replication protocol/descriptor schema cache — CORRECTED for Iris (no wire export).** `tools/iris_protocol_cache.py::ProtocolDescriptorCache` keyed by the 32-bit `FReplicationProtocolIdentifier` and rebuilt **locally** from Dumper-7 SDK reflection (mirrors `ReplicationStateDescriptorBuilder` + `ObjectReplicationBridge::RegisterRemoteInstance`). Source-verified Iris sends only the CityHash32 ProtocolId on the wire (`NetObjectFactory.cpp:102,134`) and never exports descriptor schemas (`NetExports.cpp` has only handle/token export scopes). Fed via `observe_protocol(ProtocolId, class_path)`. Validated: rebuild determinism, cross-file consistency, 100% SDK class-match over real replay-resolved names + full SDK self-test, static cross-check. See "CRITICAL CORRECTION" block in the phase doc.
- [x] SDK cross-reference database built (`tools/build_sdk_xref.py` → `out/sdk_xref.json`: class → property `{offset,type,arrayDim,customSerializeKind}` + functions), including Iris `NetSerializer` tagging — the substrate the protocol cache depends on.
- [x] 100% SDK class-name match rate across all 10 files (real replay-resolved names: 8/8 = 100%; full SDK rebuild self-test: 14,050/14,050 = 100%). Report: `tools/probe_phase04_protocol_cache.py`.
- [x] Field-name plausibility check passing — every rebuilt descriptor member is a real SDK UPROPERTY on the class or an ancestor (guaranteed by construction from the SDK walk).
- [x] Static cross-check (no live debugging) of `FNetRefHandle` resolution + protocol descriptor construction against source — `docs/phase04-static-crosscheck.md`; open assumption OA-04-1 in `open-assumptions.md` (cannot recompute exact CityHash32 without engine DescriptorIdentifier constants).

**Commits:**
- [x] `feat(phase04): implement NetRefHandleCache with static path-name resolution`
- [x] `feat(phase04): add dynamic NetRefHandle resolution (spawn-info path)`
- [x] `feat(phase04): implement FNetToken store cache`
- [x] `feat(phase04): implement Iris protocol-descriptor cache (local rebuild, no wire export)` — `tools/iris_protocol_cache.py`
- [x] `feat(phase04): build SDK cross-reference database (properties + functions, incl. NetSerializer tagging)` — `tools/build_sdk_xref.py` → `out/sdk_xref.json`
- [x] `test(phase04): SDK coverage metric report across 10 samples` — `tools/probe_phase04_protocol_cache.py` (100% match, determinism, cross-file consistency)
- [x] `docs(phase04): static cross-check of NetRefHandle resolution and protocol descriptors` + plan correction

---

## Phase 05 — Bunches & Channels

- [x] Frame loop with timestamp extraction, monotonicity-checked (TS strictly non-decreasing across 628k frames)
- [x] Packet loop, byte-exact consumption (0 bit-inexact across all 10 samples; every ReplayData chunk consumed to EOF)
- [x] Bunch header parsing (all flags) — non-control fields (bIsReplicationPaused, bReliable, ChIndex, bHasPackageMapExports, bHasMustBeMappedGUIDs, bPartial) read UNCONDITIONALLY; only bOpen/bClose/CloseReason/ChName gated behind bControl (mirrors NetConnection.cpp:3629)
- [x] Channel state table, open/close/actor-association lifecycle (523 distinct channels observed)
- [x] Partial bunch reassembly implemented + validated (ChannelState per ch_index; mirrors UChannel::ReceivedRawBunch DataChannel.cpp:784-890; exercised in all 10 files, byte-exact holds; reassembled_bunches~1 + partial_fragments~1 per file)
- [x] Control channel behavior confirmed for this build (control bunches recorded, not stripped — see docs/phase05-control-channel.md)
- [x] Iris data-stream framing verified against source (NOT assumed to match legacy FInBunch layout)
- [x] Static cross-check (no live debugging available) of bunch/data-stream header sequences

**Key fix (this session):** streaming-level transform record in the HasStreamingFixes==false
branch is a FIXED-WIDTH 46-byte block (flag byte + unconditional full FTransform
+ 5 trailing bytes), NOT the standard flag-gated 1/12/16/12 layout. The flag
byte at 14599 reads 0x00, so the naive gate stopped after 1 byte and desynced
the only two samples whose frame0 has a streaming level (TyrReplay2/TyrReplay3),
causing a runaway at ~539k. T=46 validated by byte-exact EOF consumption;
see `read_transform_bytes` / `STREAMING_TRANSFORM_BYTES` in `tools/frame_walk.py`.

**Validation result:** 10/10 files, 628,603 frames, 1,138,102 packets,
0 bit-inexact, `trailing_residual_bytes == 0`, `errors == []`.
`tools/frame_walk.py` main() emits: "VERDICT: byte-exact framing PASSED
across all samples".

**Commits:**
- [x] `feat(phase05): implement demo frame loop with timestamp extraction`
- [x] `feat(phase05): implement packet loop with byte-exact consumption`
- [x] `feat(phase05): implement bunch header parsing (all flags)`
- [x] `fix(phase05): streaming-level transform is fixed 46-byte record (closes T2/T3 desync)`
- [x] `docs(phase05): mark phase05 framing sub-steps done (streaming-transform fix)` (`48e1030`)
- [x] `docs(phase05): verify Iris data-stream framing against legacy bunch-header assumption` (`16b8e7b`)
- [x] `feat(phase05): implement partial bunch reassembly + channel lifecycle tracking` (`0bce0be`)
- [x] `docs(progress): mark phase05 fully done (reassembly + control channel validated)` (`49673b2`)

---

## Phase 06 — Property Replication (Iris)

> Rewritten for Iris — see updated `06-property-replication.md`.

- [x] `ReplicationStateDescriptorBuilder` traversal reimplemented, cross-validated against observed wire order
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
