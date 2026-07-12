# Phase 01 — Static Cross-Check: Outer Container Header/Metadata

**Method:** No live debugger is available on this project (see `00-overview-and-setup.md`
Step 0.3 revised). Instead of a live-trace diff, this cross-check verifies the
header/metadata field order, widths, and version-gating **against the actual
UE5.6 engine source** that produced these files, plus the cross-file consistency
signal defined in `01-outer-container-format.md` validation #2.

## Source of truth (exact read)

`Engine/Source/Runtime/NetworkReplayStreaming/LocalFileNetworkReplayStreaming/`

- `Public/LocalFileNetworkReplayStreaming.h`
  - `FLocalFileNetworkReplayStreamer::FileMagic = 0x1CA2E27F` (cpp:83)
  - `enum class ELocalFileChunkType : uint32 { Header=0, ReplayData=1, Checkpoint=2, Event=3, Unknown=0xFFFFFFFF }`
  - `struct FLocalFileReplayCustomVersion` — `CustomVersions = 7` is the
    latest version in 5.6; the per-file `FileVersion` field is the deprecated
    version, and for `>= CustomVersions` a `FCustomVersionContainer` is
    serialized right after it.
- `Private/LocalFileNetworkReplayStreaming.cpp`
  - `ReadReplayInfo()` (the skeleton-pass reference): lines 257–567.

## Field order / width table (verified by reading source, confirmed by decode)

All little-endian. TYR files carry `FileVersion == 7 == CustomVersions`, so the
`FCustomVersionContainer` IS present and ALL version-gated optional branches
below are active.

| # | Field | Type | Source line | Width | Notes |
|---|-------|------|-------------|-------|-------|
| 1 | MagicNumber | u32 | 271 / 675 | 4 | `0x1CA2E27F` |
| 2 | FileVersion (deprecated) | u32 | 273 / 679 | 4 | `7` in TYR |
| 3 | CustomVersionContainer | int32 count + (FGuid[16] + int32 ver) per entry | 281–317 / 681–686 | 4 + 20*count | count = 1 in TYR |
| 4 | LengthInMS | int32 | 324 / 689 | 4 | replay duration ms |
| 5 | NetworkVersion | u32 | 325 / 690 | 4 | |
| 6 | Changelist | u32 | 326 / 691 | 4 | |
| 7 | FriendlyName | FString | 328–332 / 693–724 | variable | **Forced Unicode** (FixedSizeFriendlyName branch): a fixed 256-char (UTF-16LE) buffer, i.e. `int32 Len = -256` then 512 bytes. |
| 8 | IsLive | u32 (bool) | 354–357 | 4 | **NOT version-gated** — always serialized, immediately after FriendlyName. |
| 9 | Timestamp | FDateTime (int64 ticks) | 359–362 | 8 | gated `>= RecordingTimestamp (3)` → present |
| 10 | bCompressed | u32 (bool) | 364–370 | 4 | gated `>= CompressionSupport (2)` → present |
| 11 | bEncrypted | u32 (bool) | 372–377 | 4 | gated `>= EncryptionSupport (6)` → present |
| 12 | EncryptionKey | TArray<uint8> | 372–396 / 744–761 | 4 + N | always written inside the EncryptionSupport branch; N = 0 when unencrypted |

**Chunk table** (rest of file, `while (!AtEnd())`): `ELocalFileChunkType` u32
(line 412–413) + `SizeInBytes` int32 (line 419) + payload. Chunk header widths
confirmed `u32`/`int32` (NOT u64) from `FLocalFileChunkInfo` (header:83) and
`ReadReplayInfo` (line 419).

## Key findings / discrepancies resolved

1. **`IsLive` ordering pitfall.** The phase-01 doc sketch implies
   `FriendlyName → [gated fields]`. In fact `IsLive` is read **before** the
   version-gated `Timestamp/Compressed/Encrypted` block (source 354–357, between
   FriendlyName and the `RecordingTimestamp` check). Skipping it misaligns every
   subsequent field by 4 bytes and produces garbage chunk sizes. The parser reads
   `IsLive` unconditionally. **This is the one place the original doc's naive
   outline was wrong and source-reading corrected it.**

2. **`FileVersion` is not the gating key.** `7` is read as the deprecated field,
   then a `FCustomVersionContainer` (count=1, the `LocalFileReplay` GUID
   `3ef0a495-e449-0b7e-56d343bad987ff94`, version `7`) is serialized. The gating
   version equals that same number here, so all optional branches are on.

3. **`SizeInBytes` is `int32`, not `u32`/`u64`.** Confirmed from
   `FLocalFileChunkInfo::SizeInBytes` (header:83) and `ReadReplayInfo` line 419.
   The doc's "u32 or u64 — confirm width" pitfall is resolved: it is `int32`.

4. **FriendlyName encoding.** The `FriendlyNameCharEncoding` branch
   (`>= 5`) plus `FixedSizeFriendlyName` (`>= 1`) means the name is a fixed-size
   256-UTF16LE-char buffer written as Unicode. TYR's replay names are empty
   (all spaces + NUL), 512 bytes. Decoding as `int32 Len = -256` then 512
   UTF-16LE bytes matches exactly and lands cleanly on the next field.

## Cross-file consistency signal (validation #2 substitute for live diff)

All 10 sample files agree on:
- `FileVersion == 7`, `NetworkVersion == 337258096`, `Changelist == 31351`.
- Exactly one `Header` chunk, always first.
- `bCompressed == false`, `bEncrypted == false`, `EncryptionKey` length `0`.
- Skeleton walk lands **exactly on EOF** (zero remainder) for every file.
- Chunk sequence is the expected `Header, then alternating ReplayData/Checkpoint`
  cadence; checkpoint spacing is roughly time-driven (~30–60 s equivalent),
  consistent with a shared `ReplayCheckpointInterval`.

These agreements across 10 independent files from the same build are the
strongest available static signal that the field layout is correct, in place of
a live trace.

## Remaining unknowns (do not over-claim)

- The exact `FCustomVersionContainer::Serialize` inner format (count encoding /
  GUID byte order) was not re-read from `Core` source, but the observed layout
  (int32 count, then 16-byte GUID + int32 version) decodes consistently and the
  subsequent fields land correctly — treated as **PROBABLE**, not load-bearing
  beyond "it aligns."
- FriendlyName content is empty in all samples; the fixed-buffer decode is
  confirmed structurally but not by meaningful text.
