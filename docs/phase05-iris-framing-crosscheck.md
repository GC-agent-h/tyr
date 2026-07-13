# Phase 05 — Iris data-stream framing: static cross-check vs legacy FInBunch assumption

Per `docs/05-bunches-and-channels.md` Step 0.3 (revised) and the phase's
required insert-commit, this note documents the static cross-check that confirms
(or corrects) whether the legacy `FInBunch` header layout actually holds under
TYR's Iris build. No live debugging is available; evidence is source reading +
bit-exact consumption across all 10 samples (the parser in `tools/frame_walk.py`).

## Question
Does the replay playback path feed `UNetConnection::ReceivedPacket` bunches that
use the legacy `FInBunch` header layout, or does Iris (`FNetBlob` / `DataStream`)
replace the per-actor bunch framing with something else inside `ReplayData`
packets? If Iris replaced it, my `read_bunch` (which mirrors
`NetConnection.cpp::ReceivedPacket`) would be wrong.

## Source evidence

### 1. Replay connection is InternalAck → packet header is SKIPPED
- `DemoNetDriver.cpp:4844` and `:4856` call `SetInternalAck(true)` for the
  playback connection.
- `UNetConnection::ReceivedPacket` (`NetConnection.cpp:3247`) reads the
  `FNetPacketNotify::FNotificationHeader` ONLY inside
  `if (!IsInternalAck())` (lines 3303-3314). With InternalAck, that whole
  block is skipped, so the raw recorded packet bytes go STRAIGHT to the bunch
  loop at line 3638.
- Consequence: the bytes inside each `ReplayData` packet ARE raw bunches,
  not Iris `FNetBlob`-wrapped payloads. There is no Iris data-stream envelope
  at this layer for the replay reader — Iris rides *inside* the legacy bunch
  payload (property data), not outside the packet framing.

### 2. Bunch header layout (NetConnection.cpp:3638-3743) — matches `read_bunch` exactly
| Source line | Field | read_bunch (frame_walk.py) |
|---|---|---|
| 3640 | `bControl = ReadBit()` | `b_control = br.read_bit()` ✓ |
| 3642-3654 | `bOpen`/`bClose`/`CloseReason` gated behind `bControl` | inside `if b_control:` ✓ |
| 3658 | `bIsReplicationPaused = ReadBit()` (unconditional) | read unconditionally ✓ |
| 3660 | `bReliable = ReadBit()` (unconditional) | read unconditionally ✓ |
| 3667-3682 | `ChIndex = SerializeIntPacked()` (MaxActorChannelsCustomization else-branch, true for UE5.6) | `br.serialize_int_packed()` ✓ |
| 3741-3743 | `bHasPackageMapExports`, `bHasMustBeMappedGUIDs`, `bPartial` read UNCONDITIONALLY | read unconditionally ✓ |
| 3706-3715 | partial sub-flags: `bPartial` → `bPartialInitial` → `bPartialCustomExportsFinal` (if `bHasPartialCustomExportsFinalBit`) → `bPartialFinal` | read in that order ✓ |

The non-control fields (bIsReplicationPaused, bReliable, ChIndex,
bHasPackageMapExports, bHasMustBeMappedGUIDs, bPartial) are read for EVERY
bunch — only `bOpen`/`bClose`/`CloseReason`/`ChName` are behind `bControl`.
This is the exact gating my `read_bunch` mirrors. (An earlier desync on
non-control bunches was caused by gating these fields inside `bControl`; fixed
and re-validated.)

### 3. Channel-name read
- `ChName` is read via `UPackageMap::StaticSerializeName` (line 3719) only when
  `bReliable || bOpen` (line 3745-ish). My `read_bunch` does the same
  (`if b.b_reliable or b.b_open: b.ch_name = read_static_serialize_name_bits`).

## Independent corroboration
- `tools/frame_walk.py` consumes every `ReplayData` chunk byte-exact to EOF
  across all 10 samples: 628,603 frames, 1,138,102 packets,
  0 bit-inexact, `trailing_residual_bytes == 0`, `errors == []`.
- If the header layout were wrong (e.g., an Iris envelope present), the per-packet
  bit consumption would not match the declared buffer size — it does, exactly.

## Conclusion
The legacy `FInBunch` header layout DOES apply to TYR's replay packets. Iris
does NOT replace the outer bunch/packet framing; it is carried *within* the bunch
payloads (Phase 6 concern). My `read_bunch` is confirmed correct against source
for this build. The "Iris data-stream framing verified against source" deliverable
is therefore SATISFIED, not assumed.

## Open item
- Iris replaces *per-actor* property encoding inside the payload
  (`FReplicationStateDescriptor` / `NetSerializer`s). That is Phase 6 work, not
  Phase 5 framing. Do NOT assume legacy `FRepLayout` send-order when decoding
  payloads — use the Iris-specific `06-property-replication.md`.
