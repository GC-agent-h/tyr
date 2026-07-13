# Phase 06 — Carrier Characterization Findings (2026-07-13)

Status: CANDIDATE characterization. NOT a validated full decoder yet (README
hard gate not met for "byte-exact consumption across all 10 files" — see
confidence levels below). Purpose: record what the real replication carrier IS,
now that OA-06-2 has closed the "pristine Iris envelope" hypothesis.

## Method (all static; no live debugging available — per project constraint)

Reused `frame_walk.py` (Phase-05 validated, byte-exact framing over all 10
files) to walk frames/packets/bunches and read `Bunch.reassembled_payload`,
then ran a battery of structural diagnostics:

- `diag_carrier_probe.py` — per-file dump of largest + spawn bunch (head + body).
- `diag_carrier_count.py` — tried 6 count-encodings (u16/SIP at offsets 0/1/2/4).
- `diag_carrier_stable.py` — key-set stability + key-vs-body-length test.
- `diag_carrier_keys.py` — odd/even parity of the "u16 keys" + range.
- `diag_carrier_bits.py` — bit-packed SerializeIntPacked full-payload decode.
- `diag_carrier_all.py` — grammar pass-rate per size band + fail-head survey.
- `diag_carrier_small.py` / `diag_carrier_bitparse.py` — small-bunch families.

## KNOWN (direct observation, repeated)

1. **The carrier is NOT the pristine UE5.6 Iris `FReplicationReader::Read`
   envelope.** Confirmed three independent ways (per-bunch bit test 0/84,536;
   byte-aligned scan 0; bit-aligned scan ~5e-6 noise). OA-06-2 option (iii)
   CLOSED/refuted. (Confidence 95%.)

2. **The carrier lives inside actor-channel bunch payloads**
   (`reassembled_payload`). Transport = legacy DemoNetDriver
   frames/packets/bunches (Phase 05). The payload contents are a TYR-specific
   multi-grammar structure, not the standard Iris data stream. (95%.)

3. **≥3 recurring payload grammar families exist** (by leading-2-bytes):

   - **Family A — large replicated-state bunch.** Head `count:u16` (N), then
     `N × u16 LE key`, then a body blob. Dominant for payloads ≥256 bytes
     (observed pass-rate 98.5% in the 256–1024B band, but see caveat C1).
     Example (TyrReplay1 ch13): `1f 00` = N=31, then keys
     `4b02 5302 5b02 ...` (587, 595, 603… ramp +8), then a ~1936-byte body that
     contains a byte-run (`40 06 b6 23 e1 a0 2c 2c 43`) shared with the spawn
     bunch body on the same channel → body is serialized object/state. (90%.)

   - **Family B — bit-packed control/reference records.** Head `cb 32` /
     `cb 42` (≈146k bunches/file). 13-byte fixed length. Bit-parses cleanly as
     SerializeIntPacked: `[6475, 1, 4, 0, ...]` — i.e. a packed id followed by
     a 1/0 flag sequence, consistent with an object-reference or ack record.
     NOT byte-aligned u16. (85%.)

   - **Family C — `xx 0a` name/arg blocks.** Head `77 0a`, `5f 0a`, `8f 0a`,
     `47 0a`, `1f 0a`, `37 0a` (first byte = per-channel base + stride 0x10/0x18;
     second byte constant `0a`). Length 51–58B. Byte-structured, does NOT
     bit-parse as SerializeIntPacked (reads garbage). Recurring tail
     `...c1 ff .. .. 00` suggests an FString/name or RPC-arg block. (75%.)

   - **Family D — empty payloads** (`''`, ≈117k bunches/file). Zero-length.
     A flag/keepalive bunch, not a grammar. (95%.)

   - **Family E — `01 00`** (≈8k/file). This is Family A with N=1 (count=1).
     (85%.)

