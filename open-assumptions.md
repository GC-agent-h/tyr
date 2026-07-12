# Open Assumptions — Known Residual Uncertainties

This tracker records places where a result is validated by *indirect* evidence
(empirical byte-exact consumption, round-trip, or static reasoning) rather than
by reading the authoritative engine source operator<< directly, because either
(a) no live-debugger ground-truth is available, or (b) the relevant source file
is absent from the curated `/UE` subset. Each entry is a TRUE KNOWN-UNKNOWN, not
a confirmed fact. Items are closed when direct source evidence is obtained.

Per README rule: "record any resulting uncertainty in an `open-assumptions.md`
tracker rather than silently treating it as confirmed."

---

## Phase 03 — Bit-Level Primitives

### OA-03-1 — FString::Serialize operator not source-read
- **What:** The UE5.6 `FString` archive `operator<<` (the int32-length scheme:
  0 = empty, positive = ANSI incl. null terminator, negative = UTF-16 code units)
  was **not** read from engine source — the operator is absent from the curated
  `/UE` subset (only BitReader/BitWriter/Archive/CoreNet/NetworkGuid/UnrealNames
  are present).
- **What validates it instead:** `tools/header.py` (Phase 02) achieves
  **byte-exact consumption** of the full `FNetworkDemoHeader` across all 10
  samples using this scheme, and `tools/revalidate_phase1_2.py` re-decodes those
  same FString fields through the Phase-03 `BitReader.read_fstring` and matches
  `header.py` on every file. Strong empirical confirmation, but not a direct
  source read.
- **Risk:** The negative-length = UTF-16 convention is known to have changed in
  some UE5 builds; if TYR used a different encoding, Phase-02 byte-exact would
  already have failed (it did not). Confidence: high-but-indirect (PROBABLE).
- **Close condition:** obtain `UE/Containers/UnrealString.cpp` (or
  `FString::Serialize`) from the 5.6 source and confirm the sign convention
  line by line.

### OA-03-2 — Network FName hardcoded-index version gating
- **What:** `UPackageMap::StaticSerializeName` (CoreNet.cpp:306) uses
  `SerializeInt` for the hardcoded name index when
  `EngineNetVer < FEngineNetworkCustomVersion::ChannelNames`, else
  `SerializeIntPacked`. We assume TYR is at `HISTORY_USE_CUSTOM_VERSION=19`
  (observed in ReplayTypes.h header), which is >= ChannelNames, so
  `SerializeIntPacked` is used.
- **What validates it:** the header-derived version is 19 and the
  hardcoded-index path uses `SerializeIntPacked` in the writer (CoreNet.cpp:354)
  unconditionally on the save side; the load-side branching is symmetric. We have
  not yet observed an actual on-wire FName in a replay to confirm the branch
  taken at runtime.
- **Close condition:** decode a real FName in a Phase-05/06 bunch and confirm
  the bit reads as 1 (hardcoded) followed by a packed index (or 0 + FString).

---

## Caveat on the Phase-00 scaffold

The Phase-00 `tools/bitreader.py` `read_bit` was **MSB-first**, which is
incorrect for UE5.6 (source: BitReader.cpp:136). This was corrected to LSB-first
in Phase 03. Any tool written between Phase 00 and Phase 03 that relied on the
scaffold's `read_bit`/`read_bits` for multi-bit values (other than the already
byte-exact Phase 01/02 `struct.unpack` paths) must be re-checked. Phase 01/02
used `struct.unpack` (byte-aligned), so they are unaffected; the correction only
matters for future bit-level work, which is exactly why Phase 03 was validated
in isolation first.
