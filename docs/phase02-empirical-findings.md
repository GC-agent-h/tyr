# Phase 02 — Demo Header: empirical findings (work-in-progress)

Status: STRUCTURE MAPPED, SEMANTICS BLOCKED on missing engine source.
Last updated: 2026-07-12.

## What was done

All 10 sample `.replay` files were parsed via `tools/container.py` (Phase 01),
the `Header` chunk (type 0) extracted, and byte-level diffing performed across
files (`tools/diff_header.py`, `tools/diff_header_tail.py`,
`tools/explore_header.py`).

### Observation 1 — constant prefix
Bytes `[0x00, 0x54)` (84 bytes) are **byte-identical across all 10 files**.
Same engine build ⇒ same defaulted/version fields. This is the portion
containing (in unknown order) the network versions, replay header version,
header flags, and any other per-build constant data.

```
hex: 3da1f52c 13000000 03000000 a35c9162
     f74b8e1c c7120ea3 f79d21c8 2a000000
     240d40cc 7b4ee9e0 83a2f99b 27c0c0dc
     00000000 8a991784 ec43c0bb 19d1b381
     22272d07 13000000 5083520b 2a000000
     00000000
```
- `3d a1 f5 2c` at offset 0 — magic recheck cookie (4 bytes, constant).
- `13 00 00 00` at offset 4 — u32 = 19.
- `03 00 00 00` at offset 8 — u32 = 3 (candidate `EReplayVersionHistory`
  current value, since the doc says the replay header version is the key
  gating value for later phases; value 3 = a recent 5.x revision).
- Outer-container `network_version` (Phase 01) = 337258096, `changelist` = 31351.

### Observation 2 — per-file GUID
Bytes `[0x54, 0x64)` (16 bytes) vary per file and look GUID-shaped.
In `FReplayHelper::WriteNetworkDemoHeader` the header sets
`DemoHeader.Guid = FGuid::NewGuid();` — strong candidate for an FGuid field
at this offset. (Note: the 16 constant bytes at `[0x10,0x20)` are NOT the
guid, because a per-file guid would differ there; they are something else
constant — see open question Q1.)

### Observation 3 — constant mid-block with game/engine strings
Bytes `[0x64, 0x8c)` (40 bytes) constant; contains ASCII `++Tyr+release`
at chunk offset `0x7C` (12 chars). Preceding it (0x64..0x7C) are binary
constant fields (candidate: small ints `05 00 06 00`, `00 00 00 77 7a 00 80 0e 00`
— possibly enum/version pairs). This is the game name string (Tyr, release
config) — likely written by the game-specific header path or a
`Platform`/`BuildConfig` pair.

### Observation 4 — variable tail
From `0x8c` to end varies:
- int32 level_count (==1 in all observed samples; multi-level would grow
  the chunk — confirmed by TyrReplay2/3 being +8 bytes, matching a longer
  map-path string).
- Per entry: FString name (length includes null terminator, e.g. 30 =
  "/TyrMapRavine/Maps/Map_Ravine" 29 chars + NUL) + int32 LevelChangeTimeInMS
  (0 on the only/first level).
- Then a constant trailing span of 18 bytes:
  `01 00 00 00 00 00 00 00 00 00 00 00 00 00 f0 41 00 00 80 bf 00 00 80 bf`
  i.e. i32=1, 8 zero bytes, then three little-endian floats
  `30.0` (0x41f00000), `-1.0` (0xbf800000), `-1.0` (0xbf800000).
  SEMANTICS UNKNOWN — possibly a stream-index count + default vector/rotation.
- Then an FString platform name: `WindowsClient`.
- Then a 2-byte trailer `04 03` (candidate BuildConfig + BuildTarget enum
  pair — UNCONFIRMED).

Sizes: 8 files = 226 bytes; 2 files (TyrReplay2,3) = 234 bytes — the +8
corresponds to those files carrying a longer level-name string, confirming
the level list is the variable-length region and everything from the
trailing span onward is constant per file length.

### CORRECTED layout (supersedes earlier 0x90 framing)
```
[0x00,0x54) const prefix : 84 bytes, identical all files (versions/flags).
[0x54,0x64) guid         : 16 bytes, per-file (FGuid candidate).
[0x64,0x8c) mid const    : 40 bytes, identical all files, "++Tyr+release".
[0x8c,   ..) level list  : i32 count + {FString name, i32 time_ms}*.
[ level_end, ..) unknown : 18 bytes constant (i32=1 + 3 floats).
[ .. , -2)   platform    : FString "WindowsClient".
[ -2 , end)  trailer     : 2 bytes 04 03.
```
The parser `tools/header.py` achieves byte-exact consumption of all 10
files under this layout (validations V1/V2/V3). Semantic naming of the
const prefix, the mid block, and the 18-byte trailing span is DEFERRED
until the engine struct definition is available.

## Remaining unknowns (require source)

- **Q1:** Semantic identity of the 84-byte constant prefix. Which u32 is
  EngineNetworkVersion, which is GameNetworkVersion, which is
  EReplayVersionHistory, which is HeaderFlags (EReplayHeaderFlags)? And what
  are the other constant int32s (e.g. the pair `13 000000`/`13000000` at +4/+0x67,
  the `00000000` at +0x30, the `5083520b` / `2a000000` values, etc.)?
- **Q2:** Exact `EReplayHeaderFlags` bit values (to decode toggles like
  DeltaCheckpoints which drives Phase 8).
- **Q3:** Meaning of trailing `00 04 03` (could be BuildConfig + BuildTarget
  enum pair, or array terminator + two version ints — needs struct def).
- **Q4:** Confirm `++Tyr+release` is the FString game name and not
  game-specific-data blob content.

## Blocker

The provided `/UE` subset (22 files) does NOT contain
`struct FNetworkDemoHeader`, its `Serialize`/`operator<<` body, or the
`EReplayHeaderFlags` / `EReplayVersionHistory` enum definitions (those live
in `Engine/.../DemoNetDriver.h` / `ReplayHelper.h`, which were not included).
No engine tree on disk contains them either (verified via find/grep).

→ Needs `Engine/Source/Runtime/Engine/Classes/Engine/DemoNetDriver.h`
  (FNetworkDemoHeader + EReplayHeaderFlags + EReplayVersionHistory) and the
  `FNetworkDemoHeader::Serialize` implementation to assign semantics.
