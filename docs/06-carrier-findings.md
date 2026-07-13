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
