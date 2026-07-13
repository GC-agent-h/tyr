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
