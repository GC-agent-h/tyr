# Phase 1 — Outer Container Format

## Goal

Be able to walk any `.replay` file from start to end, correctly identifying every top-level chunk, its type, and its byte length — without yet interpreting the contents of those chunks. This is your "skeleton pass": if you can't reliably do this, nothing downstream will work, because every later phase depends on correct chunk boundaries.

## Source of truth

`Engine/Plugins/Runtime/NetworkReplayStreaming/LocalFileNetworkReplayStreaming/Source/LocalFileNetworkReplayStreaming/Private/LocalFileNetworkReplayStreaming.cpp`

This is the streamer implementation UE uses when replays are saved as local files (as opposed to a backend replay service). Since you have standalone `.replay` files, this is almost certainly the code path that produced them. Read the functions named roughly:

- `FLocalFileNetworkReplayStreamer::WriteHeader_Internal` / `ReadHeader`
- `FLocalFileNetworkReplayStreamer::FlushStream` and chunk-writing helpers
- The `FLocalFileReplayInfo` / `FLocalFileEventInfo` / `FLocalFileChunkInfo` struct definitions in the corresponding header (`LocalFileNetworkReplayStreaming.h`)

## Structure to implement

### 1. Top-level magic and version

The file begins with a fixed magic number (an integer constant, check `NETWORK_DEMO_MAGIC` — the exact value is defined in `Engine/Source/Runtime/Engine/Public/NetworkReplayStreaming.h` or `DemoNetDriver.h` depending on engine version) followed by a file version enum/int. This version number is what gates almost every "optional field present or not" decision later — treat it as load-bearing, not cosmetic.

**Implementation approach:**
```
u32 magic = read_u32()
assert magic == NETWORK_DEMO_MAGIC   # confirm against source constant
u32 file_version = read_u32()
```
Print this for all 10 sample files immediately. They should all match (same build), which is your first sanity check.

### 2. Top-level metadata block

Following the magic/version, `LocalFileNetworkReplayStreaming.cpp` writes a metadata struct roughly equivalent to:

