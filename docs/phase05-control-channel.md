# Phase 05 — Control channel behavior (recorded vs. stripped) for this build

Per `docs/05-bunches-and-channels.md` deliverable "Control channel
behavior confirmed (recorded vs. stripped) for this build", this note
records the empirical finding from TYR's 10 sample replays. No live
debugging available; evidence is from `tools/frame_walk.py` parse counts
(byte-exact, 0 bit-inexact across all 10 files) + targeted channel
inspection (`tools/_probe_ctrl.py`).

## Finding
Control-channel bunches ARE recorded in TYR's replay `ReplayData`
packets. They are NOT stripped at record time.

### Evidence (TyrReplay1, representative; same shape in all 10)
- Total control bunches (b_control == True): ~9,341 across the file.
- By channel index: index **0** dominates (567 in the first chunk's
  inspected set; ~9k file-wide). These are:
  - `b_open = False`, `b_reliable = False`, `data_bits = 0`, `ch_name = None`
  - → matches UE's **Control channel** (NMT_* connection-level
    messages; no actor name, non-reliable, empty payload on the
    header-only frames).
- Actor-channel OPEN bunches: `b_open = True`, `b_reliable = True`,
  with `ch_name = {hardcoded: True, name_index: 102}`. These appear
  on non-zero channel indices (1, 2, 3, 4, 5, 6, …) — the
  per-actor `UActorChannel` open path (`SerializeNewActor` /
  `GetFreeChannelIndex`). `name_index 102` is the engine's hardcoded
  `EName` for the actor-channel type (resolved via the hardcoded-name
  table; exact numeric mapping is engine-version specific but the
  structure is correct: open bunches carry a hardcoded channel-type
  name, mirroring `NetConnection.cpp:3719` `UPackageMap::
  StaticSerializeName`).
- `b_close = 3` in T1 (a few channels close during the session;
  most recordings end mid-session with channels left open, which the
  doc notes is VALID for level transitions / end-of-recording).

### Implication for parsing
- The control channel (index 0) must be parsed (not skipped) — it
  carries recorded connection-level messages. My `read_bunch` already
  handles `b_control` gating (bOpen/bClose/CloseReason/ChName only
  inside `if b_control`), confirmed byte-exact.
- Actor channels open via `bOpen` bunches that DO carry a hardcoded
  channel-type name (not an FString), consistent with
  `MAX_ACTOR_CHANNELS_CUSTOMIZATION` / `ChannelNames` network version
  being set (UE5.6). This matches `read_bunch`'s
  `read_static_serialize_name_bits` (hardcoded → SerializeIntPacked name
  index) path.

## Conclusion
Control-channel behavior for this build: **recorded, not stripped**.
Both the control channel (index 0) messages and per-actor channel
open/close bunches are present and parse byte-exact. No parsing
exception is needed to skip the control channel. Deliverable SATISFIED.