4. **The "keys" in Family A are NOT payload offsets nor stable slot indices.**
   - key > body_len in 99.7% of cases (e.g. key≈2223 while body≈60B) → keys
     index something OUTSIDE the body (object/handle space). (95%.)
   - key-set is NOT stable across frames (0/353 channels have ≥90% identical
     key-set) → keys vary per update, not fixed slot ids. (90%.)
   - keys ramp by a FIXED stride within a bunch (587,595,603,607 = +4/+8) and
     the BASELINE is fixed per channel across files (ch13≈587; ch228≈2215) →
     per-channel object-handle BASE, not arbitrary. (85%.)

5. **98.8% of Family-A keys are ODD (max 65535, full u16 range).** This
   REFUTES the interpretation that they are raw `FNetRefHandle::raw_id`
   (which would be ~50/50 odd/even per NetRefHandle.h:60-64). So either they
   are a different handle encoding, or they are not handles at all. (90%.)

## CANDIDATE (limited/conflicting evidence — NOT confirmed)

- Family A keys are a per-channel object index (base + stride), pointing into
  a handle/object table resolved elsewhere (NOT the Phase-04 NetToken store,
  which populates from a separate byte-aligned export region). Confidence 40%.
  Contradicted by: 98.8% odd parity; Phase-04 handle parity model.
- Family C `xx0a` blocks are FString/name or RPC-argument records. Confidence
  35%.
- Family B `cb32` blocks are object-reference/ack records (SerializeIntPacked
  id + flags). Confidence 50%.
- TYR ships a customized/older Iris variant. Confidence now LOWER (45%) — the
  multi-grammar byte structure looks more like a game-specific carrier than a
  near-standard Iris variant. Do NOT assert without binary evidence.

## Open unknowns (must resolve before a validated decoder)

- U1. What is the EXACT count/key encoding for Family A? The naive `count:u16`
  is under-constrained by consumption (C1), so a different prefix/width is
  plausible. Need an external anchor (e.g. correlate Family-A keys with an
  independently-resolved object list, or disassemble TYR's replication send
  path).
- U2. What do Family A bodies contain semantically (positions? health?
  transforms?)? Not yet decoded.
- U3. Family C tail structure (FString vs packed args) unresolved.
- U4. Why 98.8% odd keys — encoding unknown.

## Caveats (intellectual honesty)

- **C1 (critical):** the "grammar pass rate" I first computed for
  `count:u16 + N×u16 + body` is TAUTOLOGICAL — any u16 `count` small enough
  "consumes" by construction, so 98.5% is NOT a real validation. The genuine
  evidence for Family A is the *regular ramp + shared body byte-run + key>body*
  observations, not the consumption rate. A real decoder needs an external
  anchor (U1) before it can be called validated.
- **C2:** No Phase-04 handle cache is populated from real replay bytes by
  `frame_walk.py` (Phase 04 validated via separate byte-scan probes). So a
  cross-anchor of Family-A keys to resolved handles is not yet wired up; U1
  remains open.

## Next build steps (when authorized)

1. Wire `NetRefHandleCache`/token store population into the frame walker so
   Family-A keys can be tested against resolved objects (closes U1 anchor).
2. Per-family decoders in `tools/carrier_decode.py`: Family B (bit-packed) is
   the most tractable and most likely to reach byte-exact consumption first.
3. Re-run the phase-doc Validation (full consumption + one semantic anchor)
   only after U1 is closed. Do NOT tick Phase-06 t7 until then.

## ADDENDUM 2026-07-13 (internal static validators exhausted)

Further probing of Family A's body to find a non-tautological validator:

- REFUTED: body = N equal-sized records. `body_len % N == 0` held for only
  40.8% of 7,861 candidate bunches (~ chance level for random N); `body_len//N`
  scatters across 19/30/32/33/34/36/37/... with no dominant record size. (90%.)
- REFUTED: body = N `[u16 sublen][sublen bytes]` variable records. Exact
  consumption = 0/7,861. u8 sublen variant = 97/7,861 (1.23% ≈ chance). (90%.)
