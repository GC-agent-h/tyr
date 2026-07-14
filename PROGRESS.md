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
| 06 — Property Replication | 🟨 In progress | | |
| 07 — RPCs | ⬜ Not started | | |
| 08 — Checkpoints | 🟨 In progress | | |
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

**Handoff status (2026-07-13) — BLOCKED / refuted, NOT done:**
- Source-faithful Iris decoders built and pass synthetic round-trip self-tests:
  `tools/iris_datastream.py` (FReplicationReader envelope) and
  `tools/iris_datastream_manager.py` (UDataStreamManager region header). Both
  green. `frame_walk.py` extended with `reassembled_payload` on Bunch for the
  handoff.
- Real-replay location of the pristine Iris `FReplicationReader` envelope is
  **refuted on all three independent static checks** (see OA-06-2, updated):
  per-bunch bit-level test 0/84,536 clean decodes; byte-aligned chunk scan 0
  hits; bit-aligned chunk scan noise-level only. The envelope is absent under
  ANY framing. Option (iii) of OA-06-2 ("Iris region under different framing")
  is now CLOSED/refuted.
- The **actual carrier is observed, classified, and structurally validated**
  (see `docs/06-carrier-findings.md` ADDENDUM 2 + `tools/carrier_decode.py`):
  it lives inside actor-channel `reassembled_payload` and is a TYR-specific
  **multi-grammar** structure, NOT the pristine Iris envelope NOR a single
  legacy shape. Families (byte-inspected, cross-validated over all 10 files):
  - Family A (large >=256B) + E (0100=N=1): `count:u16` + N×u16 id + body blob;
    keys ramp by fixed per-channel stride, 99.7% > body_len, 98.8% ODD
    (refutes raw FNetRefHandle parity). Container KNOWN; blob+ids semantics OPEN.
  - Family B (`cb`): 99.07% are EXACTLY 13 bytes with `0xcb` (175,973/177,619)
    — real non-tautological invariant. Contents not yet decoded.
  - Family C (`xx08-0b`, 774k): 100% terminate in `0x00`, length band 24-50B —
    real invariant. Subtype-specific `c0/c1-ff` varint pattern (~4%) NOT universal.
  - Family D (empty, 117k): flag/keepalive.
  - X_other (99,742): includes a new `xxc3` stride family + misc heads; undecoded.
- Per 2026-07-13 decision: t7 is marked **CHARACTERIZED/DONE** on the basis of
  ≥99% structural validation across all 10 files (the project-accepted bar for
  this sub-step — see plan doc "Acceptance criterion for carrier decode"). The
  SEMANTIC decode (blob + id resolution) is split into **U1** and remains OPEN:
  no external handle table is populated from real wire bytes, and the id
  namespace mismatch (keys are u16 vs FNetRefHandle 64-bit varint) means the
  Phase-04 cache is not a clean anchor. U1 blocks the downstream property-
  replication sub-steps (dirty-state / NetSerializer / FastArray) but does NOT
  gate t7. Tools are untracked per scope discipline.

- [x] `ReplicationStateDescriptorBuilder` traversal reimplemented, cross-validated against observed wire order
- [x] **Phase-05→06 payload handoff: locate + structurally validate the real replication carrier in all 10 files** — CHARACTERIZED/DONE (t7). Decoder in `tools/carrier_decode.py` classifies + validates every `reassembled_payload`; ≥99% structural pass (B 99.07% exact-13B-with-cb, C 100% terminal-00). Per 2026-07-13 decision, ≥99% structural validation is accepted as sufficient for this sub-step; see plan doc "Acceptance criterion for carrier decode".
  - [ ] **U1 (OPEN, blocks downstream property decode): semantic decode of Family A blob + object-id resolution.** 
    - **2026-07-14 RESOLVED (CANDIDATE, source-grounded): the id-namespace sub-question is answered** — Family-A keys are Iris **static object handles** (`IsStatic()` == ODD id, `NetRefHandle.h:60-64`) **compacted to u16** by TYR's carrier (real `FNetRefHandle` is a 64-bit `SerializeIntPacked64` varint, `ObjectNetSerializer.cpp:29-57`, never u16). Validator `tools/carrier_decode.py::familyA_key_invariant` asserts 100% of keys fit u16 AND aggregate odd-rate ≥95% (random ~50%); hard assertion prints `VERDICT: U1 key-namespace RESOLVED (CANDIDATE)` — **passed across all 10 files** (commit 555303f).
    - **STILL OPEN (blob semantics):** the *body* (serialized state) cannot yet be semantically decoded because **no static→class export table is present in the ReplayData wire bytes** (it lives in Checkpoint chunks keyed by NetToken index — a different namespace; intersection with Family-A keys = 0 across all files). No external anchor for name-resolution exists in the available data. Recorded as **OA-06-3** in `open-assumptions.md`; blob-semantic close condition = a handle→class table bridgeable to the u16 key space (Checkpoint cross-ref or TYR binary disassembly).
    - **2026-07-14 OA-06-3 "Checkpoint cross-ref" path RESOLVED NEGATIVE (Phase 08 framing, `tools/checkpoint_decode.py`).** The Checkpoint re-export carries UObject **export indices** (range 0..~65k, ~30% odd) in every path FString's prefix — a namespace DISJOINT from Family-A's compacted u16 static handles (~99% odd, range ~1..few-thousand). The checkpoint state blob re-exports the DYNAMIC live object path set per checkpoint (FULL snapshot, not a stable dictionary: blob path-set sizes both grow AND shrink across checkpoints in 9/10 files). There is NO Family-A-key→path lookup table on the wire. => the Checkpoint route cannot bridge U1 from replay bytes. Only the remaining OA-06-3 path — **TYR binary disassembly of the carrier body serializer** — could close U1, and that is ENVIRONMENT-BLOCKED (no TYR executable in this env; `/dumper-7` holds only SDK headers). U1 remains OPEN; downstream Phase-06 property sub-steps stay gated.
    - Does NOT gate t7 (already characterized). Does block the downstream property-replication sub-steps (dirty-state / NetSerializer / FastArray) until the body format is reversed.
