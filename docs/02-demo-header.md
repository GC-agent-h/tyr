# Phase 2 — Demo Header Chunk

## Goal

Fully decode the `Header` chunk identified in Phase 1 into a structured `FNetworkDemoHeader`-equivalent object, including engine/game network version fields, feature flags, level names, and any game-specific custom data blob TYR injects.

## Source of truth

- `Engine/Source/Runtime/Engine/Classes/Engine/DemoNetDriver.h` — look for `struct FNetworkDemoHeader` (name may be slightly different in 5.6, e.g. it may have moved into `ReplayHelper.h`) and the associated `EReplayHeaderFlags` enum.
- `Engine/Source/Runtime/Engine/Private/ReplayHelper.cpp` — the actual serialization function (search for `operator<<` overload for the header struct, or a `ReadDemoHeader`/`WriteDemoHeader` free function/method).
- `Engine/Source/Runtime/Engine/Classes/Engine/DemoNetDriver.h` — `EReplayVersionHistory` enum, which each header field's presence is gated on.

## Structure to implement

The header typically includes, in order (**confirm exact order and gating against your 5.6 source — do not assume this list is complete or in the right order**):

1. **Network checksum / magic recheck** — some versions re-validate a magic value at this level too.
2. **Network version** (`FNetworkVersion`-derived value) and **replay version** (`EReplayVersionHistory` current value at record time) — this second value is what all your version-gated `if` branches for the rest of this phase (and later phases) should key off, not the outer file version from Phase 1, which is a different field with a different purpose (they are related but not always identical).
3. **Feature flags bitmask** (`EReplayHeaderFlags`) — a packed set of booleans such as:
   - Whether delta checkpoints are used (`HasDeltaCheckpoints` or similar) — **this flag controls Phase 8's decoding strategy**, flag it prominently.
   - Whether the replay uses "game-specific frame data."
   - Whether streaming chunk indices are present.
   - Possibly a flag indicating whether checksums are embedded per-packet for replay integrity verification (useful to you as a validation tool if present — see below).
4. **Minor/major/persistent level names** — `FString`s naming the map(s) loaded, useful for immediate human-readable sanity checking.
5. **Game-specific header data** — if the game overrides `AGameStateBase::GetGameSpecificDemoHeader` or `UGameInstance`-level hooks (searchable in the SDK: look for any project-specific class derived from `AGameStateBase`, `AGameModeBase`, or `UGameInstance` that has a function overriding a demo/replay-header hook — Dumper-7 will show you overridden virtual functions if the SDK captured them, or at minimum will show you the class hierarchy so you know what to look for in the disassembly). This is the one part of the header that is **not** documented by base engine source — you need to identify it via the SDK's class list (does TYR have a custom `AGameStateBase` subclass with an obviously-named function?) and static disassembly of the write path (locate where the base header write finishes and check statically whether additional bytes are written by a virtual call before the header chunk closes — no live debugging is available on this project, see `00-overview-and-setup.md` Step 0.3 revised).

## Implementation approach

1. Decode fields strictly in the order the source function writes/reads them — resist the temptation to reorder for "logical grouping," since serialization order must match exactly.
2. For every field gated by `if (Header.Version >= X)`, implement the identical guard using the replay-version value you read in step 2 above, not the outer container version from Phase 1.
3. When you reach the game-specific data blob:
   - First, try treating it as **zero bytes** (i.e., assume TYR does not override this hook). If your subsequent chunk-boundary parity check (see below) still holds, you're likely correct that there's no custom blob, or it's empty in practice even if the hook exists.
   - If there's leftover unparsed data before the chunk's declared size runs out, that's your game-specific blob — its size should be implicitly determined by "whatever bytes remain in this chunk after the standard fields," since custom data typically doesn't self-declare its own length header (though some games do prefix it with a size — check by testing both hypotheses against the leftover byte count across all 10 files: if leftover byte count varies between files in a way consistent with a plausible custom struct, that supports the no-self-length hypothesis; if the first 4 bytes of the leftover region look like a plausible small integer matching the remaining byte count, that supports a self-length-prefixed blob).