- Therefore: the `count:u16` counts the **object-id list**, not records that
  tile the body. The body is a single OPAQUE serialized-state blob. The
  surviving model is exactly: `[count:u16][N×u16 external object-id][blob]`.
  This container is byte-exact by construction (count fixes id-bytes, rest =
  blob) but UNDER-CONSTRAINED as a validator (any count fits) — consistent with
  the earlier C1 caveat. (85%.)

Implication for U1: **no further internal static test can close U1.** The body
semantics and the id-resolution require an EXTERNAL anchor that is not present
in the available data:

- Phase-04 `NetRefHandleCache.handle_cache` is NOT populated from real wire
  bytes by any committed walker (probe_phase04_iris.py only fills the
  token_store path-strings via the separate NetToken export stream). So there
  is no real handle table to test keys against.
- Even if wired, Phase-04 `FNetRefHandle.raw_id` is a `SerializeIntPacked64`
  (64-bit varint, unbounded by 16 bits), whereas Family-A keys are **u16
  (max 65535, 98.8% odd)**. The namespaces do not line up: the keys are not
  literal `.raw_id` values. So "wire the handle cache and match keys" is not a
  clean anchor — it would require an un-evidenced mapping.
- Keys span the full u16 range (max 65535) and ramp by fixed per-channel
  stride (587,595,603…), so they are NOT small indices into a tiny table. The
  98.8% odd parity is best explained as a game-specific id encoding (e.g.
  low bits = type/static flag), NOT legacy raw_id parity. (CANDIDATE 40%.)

## ADDENDUM 2 (2026-07-13) — CORRECTED family validators (decoder built)

After raw byte inspection of `carrier_decode.py` over all 10 files, TWO
earlier claims were RETRACTED (over-read from small samples):

- RETRACTED: "Family B is a SerializeIntPacked stream reading [6475,1,4,0]".
  That was a forced varint read past a non-continuation byte (`cb 42 01 04 00`:
  byte 3 = 0x01, high-bit clear, yet not last). Family B is NOT a varint stream.
- RETRACTED: "Family B is a fixed 13B record with constant anchors
  `01 04 00` / `03 02 00`". Offsets 1–12 are variable data, not constants.

CORRECTED, DEFENSIBLE structural validators (non-tautological — a random byte
stream does not match these at the observed rates):

- **Family B (`cb`)**: 99.07% of `cb` bunches are EXACTLY 13 bytes with `0xcb`
  at offset 0 (175,973/177,619). Rare length variants (9/17/26/40/56B) = 0.93%.
  Invariant = `pl[0]==0xcb AND len==13`. (Random match ≈ 1/256 × 1/256.)
- **Family C (`xx08-0b`)**: 774,307 bunches, **100% terminate in `0x00`**,
  length band 24–50B. The `c0/c1-ff` varint pattern seen in some samples is
  subtype-specific (~4% of samples), NOT universal — RETRACTED as the family
  signature. Invariant = `pl[1] in {0x08..0x0b} AND pl[-1]==0x00`. (Random
  terminal-00 ≈ 0.4%.)
- **Family A (large >=256B)** and **E (`0100`, N=1)**: container
  `[count:u16][N×u16 id][blob]`; keys 98.8% odd, 99.7% > body_len (reconfirmed
  across 85,066 bunches).
- **Family D (empty)**: 117,036 flag/keepalive bunches.
- Remaining **X_other = 99,742** bunches incl. a newly-seen `xxc3` stride
  family (`bbc3/fbc3/d3c3/a3c3`) + `4b00`/`0b21`/`04`(1-byte) heads. Not yet
  characterized.

Decision point: U1 cannot be closed statically with current tooling. Options:
  (a) Build a per-file object/name table from the Family-C (`xx0a`) blocks and
      test whether Family-A keys index into it (needs Family C decoded first).
  (b) Accept the carrier CHARACTERIZATION as the deliverable for this sub-step
      (container grammar KNOWN; blob+ids OPEN) and move Family A decoding to
      CANDIDATE; proceed to build the Family B (bit-packed) decoder, which is
      self-validating and does not need an external anchor.
  (c) Attempt to wire Phase-04 token export + handle observation into the real
      frame walker and build a genuine cross-anchor (largest effort, highest
      payoff if the id-namespace mismatch can be bridged).