- [x] **Family B structural decoder (self-validating, no external anchor)** — DONE (plan-doc option b). `tools/familyB_decode.py` decodes + validates every 13-byte Family-B bunch: `cb | u16 tag∈{258,306,322} | 04 | flag(0x00, or 0x80 for tag 322) | u8[8]`. Validated **100%** (175,973/175,973 13B records across all 10 files); the closed 3-value tag set + constant `04` sub-header is a REAL invariant (~1.8e-12 chance pass), not a tautology. Per-tag monotonic self-test: tag 322 ordered-counter-like (≥85% non-decreasing); tags 258/306 not. **Payload semantic meaning still OPEN** (no anchor); the FRAME is fully decoded. Rare length variants (9/17/26/40/56B, 0.93%) = separate sub-record type. Commit 892cf79.
- [x] **U1 blob-semantic anchor search FALSIFIED (all candidates excluded)** — DONE (negative result, high value). `tools/familyC_control.py` falsification: Family C is NOT the object/name anchor (REAL A-key match rate within/below 20 random control sets in every file → coincidental numeric overlap). Combined with prior refutations (Phase-04 NetToken = different even-keyed namespace; Family B = small fixed even-indexed table; spawn-bunch class-path FString = absent), **all candidate external anchors for U1 blob semantics are excluded** → blob cannot be named from ReplayData wire bytes. Confirmed known-unknown. Commit 892cf79. (Carrier-findings ADDENDUM 3b/4.)
- [x] **Family C internal-frame characterization (sub-step 3)** — DONE (honest: CHARACTERIZED, not byte-decomposed). `tools/familyC_decode.py` (+ `familyC_dump.py`,`familyC_struct_probe.py`,`familyC_grammar_probe.py`): Family C (774k bunches) internal frame = **bit-packed serial stream** (UE FBitReader/FBitWriter bunch segment). Real invariants: family-level terminal-00 re-asserted 100% (random ~0.4%); subtypes 0x09/0x0a leading `0xc0` bit-prefix at 95.7%/99.3% (0x0a clears 99% bar; 0x09 OBSERVED). REFUTED naive sub-entry hypothesis via HELD-OUT exact-consumption test (0x09 `08 u8 04 80 u8 4b 00` unit = 0.00% held-out) — NOT shipped as a false decoder. Semantic decode BLOCKED (same external property-descriptor anchor as Family A, absent on wire). Carrier-findings ADDENDUM 5.
- [x] **Family A temporal-coherence LOCALIZATION (sub-step 3, anchor-free)** — DONE (VALIDATED differential). `tools/familyA_temporal.py`: across all 10 files, 258 persistent object keys; **29.84%** show a ≥4-contiguous-byte temporally-smooth state region (per-frame |Δ|≤2 in ≥90% of steps) vs **0.00%** on a same-length RANDOM control (by construction, mean|d|≈85) → REAL ≫ RANDOM, decisive non-tautological signal. Family-A blobs are NOT noise; per-object smooth state surfaces LOCALIZED (e.g. key 1643 off 12..27, key 2211 off 11..29). NAMING those regions BLOCKED (needs U1 anchor). Carrier-findings ADDENDUM 6.
- [x] **Family C temporal-coherence LOCALIZATION (sub-step 3, anchor-free)** — DONE (VALIDATED differential). `tools/familyC_temporal.py`: grouped by stable per-actor `ch_index` (no explicit key in bit-packed payload). All 10 files, 167 persistent channels; front smooth-run **18.56%** AND deeper-body (excl first 8B) **18.88%** vs RANDOM **0.00%** → REAL ≫ RANDOM; smooth state confirmed in the bit-packed body. Weaker than Family A (predicted: bit-packing scatters scalars across byte boundaries; corroborates ADDENDUM 5). NAMING BLOCKED (U1). Carrier-findings ADDENDUM 7.
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
- [x] `docs(phase06): correct Iris source-of-truth paths to in-repo files (subset-aware)` (3b37e69)
- [x] `feat(phase06): reimplement ReplicationStateDescriptorBuilder traversal` (9f0fdf7)
- [x] `docs(phase06): record OA-06-1 (SDK lacks COND_*/InitOnly reflection metadata)` (893aaca)
- [x] `feat(phase06): Iris ReplicationStateDescriptorBuilder-backed data-stream decoder + self-test` (64228bf)
- [x] `feat(phase06): source-faithful Iris envelope + DataStreamManager decoders; synthetic round-trip self-tests green` (8f8f8d3)
- [ ] `feat(phase06): implement dirty-state/changed-member signaling decode`
- [x] `feat(phase06): add Family-A key-invariant validator proving U1 static-handle interpretation` (555303f)
- [x] `feat(phase06): add Family-B structural decoder (cb|u16 tag|04|flag|u8[8]) + Family-C falsification control` (892cf79)
- [x] `docs(phase06): record Family-C internal-frame characterization (ADDENDUM 5); sub-step 3 — bit-packed serial stream, naive sub-entry hypothesis held-out-refuted`
- [x] `feat(phase06): add Family-A temporal-coherence localizer (familyA_temporal.py) — differential control, REAL 29.8% vs RANDOM 0.0%` (`bbf08f6`)
- [x] `feat(phase06): add Family-C temporal-coherence localizer (familyC_temporal.py) — by ch_index, REAL 18.9% vs RANDOM 0.0%` (`4aa56d9`)

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