## Validation

1. **Full-chunk consumption**: after decoding every documented field, the number of bytes consumed should exactly equal the `Header` chunk's declared size from Phase 1 (accounting for any custom trailing blob). Any mismatch here means a field width, string encoding, or gating condition is wrong — **do not proceed until this is exact**, since even a single misread byte here corrupts alignment for the entire rest of the file (the header is not independently framed at the bit level beyond the chunk boundary, so downstream chunks are only safely skippable via Phase 1's chunk-size mechanism, but *within* this chunk, exactness matters for actually using the data).
2. **Human plausibility check**: level names should be real, recognizable map names from TYR (cross-reference against the SDK's world/level asset references if visible, or against known map names from the game). Network/engine version numbers should match across all 10 files (same build).
3. **Feature flag cross-check**: for each flag you decode, try to find corroborating evidence elsewhere:
   - If "delta checkpoints" flag is set, Phase 8 checkpoints should reference a previous checkpoint ID rather than being self-contained — verify this once you get to Phase 8, and retroactively confirm the flag was decoded correctly.
   - If a "per-packet checksum" flag exists and is set, you gain a powerful validation tool for Phases 5–7: you can verify your bit-reader alignment mid-stream by checking these embedded checksums, rather than only being able to tell alignment is broken by a catastrophic later failure.
4. **Static cross-check (no live debugging available)**: per Step 0.3 (revised) in `00-overview-and-setup.md`, no live session exists to breakpoint and diff. For resolving the game-specific blob question in particular — where the doc's leftover-bytes inference is the primary method — supplement it with static disassembly of the `GetGameSpecificDemoHeader`-equivalent hook (if TYR's `AGameStateBase` subclass overrides it, per the SDK's class hierarchy) rather than treating the byte-count hypothesis test alone as conclusive. Document whichever conclusion you land on as an explicit open assumption if disassembly alone can't fully confirm it.
5. **Cross-file diffing**: since you have 10 files from the same build, write a quick diff tool that shows you exactly which header fields vary between files (level name, duration, timestamp) versus which are constant (version numbers, flags). Anything that's constant across all 10 but that you *expected* to vary (or vice versa) is a signal worth investigating before moving on.

## Deliverables checklist

- [ ] All standard header fields decoded in correct source order with correct version gating.
- [ ] Byte-exact consumption of the Header chunk for all 10 files (including any game-specific blob).
- [ ] Level names and version numbers pass a human plausibility check.
- [ ] Feature flags identified and cross-referenced against Phase 8 behavior (revisit after implementing Phase 8).
- [ ] At least one static cross-check (no live debugging available) resolving the game-specific blob question, per Step 0.3 (revised).

## Suggested commit breakdown

1. `feat(phase02): parse standard demo header fields with version gating` — the bulk of the documented fields (network/replay version, level names), with explicit version-guard `if` branches matching source.
2. `feat(phase02): implement feature flag bitmask decoding` — split out separately since this is a distinct, self-contained concern (`EReplayHeaderFlags`) and you'll want to revisit/annotate this commit specifically once Phase 8 confirms which flags actually correspond to observed behavior.
3. `feat(phase02): detect and parse game-specific header blob (if present)` — the leftover-bytes hypothesis testing described above; commit whichever hypothesis (zero-length, self-length-prefixed, or a specific known struct once reversed) you land on, with a comment explaining the evidence.
4. `test(phase02): byte-exact chunk consumption assertion across samples` — hard automated check that the Header chunk is fully consumed for all 10 files.
5. `docs(phase02): static cross-check of header fields incl. custom blob` — no live debugging is available on this project; commit disassembly notes and the leftover-bytes hypothesis evidence instead, keeping it separate so it's easy to find later.
6. `docs(phase02): note feature-flag cross-reference to revisit after phase08` — a short TODO-style commit marking which flags need retroactive confirmation once Phase 8 is implemented; update/close this out when you get there rather than letting it silently rot.

Proceed to `03-bit-level-primitives.md`.
