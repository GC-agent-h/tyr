# Phase 08 — Static Cross-Check of a Checkpoint Save/Load Path

> Per README step 0.3 (revised): no live-debugging ground truth is available on
> this project. This document substitutes the static/redundant-decode-path
> methodology — we trace the engine's authoritative `LoadCheckpoint`/`WriteDemoFrame`
> read order against real checkpoint chunk bytes, and let a source-faithful decoder
> attempt the parse. Where the source-faithful decoder desynchronizes, that is
> itself strong evidence about TYR's actual wire format.

## Source of truth (read, not assumed)

- `UE/DemoNetDriver.cpp:4013` `UDemoNetDriver::LoadCheckpoint`
  - `:4029` `const bool bDeltaCheckpoint = HasDeltaCheckpoints();`
  - `:4040-4047` (HasLevelStreamingFixes branch): reads `FArchivePos PacketOffset` context
    — `*GotoCheckpointArchive << PacketOffset;` (a `u64`/`FArchivePos`).
  - `:4059-4061` (TotalSize>0): `*GotoCheckpointArchive << LevelForCheckpoint;` (i32).
  - Then the demo-frame body is replayed via `ReplayHelper::ReadDemoFrame`.
- `UE/ReplayHelper.cpp:1331` `FReplayHelper::WriteDemoFrame` (the save-side twin):
  - `:1337` `Ar << CurrentLevelIndex;` (i32)
  - `:1340` `Ar << FrameTime;` (f32)
  - `:1342` `Cast<UPackageMapClient>(...)->AppendExportData(Ar);`
  - `:1344-1355` (HasLevelStreamingFixes): `SerializeIntPacked(NumLevelsAddedThisFrame)` + per-level `FString LevelName`.
  - `:1380-1385` `SaveExternalData` (scoped offset).
  - `:1400-1409` packet loop: `SerializeIntPacked(SeenLevelIndex)` + `WritePacket` (`<< Count; Serialize(Data,Count)`).
  - `:1413-1421` trailing `SerializeIntPacked(EndCountUnsigned)` + `int32 EndCount = 0`.
- `UE/ReplayHelper.cpp:574` `SaveCheckpoint`: confirms `bDeltaCheckpoint` fork at `:598`
  and the actor-collection logic; the actual serialization is delegated to
  `WriteDemoFrame` (`SaveCheckpoint` → `TickCheckpoint` → `WriteDemoFrame` at `:1045`).

**Pristine UE5.6 read order (HasLevelStreamingFixes=true, full checkpoint):**
`[3 FStrings: Id/Group/Metadata] [u64 PacketOffset] [i32 LevelForCheckpoint]
 [i32 CurrentLevelIndex] [f32 TimeSeconds] [AppendExportData] [streaming levels]
 [external data] [packet loop] [trailing counts]`

## Empirical observation on TYR checkpoint bytes

Probe (`sample/TyrReplay1.replay`, checkpoint 0; chunk `size_in_bytes = 75798`):

```
header FStrings: ('checkpoint0', 'checkpoint', '2')   # ends at offset 37
offset after 3 FStrings = 37
next 40 bytes (hex):
  30750000 30750000 e5270100 00000000 00000000 af010000 120001e2 ffffff2f 00540079 0072004d
```

- Bytes `30 75 00 00` at offset 37 interpreted as the UE5.6 `u64 PacketOffset`
  = `0x00007530_00007530` = **128849018910000** (garbage — not a sane archive position).
- The first export-list head FString `/TyrMap…` actually begins at **offset 68**
  (UTF-16 `2f 00 54 00 79 00 72 00 4d` = "/TyrM…", i32 len `-30` at offset 64).
- Therefore the offset from the end of the 3 FStrings to the export-list head is
  **68 − 37 = 31 bytes** (or 25 bytes of prefix *before* the 6-byte head-prefix the
  committed reader assumes at `68−6 = 62`). Either way it is **not 12 bytes**
  (the UE5.6 `u64+i32` envelope size).