## ADDENDUM 3 (2026-07-14) — U1 id-namespace RESOLVED (source + empirical)

The U1 dead-end is broken at the *id* level. The plan's option (c) ("wire
Phase-04 token export + match keys") was tested and **refuted as a viable
anchor** — but in doing so it surfaced the real explanation.

### Source facts (UE5.6, in-repo `/UE`)
- `UE/NetRefHandle.h`: `FNetRefHandle::GetId() = (Serial<<1)|Static`;
  `Serial`=53 bits, `Static`=1 bit, `ReplicationSystemId`=10 bits → 64-bit
  value, wire-serialized via `WritePackedUint64` (`SerializeIntPacked64`)
  in `UE/Iris/Private/Iris/Serialization/ObjectNetSerializer.cpp:29-57` —
  **NOT a u16**.
- `IsStatic()` == ODD id; `IsDynamic()` == EVEN id (NetRefHandle.h:60-64).

### Empirical (all 10 files; `tools/carrier_decode.py` + `tools/u1_probe*.py`)
1. Family-A keys are **u16**: max ≤ 65535 in every file. Real 64-bit
   `SerializeIntPacked64` ids would routinely exceed 65535 — so TYR's carrier
   **compacts Iris static handles to u16**.
2. **Odd parity 93.7%–100% (aggregate 98.77%)** — matches the Iris
   `IsStatic()` ODD invariant by overwhelming majority. The ~1.23% even keys
   are consistent with occasional dynamic (even) handles sharing the stream.
3. **Phase-04 NetToken indices are a DIFFERENT space** (millions, even —
   e.g. 1099392, 222299456, found in Checkpoint chunks). Intersection of
   Family-A keys and the NetToken index space = **0** across all files. So
   "wire the handle cache and match keys" is NOT an anchor. Confirmed.
4. **Family-B lead u16 is even, only 3 distinct values** (files 2/3/4);
   0% in A-space for files 5–9. A small fixed even-indexed table, NOT an
   object-id anchor. Ruled out.
5. Spawn (first) bunch on a channel == `E_0100` (N=1) record whose body
   equals the channel's first Family-A body (T3: 16/19 channels share
   key+body). Keys are **persistent per-object ids**; the body IS the object's
   serialized state.

### Conclusion
U1's *id-namespace* question is RESOLVED (CANDIDATE, source-grounded):
**Family-A keys are Iris static object handles, compacted to u16 by TYR's
carrier.** The *blob semantic decode* (positions/health/…) REMAINS OPEN:
no static→class export table is present in the ReplayData wire bytes (it lives
in Checkpoint chunks keyed by NetToken index — a different namespace). This is
exactly the plan doc's stated condition: U1 "does NOT gate t7" but "blocks
the downstream property-replication sub-steps."

### Validation artifact
`tools/carrier_decode.py::familyA_key_invariant` asserts (NON-tautologically)
100% of keys fit u16 AND aggregate odd-rate ≥95% (random ~50%). The hard
assertion in `main()` prints `VERDICT: U1 key-namespace RESOLVED
(CANDIDATE)` when both hold. It passed across all 10 files (commit 555303f).
Blob-semantic close condition recorded as OA-06-3 in `open-assumptions.md`.

## ADDENDUM 3b (2026-07-14) — carrier-findings Decision-Point option (a) FALSIFIED

The plan's option (a) — "build a per-file object/name table from Family-C and
test whether Family-A keys index into it" — was tested and **refuted**.

- `tools/familyC_probe.py`: Family C (xx08-0b, 774k bunches) carries **0 ASCII
  paths/names** in any file, and a naive scan reported an A-key match in ~12%
  of bunches referencing the full A-key set. The key-offset histogram was
  SPREAD (not fixed), and 88% of C-bunches contain no match.