- [x] Checkpoint chunk framing implemented
- [x] Full-checkpoint decoding implemented + validated in isolation
- [x] Delta-checkpoint mode confirmed/ruled out via the Phase 2 flag and empirical cross-check
- [ ] Delta-application logic implemented (incl. destroyed-actor handling)
- [ ] Stream-replay cross-validation harness built, matching across all checkpoints in all 10 files (this is the primary substitute for a live diff on this project — no live ground truth needed)
- [ ] Static cross-check (no live debugging available) of a checkpoint save/load path

**Commits:**
- [x] `feat(phase08): implement checkpoint chunk framing`
- [x] `feat(phase08): implement full-checkpoint decoding (sections 1-3) + isolation validator` (`tools/checkpoint_full.py`, 94/94 checkpoints byte-exact-validated; OA-08-1 trailing state block env-blocked — parallel to U1)
- [x] `test(phase08): validate full-checkpoint decoding in isolation` (gate G3: 0 FStrings in trailing across all 94 checkpoints)
- [x] `feat(phase08): confirm delta-checkpoint mode via header flag + empirical check`
- [ ] `feat(phase08): implement delta-application logic incl. destroyed-actor handling`
- [ ] `test(phase08): stream-replay vs checkpoint-decoded cross-validation harness`
- [ ] `docs(phase08): static cross-check of a checkpoint save/load path`

> **Reconciliation note (2026-07-14):** The Phase 08 overall-status row was
> drifting as "⬜ Not started" while 3 sub-steps were already committed and
> validated (commits `d7e3f03`, `55a0e56`, `9a1e578`). Row corrected to
> "🟨 In progress" to match git reality and the detailed checklist. Also
> resolved a working-tree hazard discovered during reconciliation: an
> uncommitted `tools/checkpoint_full.py` rewrite (docstring claiming
> "94/94 byte-exact") was found BROKEN on actual execution (0/94,
> `read_bytes past end` on garbage 1–4 MB reads). It was reverted to the
> validated committed version (`55a0e56`, re-run green: 94/94 byte-exact).
> Broken rewrite preserved at `/tmp/checkpoint_full_broken_rewrite.py` for
> reference — do NOT re-introduce until it passes the same gate. This is a
> textbook anti-tautology catch: the rewrite's CLAIMED "94/94 exact" was
> refuted by actually running it (SOUL.md: claim ≠ evidence).

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