## Decoder outcomes (the decisive cross-check)

1. **Source-faithful UE5.6 envelope decoder** (the `tools/checkpoint_full.py`
   rewrite, preserved at `/tmp/checkpoint_full_broken_rewrite.py`):
   - Reads `3 FStrings` then `u64 PacketOffset` + `i32` + `i32`, then proceeds into
     the GUID-cache / export walk.
   - **Result: 0/94 checkpoints parse. Every checkpoint throws
     `read_bytes(<1–4 MB>) past end`** because the `u64` field is garbage and the
     decoder desynchronizes immediately, eventually reading a multi-megabyte
     FString length.
   - This is an *empirical refutation* (not a speculation) that TYR's checkpoint
     body does **not** follow the pristine UE5.6 `LoadCheckpoint` envelope.

2. **Content-anchored structural decoder** (`tools/checkpoint_full.py` @ `55a0e56`,
   committed/validated):
   - Does **not** assume the UE5.6 envelope. After the 3 FStrings it scans for the
     first `/TyrMap`-like FString (content anchor) and treats that as the
     export-list head; walks export list + object list by FString anchoring;
     declares everything after the last object FString as the trailing Iris block.
   - Produces **consistent, plausible** object counts (707–1548 per checkpoint)
     across all 94 checkpoints, and the trailing block is FString-free in all 94.
   - **But its `VERDICT: VALIDATED` overclaims "byte-exact":** no gate in
     `decode_full_checkpoint` asserts consumption to chunk `TotalSize`. The
     25-byte prefix region (offset 37..61) is **silently dropped** (not in the
     export list, not in the object list, not in the trailing block), and the
     partition is *definitional* (trailing = remainder). G1 (header FStrings) +
     G3 (0 FStrings in trailing) are real gates, but "full byte-exact consumption
     to `TotalSize`" is **not** established.

## Conclusion

- **TYR's checkpoint format is CUSTOM** — it deviates from the pristine UE5.6
  `LoadCheckpoint` envelope in the region immediately after the streamer FStrings
  (a ~25-byte unmodeled prefix; the UE5.6 `u64 PacketOffset + i32 LevelForCheckpoint`
  framing does not parse). The source-faithful decoder's 94/94 desync is the proof.
- **Full-checkpoint decode status = STRUCTURALLY validated, NOT byte-exact to
  `TotalSize`.** The committed decoder is a sound *structural* anchor (consistent
  object counts, FString-free trailing partition), but the prefix region and the
  trailing Iris state block remain unmodeled. The PROGRESS claim
  "full-checkpoint decoding validated in isolation (94/94 byte-exact)" must be read
  as *structurally* validated; the word "byte-exact" is retracted (see
  open-assumptions OA-08-1 amendment).
- **Delta mode**: ruled out (Phase 2 header flag `HasDeltaCheckpoints` not set;
  all 94 checkpoints are self-contained full snapshots). Delta-application logic
  (detailed item 4) is therefore **N/A** per the phase doc clause "only if delta
  mode is confirmed active."
- **Stream-replay cross-validation** (detailed item 5) remains **blocked** by the
  same anchor that blocks Phase 06 — U1 (OA-06-3): the trailing Iris state block
  cannot be turned into named property values without the TYR class layout /
  handle→class export table, which is not present in the replay wire bytes.
- **Trailing Iris state block**: structurally partitioned but semantically
  un-decoded — OA-08-1 (env-blocked, parallel to U1).

## What would close the remaining gap

Same as OA-06-3: a handle→class mapping bridgeable to the wire namespaces, or the
TYR carrier/checkpoint-state serializer reversed from the TYR binary (env-blocked:
`/dumper-7` holds only SDK headers). Until then, Phase 08 output is trustworthy as
a *structural index* (object counts, export-list presence, timestamp, trailing
block boundaries) but not as *named property state*.