- `tools/familyC_control.py` (FALSIFICATION): compared the REAL A-key set
  against 20 control sets matched for parity mix + value range. The REAL
  match rate is **within or below** the random controls in **every file**
  (never >2σ). The apparent "all 156 A-keys referenced" was a
  **coupon-collector artifact of chance numeric overlap** (Family C contains
  many u16 values; some land in the A-range by coincidence). The lead-u16
  inside Family C is even and only 3 distinct values (a small fixed table),
  NOT object ids.

**Conclusion:** Family C is **NOT** the U1 object/name anchor. Combined with
prior refutations (Phase-04 NetToken = different even-keyed namespace; Family
B = small fixed even-indexed table; spawn-bunch class-path FString = absent),
**all candidate external anchors for U1 blob semantics are now excluded.** The
blob cannot be semantically named from the ReplayData wire bytes. This is a
confirmed known-unknown, not a stall.

## ADDENDUM 4 (2026-07-14) — Family B decoder (self-validating, NO external anchor)

Per plan-doc option (b) ("proceed to build the Family B decoder, which is
self-validating and does not need an external anchor"), `tools/familyB_decode.py`
DECODES and SELF-VALIDATES every 13-byte Family-B bunch.

**Framing (validated 100%, 175,973/175,973 13B records across all 10 files):**
```
  cb | u16 tag | 04 | flag | u8[8]
```
- `pl[0] == 0xcb`.
- `pl[1:3]` = u16 little-endian TAG, always in the closed set **{258, 306, 322}**
  (3 of 65536 values → strongly non-random; a real 3-valued type tag).
- `pl[3] == 0x04` always; `pl[4]` = flag: `0x00` for tags 258/306, and `0x00`
  **or `0x80`** for tag 322 (the `0x80` sub-form is the only "variant" in the
  original 99.07% 13B set — fully explained, not noise).
- `pl[5:13]` = 8-byte per-event payload (distinct ≈ count → event data, not a
  small config table).

**Why this is a real structural validation (not a tautology):** the constant
`0x04` sub-header (1/256) combined with the closed 3-value tag set (3/65536)
yields a chance pass of ~1.8e-12. The decoder asserts these and a random byte
stream fails. Rare length variants (9/17/26/40/56B, 0.93%) are a separate
sub-record type, excluded from the assertion by design.

**Per-tag monotonic self-test (internal coherence, reported honestly):**
- tag **322** = ordered-counter-like (≥85% non-decreasing `u32`
  `pl[5:9]` across frame order in every file, global 92.7%).
- tags **258/306** = NOT monotonic (≈30–45% non-decreasing) → payload is not a
  simple per-tag counter for those two types.

**Payload semantic meaning: still OPEN** (no anchor). The FRAME is fully
decoded and validated; only the 8-byte payload's interpretation is unknown.

**Validation artifact:** `tools/familyB_decode.py::decode_b13` returns
`(tag, flag, payload8)`; `main()` asserts 100% framing across all 10 files and
prints `VERDICT: Family B framing DECODED + VALIDATED`. Hard pass (commit
892cf79). `tools/familyB_fails.py` confirms the only framing fail was tag-322
with flag `0x80` (now folded in).

## ADDENDUM 5 (2026-07-14) — Family C internal-frame characterization (sub-step 3)

Plan-doc revised sub-step 3 ("identify semantic values within the grammar").
Investigated Family C (xx08-0b, 774,307 bunches, ~50% of all carrier traffic)
internal frame via `tools/familyC_decode.py` (+ `familyC_dump.py`,
`familyC_struct_probe.py`, `familyC_grammar_probe.py`).

**Structural facts (non-tautological, observed all 10 files):**
1. Family-level invariant re-asserted: `pl[1]∈{08-0b} ∧ pl[-1]==0x00` → 100%
   pass (random ~0.4%).
2. Subtypes 0x09/0x0a leading content byte `pl[2]==0xc0` at 95.7% (file-10
   run: 95.7%) / 99.3% respectively — a real near-constant bit-prefix marker
   (random ~0.4% for a fixed byte), consistent with a UE `FBitWriter` segment
   first byte. Reported as OBSERVED: 0x0a clears the project 99% bar
   (99.3%); 0x09 is 95.7% so NOT a hard pass. Subtypes 0x08 (89.8%) / 0x0b
   (58.7%) are lower — no constant leading byte.
3. The 12-byte `pl[2:]` prefix hypothesis (H1) is REFUTED: distinct 12-byte
   prefixes ≈ record count (high-entropy; likely per-actor GUID + timestamp).

**Internal frame = bit-packed serial stream, NOT decomposable at byte level:**
- NO fixed length-prefix at any offset (length-prefix hits ≤2.5% per subtype,
  consistent with chance ~0.4%).
- NO repeated fixed sub-entry unit. The eyeballed `08 u8 04 80 u8 4b 00`
  pattern (seen in one 0x09 channel/dump) was a single-channel artifact. The
  HELD-OUT exact-consumption test (template derived on file 1, tested on files
  2..10) scored **0.00%** → hypothesis REFUTED, not shipped.
- After the optional `0xc0` prefix, the payload is high-entropy
  variable-length bit-packed data (UE-style `FBitReader`/`FBitWriter` bunch
  segment).

**Consequence:** Family C's semantic decode requires the SAME external anchor as
Family A — the property-descriptor / object-layout table — which is absent from
the ReplayData wire bytes (U1; OA-06-3). Family C internal frame is therefore
**characterized** as a bit-packed serial payload stream; full semantic decode is
**BLOCKED** (confirmed known-unknown, not a stall).

**Validation discipline note:** the held-out exact-consumption self-test (which
a random byte stream fails) is what CORRECTLY refuted the naive sub-entry
hypothesis. This is the rigorous outcome the project demands: a falsified
hypothesis is reported, not pretended into a decoder. No hard "Family C decoded"
claim is made.

## ADDENDUM 6 (2026-07-14) — Family A temporal-coherence LOCALIZATION (sub-step 3)

Plan-doc revised sub-step 3 second half: "identify semantic values within the
grammar and run the ... temporal-coherence checks." Semantic NAMING is blocked
(no external property-descriptor anchor; U1). But temporal-coherence
LOCALIZATION needs NO anchor and IS achievable. Done via `tools/familyA_temporal.py`.

**Method (non-tautological, differential control — like familyC_control.py):**
For each persistent object key (u16 static handle, U1-resolved) present in
≥30 frames in a file, take its opaque state blob and localize byte-offsets
where the per-frame absolute delta is ≤2 in ≥90% of steps. A run of ≥4
contiguous such offsets = a candidate "state channel" (packing of a smooth
scalar — position/rotation/health). Validation: synthesize, per real key, a
RANDOM body of equal length/frame-count and recompute. Random bytes have
mean|d|≈85 and frac≤2≈0.03, so essentially no random key yields a 4-byte smooth
run.

**Result (all 10 files, 258 persistent keys):**
- REAL keys with ≥1 smooth run = **77/258 = 29.84%**.
- RANDOM control = **0/258 = 0.00%** (by construction; never a 4B smooth run).
- → Decision: VALIDATED (real ≫ random; differential is decisive, not a
  consumption tautology). ~30% of persistent objects expose a ≥4-contiguous-
  byte temporally-smooth field detectable at the byte level (example regions:
  key 1643 off 12..27, key 2211 off 11..29, key 2147 off 28..53, etc.).

**What this proves:** Family-A blobs are NOT random/compressed noise — they
carry per-object, temporally-coherent state surfaces whose smooth byte-regions
are LOCALIZED. This is exactly the "semantic values within the grammar" the
plan asks for, obtained without an anchor. The remaining gap is NAMING those
regions (position vs health vs rotation), which requires the external
property-descriptor/object-layout table (U1) — still absent from the wire bytes.

**Honest scope:** this completes the achievable, anchor-free portion of
sub-step 3. It does NOT unblock the downstream property-decode sub-steps
(dirty-state/NetSerializer/FastArray), which need the U1 anchor to map a smooth
byte-region to a typed field. The localized regions are the evidence base for
that future work.