- Length in milliseconds (total replay duration)
- Network version (checksum-like value derived from the game's network compatibility settings — compare against what you'd expect from the executable's `GetLocalNetworkVersion`-equivalent function if you can locate it)
- Changelist number
- Friendly name (an `FString` — length-prefixed string, see Phase 3 for exact string encoding)
- Timestamp (`FDateTime` or similar — check exact serialization in source, usually ticks as int64)
- Boolean flags: `bIsLive`, `bCompressed`, `bEncrypted` (and possibly `bDeltaCheckpoints`, `bHasStrictOrdering`, depending on version — check the version-gated fields carefully, since adding a new bool per version is common practice in this file across UE releases)

**Since you're not using compression/encryption**, confirm those two flags are false, but do not skip reading them — they still occupy their designated bytes/fields in the header regardless of value, and misreading a bool as absent will misalign every byte that follows.

### 3. Chunk table

The rest of the file is a sequence of chunks. Each chunk entry generally has this shape (verify exact field order/types against source, as this varies slightly by version):

```
u32 chunk_type      # ELocalFileChunkType: Header, Checkpoint, Event, ReplayData, (possibly Metadata in newer versions)
u32 or u64 chunk_size  # size in bytes of the chunk's payload, NOT including this size field itself
<chunk_size bytes of payload, meaning depends on chunk_type>
```

`ELocalFileChunkType` values to expect (check `LocalFileNetworkReplayStreaming.h` for the exact enum in 5.6):

- `Header` — contains the demo header (Phase 2)
- `ReplayData` — contains the actual frame-by-frame network stream (bunches/packets — Phases 5–7)
- `Checkpoint` — full/delta snapshot for scrubbing (Phase 8)
- `Event` — out-of-band events (e.g., custom game-defined bookmarks, kill-cam markers — check if TYR uses `AddEvent`/`AddOrUpdateEvent` calls in its game code, visible in the SDK if the game class overrides replay event recording)

### 4. Implementation: the "skip and count" skeleton pass

Before decoding chunk contents, write a parser that does only this:

```
while not at EOF:
    chunk_type = read_u32()
    chunk_size = read_u32()  # or u64, confirm width from source
    record(chunk_type, chunk_size, current_offset)
    seek(current_offset + chunk_size)
assert final_offset == file_size
```

Run this over all 10 sample files. For each, print a table: chunk index, type, offset, size. This alone tells you a great deal:

- Does the chunk sequence look sane (e.g., one Header chunk, then alternating Checkpoint/ReplayData/Event chunks)?
- Do chunk sizes sum exactly to file size, with zero leftover bytes? If not, your field widths (u32 vs u64) or struct layout assumption is wrong somewhere upstream.
- Are checkpoint chunks roughly evenly spaced in file offset (they usually are, based on a time interval, e.g., every N seconds) — this is a strong positive signal your chunk boundaries are correct, since checkpoint cadence is typically time-driven and should look consistent across the 10 files if they share the same `ReplayCheckpointInterval` setting.

## Common pitfalls

- **Field width ambiguity**: some fields changed from `int32` to `int64` across UE versions (notably file sizes, to support very long replays). If your byte-count sanity check fails, this is the first thing to suspect — try re-parsing with 64-bit chunk sizes.
- **Endianness**: UE serialization is little-endian on all relevant platforms; not usually an issue, but sanity-check with a known field (e.g., magic number in hex) if something looks byte-swapped.
- **Version-gated optional fields**: don't assume the struct layout in the current-HEAD source matches 5.6 exactly — cross check against the specific 5.6 tag/branch of the engine source you were given, not a mental model of "how UE replay headers generally look." Search for version guards like `if (FileVersion >= ...)` around each field.

## Validation

1. **Byte-exact EOF landing**: the skeleton pass above must land exactly on EOF for all 10 files with zero remainder. This is a hard, binary pass/fail signal — if even one file fails, do not proceed to Phase 2 until fixed.
2. **Cross-file consistency**: file version, network version, and changelist should be identical across all 10 files (same build). If they differ, you've likely misread a field (or the files genuinely come from different builds — re-confirm the premise).
3. **Metadata plausibility**: `LengthInMS` should roughly match file size divided by expected bitrate, and should be a plausible replay duration (not a garbage huge number, not zero, unless a file is intentionally an empty/aborted recording).
4. **Static cross-check (no live debugging available on this project)**: instead of a live diff, statically disassemble `WriteHeader_Internal`/`ReadHeader` (Ghidra/IDA) and confirm field order/widths match your source reading, per Step 0.3 (revised) in `00-overview-and-setup.md`. Combine with the cross-file consistency check above (item 2) — agreement across all 10 files on version/changelist fields is your strongest available signal here in place of a live trace.

## Deliverables checklist

- [ ] Parser reads magic + version and asserts correctness across all 10 files.
- [ ] Parser reads top-level metadata block completely (including confirming `bCompressed`/`bEncrypted` are false).
- [ ] Parser walks the full chunk table for all 10 files, landing exactly on EOF.
- [ ] A printed chunk-table report per file, manually eyeballed for plausibility.
- [ ] At least one field-by-field static cross-check (disassembly reading, no live debugging available) documented per Step 0.3 (revised).

## Suggested commit breakdown

1. `feat(phase01): parse magic number and file version` — smallest possible first commit; just enough to assert the magic and print the version across all 10 files.
2. `feat(phase01): parse top-level metadata block` — length, network version, changelist, friendly name, timestamp, and the compressed/encrypted flags.
3. `feat(phase01): implement chunk table skeleton walker with EOF assertion` — the skip-and-count loop; this is the commit that should include the hard "lands exactly on EOF" assertion as an automated test, not just a manual check.
4. `test(phase01): cross-file consistency report across 10 samples` — the script that prints/asserts file version, network version, and changelist match across all 10 files.
5. `docs(phase01): static cross-check of header/metadata fields` — since no live debugging is available on this project (see `00-overview-and-setup.md` Step 0.3 revised), commit your disassembly-based notes confirming field order/widths instead of a live-trace diff.

Keep commit 3 separate from 1–2: it's the one with the hard pass/fail EOF invariant, and you want that in its own commit so that if a later change ever breaks EOF-landing, `git bisect` points you straight at the chunk-walking logic rather than a mix of unrelated changes.

Proceed to `02-demo-header.md`.
