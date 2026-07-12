# Phase 5 — Bunches and Channels

> **Iris note.** This project's replication backend is confirmed Iris (see `00-overview-and-setup.md`). Iris replaces the legacy per-actor `UActorChannel` bunch-payload model with **Iris Data Streams** (`FNetBlob`/`FDataStream`-based transport, driven by `UDataStreamManager`/`UReplicationDataStream` rather than a 1:1 actor-to-channel mapping). The outer packet/frame-level framing described below (Level 1) is likely still broadly applicable since it's driven by `DemoNetDriver`'s replay-specific wrapper, largely orthogonal to the replication backend — but **Level 2 (bunch framing) needs empirical verification against Iris's actual data-stream framing before you trust the legacy `FInBunch` field layout described here.** Treat everything below this note as the legacy-informed starting hypothesis, not a confirmed structure — check `UDataStreamManager`/`ReplicationDataStream` source first and adjust before writing Phase 6 against it. No live debugging is available to confirm empirically at runtime; use the static cross-check methodology (Step 0.3, revised) and cross-file consistency instead.

## Goal

Decode the actual network traffic stream stored inside `ReplayData` chunks into a sequence of per-frame "packets," each containing one or more "bunches" (UE's term for a channel-addressed unit of data), with correct channel bookkeeping (open/close/partial/reliable state) so that Phase 6 can consume complete, correctly-ordered property payloads per actor.

## Source of truth

- `Engine/Source/Runtime/Engine/Private/DataChannel.cpp` — bunch header parsing (`UChannel::ReceivedRawBunch`, `FInBunch` construction) and channel type dispatch.
- `Engine/Source/Runtime/Engine/Classes/Engine/Channel.h` — `FInBunch`/`FOutBunch` struct definitions, `EChannelType`.
- `Engine/Source/Runtime/Engine/Classes/Engine/ActorChannel.h` and `.../Private/ActorChannel.cpp` — `UActorChannel::ReceivedBunch`, actor-specific channel state.
- `Engine/Source/Runtime/Engine/Private/DemoNetDriver.cpp` — specifically the replay-specific packet processing loop (`UDemoNetDriver::TickDispatch`/`ProcessPacket`/`ReadDemoFrame`-equivalent — the demo driver largely reuses `UNetConnection`'s bunch-processing logic but with a replay-specific framing wrapper around each recorded frame, so also check for a demo-specific "frame" structure that wraps groups of packets with a timestamp). This outer framing is expected to still apply under Iris since it's replay/transport-level, not replication-backend-level — but verify.
- `Engine/Source/Runtime/IrisCore/Private/Iris/ReplicationSystem/DataStream/DataStreamManager.cpp` and `.../ReplicationDataStream.cpp` (path may vary slightly) — the Iris data-stream transport layer that replaces legacy per-actor bunch/channel dispatch; read this **before** assuming the legacy `FInBunch` flag layout (bOpen/bClose/bPartial/etc.) applies unchanged.
- `Engine/Source/Runtime/IrisCore/Private/Net/Core/NetBlob/NetBlobHandler.cpp` / `NetBlob.h` — `FNetBlob` is Iris's unit of serialized payload (objects, RPCs) carried inside data streams; the closest Iris analog to a legacy bunch payload's contents.

## Two levels of framing to distinguish

### Level 1: Demo "frame" framing (replay-specific)

Within a `ReplayData` chunk, data is organized into **frames**, each tagged with a timestamp (float, seconds since recording start) so that scrubbing/seeking works. Each frame typically contains one or more raw packets. Check `DemoNetDriver.cpp`'s frame-write function (search for something like `WriteDemoFrame` or the loop that calls `ReplicateActor`/`TickFlush` during recording) to get the exact per-frame structure:

```
f32 or f64 timestamp
u32 packet_count  (or a sentinel-terminated loop of packets)
for each packet:
    u32 packet_size
    <packet_size bytes of raw packet data>
```

**This framing is replay-specific** — it does not exist in live network traffic, since live connections don't need per-packet timestamps for scrubbing. Confirm the exact structure from the demo driver's write path rather than assuming it matches `DataChannel.cpp`'s live-connection framing.

### Level 2: Bunch framing (shared with live networking, reused as-is)

Within each raw packet payload, one or more **bunches** are packed back-to-back, each with a header matching `FInBunch`'s fields (read from `DataChannel.cpp`/`Channel.h`):

- Channel index (integer, identifies which logical channel — e.g., a specific actor's replication channel, or the special Control channel index 0)
- Channel type (only present on channel-opening bunches — `EChannelType`: Actor, Control, Voice, etc.)
- Flags: `bOpen` (this bunch opens the channel), `bClose` (closes it, e.g. actor destroyed), `bReliable`, `bPartial` (this bunch is a fragment of a larger payload split across multiple bunches), `bPartialInitial`/`bPartialFinal` (fragment position markers), `bHasPackageMapExports` (this bunch carries GUID/NetFieldExportGroup export data inline — ties directly into Phase 4), `bHasMustBeMappedGUIDs`
- Sequence number (for reliable ordering — largely informational for a replay parser since you're processing in file order already, but useful for detecting out-of-order edge cases or validating your parse against expected monotonic sequence)
- Payload bit-count (how many bits of actual channel payload follow — **note this is often a bit-count, not byte-count**, so make sure your bit reader is tracking absolute bit position correctly per Phase 3, since bunch payloads are not necessarily byte-aligned before or after)

## Implementation approach

1. **Frame loop**: for each `ReplayData` chunk, loop over frames, recording each frame's timestamp — this gives you a global "replay time" axis you can attach to every subsequent decoded event, extremely useful for later analysis/debugging (e.g., "what happened at t=42.3s").
2. **Packet loop**: within each frame, loop over raw packets.
3. **Bunch loop**: within each packet, loop over bunches until the packet's bits are exhausted. Maintain a **channel state table**: `Map<ChannelIndex, ChannelState>` where `ChannelState` tracks: channel type, whether open, associated actor NetGUID (once known, from an opening bunch that includes `SerializeNewActor` data — ties into Phase 4), and a partial-bunch reassembly buffer for `bPartial` sequences.
4. **Partial bunch reassembly**: when `bPartial` is set, buffer the payload bits under that channel until `bPartialFinal` arrives, then concatenate and treat as a single logical bunch payload for Phase 6 purposes. Get the exact reassembly order/logic from `UChannel::ReceivedRawBunch`'s partial-handling branch — don't assume simple concatenation is sufficient without checking whether any framing bits are inserted between partial fragments.
5. **Control channel (channel 0) handling**: bunches on the special Control channel carry connection-level messages (e.g., `NMT_Login`-style control messages) rather than actor replication data. For replay purposes many of these are irrelevant (they're live-connection handshake artifacts) but check whether any control messages are meaningfully recorded in replays in your 5.6 branch (some are stripped at record time, some aren't — verify empirically) before assuming you can skip the whole channel.

## Validation

1. **Bit-exact packet consumption**: after decoding all bunches within a packet, the bits consumed should exactly equal the packet's declared bit/byte length from the frame structure. This is your primary hard pass/fail signal for this entire phase, analogous to the chunk-boundary check in Phase 1 — implement it as an assertion, not a warning.
2. **Channel lifecycle sanity**: for every channel index, verify a plausible open→(data)*→close lifecycle (or open→(data)* with no close if the recording ends mid-session, or level transition, which is also valid — cross-check against level-name changes if you track those from Phase 2). A channel receiving data bunches before any open bunch, or receiving bunches after a close bunch, indicates a parsing bug.
3. **Partial bunch reassembly correctness**: after reassembly, the total reassembled payload's bit-length should match any length hint the first partial fragment might carry (check if `FInBunch` includes an expected-total-size hint for partials in your source version) — if such a hint exists, use it as a direct validation check; if not, at minimum verify reassembled payloads for known simple property types (Phase 6) decode to plausible values as an indirect check.
4. **Timestamp monotonicity**: frame timestamps should be non-decreasing (or strictly increasing, check which) throughout a `ReplayData` chunk sequence, and should roughly match the total `LengthInMS` from the Phase 2 header when you reach the last frame. A timestamp that jumps backward or wildly out of range indicates a frame-boundary misparse.
5. **Static cross-check (no live debugging available)**: per Step 0.3 (revised), there's no running session to breakpoint. Substitute: statically disassemble the Iris data-stream dispatch path (`DataStreamManager`/`ReplicationDataStream`) and confirm your parser's inferred framing fields (channel/stream index, flags, sequence, bit count) match the compiled logic by hand-tracing against a couple of real sample-file offsets. Given this is the highest-leverage check in the phase and the hardest to substitute for, budget extra time here and cross-check against Level 1's frame-timestamp monotonicity and Phase 1's chunk-size totals as independent corroborating signals.

## Deliverables checklist

- [ ] Frame loop implemented with timestamp extraction, monotonicity-checked.
- [ ] Packet loop implemented with byte-exact consumption per packet.
- [ ] Bunch header parsing implemented for all relevant flags.
- [ ] Channel state table implemented, tracking open/close/actor-association lifecycle.
- [ ] Partial bunch reassembly implemented and validated.
- [ ] Control channel behavior confirmed (recorded vs. stripped) for this build.
- [ ] Iris data-stream framing verified against source rather than assumed to match legacy `FInBunch` layout.
- [ ] At least one static cross-check (no live debugging available) of bunch/data-stream header sequences, per Step 0.3 (revised).

## Suggested commit breakdown

1. `feat(phase05): implement demo frame loop with timestamp extraction` — the outermost, replay-specific framing layer; commit and validate monotonicity before touching packets/bunches.
2. `feat(phase05): implement packet loop with byte-exact consumption` — the per-frame packet loop, with its own hard consumption assertion.
3. `feat(phase05): implement bunch header parsing` — all flag fields (`bOpen`, `bClose`, `bReliable`, `bPartial`, etc.), without yet handling partial reassembly or channel state — just parse-and-log at this stage.
4. `feat(phase05): implement channel state table and lifecycle tracking` — the open→data→close bookkeeping, built on top of commit 3.
5. `feat(phase05): implement partial bunch reassembly` — kept separate since it's a distinct, trickier piece of logic (buffering across multiple bunches) layered on top of the channel state table.
6. `docs(phase05): document control channel behavior findings for this build` — a short findings note (recorded vs. stripped control messages in this engine/build), committed as documentation even if no parsing code changes as a result.
7. `docs(phase05): static cross-check of bunch/data-stream header sequence` — no live debugging is available on this project; commit disassembly-based notes confirming the Iris data-stream framing in place of a live diff, per Step 0.3 (revised).

Insert a commit before #3 if needed: `docs(phase05): verify Iris data-stream framing against legacy bunch-header assumption` — dedicated commit confirming (or correcting) whether the legacy `FInBunch` flag layout described in this doc actually holds under Iris, since commit 3 onward assumes a specific field layout that needs empirical confirmation first.

If partial bunch reassembly (commit 5) turns out to be unexpectedly complex once you're in it, consider splitting further: one commit for the buffering/concatenation mechanism, a second for whatever length-hint validation you're able to implement per this phase's Validation section.

Proceed to `06-property-replication.md`.
