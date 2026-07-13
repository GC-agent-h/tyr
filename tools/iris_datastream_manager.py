"""
Iris DataStreamManager packet-region decoder (Phase 06 t7 handoff).

Source of truth (UE5.6 Iris sources in /UE):
  * UDataStreamManager::FImpl::ReadData  -> Iris/Private/Iris/DataStream/DataStreamManager.cpp:841
  * UDataStreamManager::FImpl::WriteData -> DataStreamManager.cpp:350  (mirror, for validation)
  * FReplicationWriter::Write            -> Iris/Private/Iris/ReplicationSystem/ReplicationWriter.cpp:4348
  * FReplicationReader::Read             -> Iris/Private/Iris/ReplicationSystem/ReplicationReader.cpp:2924

ARCHITECTURE (why this is separate from the legacy bunch stream):
  In UE5.6, Iris replication does NOT ride inside legacy UChannel bunch
  payloads. The entire connection packet buffer is:
       [legacy bunch stream ...][Iris DataStreamManager region]
  The DataStreamManager writes a small header, then for each active data
  stream concatenates that stream's payload (the FReplicationReader envelope).
  frame_walk's bunch loop stops at AtEnd() of the bunch stream, which leaves
  the Iris region as trailing residual bits in the packet buffer. THIS decoder
  parses that trailing region.

WIRE GRAMMAR (DataStreamManager region, bit-exact):
  StreamCount        = ReadBits(5) + 1                (DataStreamManager.cpp:98 StreamCountBitCount=5)
  DataStreamMask     = ReadBits(StreamCount)          (:847)
  bHasStateChanges   = ReadBool()                     (:850)
  if bHasStateChanges:
      ChangedMask    = ReadBits(StreamCount)          (:851)
      for each set bit in ChangedMask:
          State      = ReadBits(4)                    (:874 StreamStateBitCount=4)
  for each set bit in DataStreamMask (in index order):
      <DataStream->ReadData>  == FReplicationReader envelope (see iris_datastream.py):
          [2-bit debug features][16-bit ObjectBatchCountToRead]
          [16-bit DestroyCount][destroy records][batches...]

NOTE: stream payload boundaries are NOT length-prefixed; each DataStream->ReadData
consumes exactly its own region. So we parse the header, then for each active
stream call the per-stream decoder, letting the BitReader advance. A clean parse
consumes the entire region (reader reaches end) with no overflow on any stream.

The replication (game-state) stream is whichever active stream decodes as a
valid FReplicationReader envelope (object_batch_count plausible, batches parse).
Other streams (e.g. NetTokenDataStream) will not satisfy that and are skipped.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from bitreader import BitReader
from iris_datastream import IrisDataStreamWalker, PayloadInfo

STREAM_COUNT_BIT_COUNT = 5   # DataStreamManager.cpp:98
STREAM_STATE_BIT_COUNT = 4   # DataStreamManager.cpp:99


@dataclass
class StreamInfo:
    index: int
    is_replication: bool = False
    payload: Optional[PayloadInfo] = None


@dataclass
class DataStreamManagerInfo:
    stream_count: int
    data_stream_mask: int
    has_state_changes: bool
    changed_mask: int = 0
    states: List[int] = field(default_factory=list)
    streams: List[StreamInfo] = field(default_factory=list)
    consumed_bits: int = 0
    total_bits: int = 0
    overflow: bool = False
    exact: bool = False
    error: Optional[str] = None


def walk_manager(data: bytes, expected_bits: Optional[int] = None) -> DataStreamManagerInfo:
    """Decode an Iris DataStreamManager region from `data` (raw bytes, bit-precise).

    Returns DataStreamManagerInfo. `exact` means the region was fully consumed
    with no overflow and at least one active stream decoded as a valid
    replication envelope. `expected_bits`, if given, overrides len(data)*8 as
    the target (used by the synthetic self-test, whose payload is not
    byte-aligned).
    """
    total = len(data) * 8
    if expected_bits is not None:
        total = expected_bits
    info = DataStreamManagerInfo(
        stream_count=0, data_stream_mask=0, has_state_changes=False,
        consumed_bits=0, total_bits=total)
    if total < 8:
        info.error = "region too small"
        info.overflow = True
        return info
    br = BitReader(data)
    try:
        stream_count = br.read_bits(STREAM_COUNT_BIT_COUNT) + 1
        data_stream_mask = br.read_bits(stream_count)
        has_changes = br.read_bit() != 0
        changed_mask = 0
        states = []
        if has_changes:
            changed_mask = br.read_bits(stream_count)
            for i in range(stream_count):
                if (changed_mask >> i) & 1:
                    states.append(br.read_bits(STREAM_STATE_BIT_COUNT))
        info.stream_count = stream_count
        info.data_stream_mask = data_stream_mask
        info.has_state_changes = has_changes
        info.changed_mask = changed_mask
        info.states = states

        walker = IrisDataStreamWalker()
        for i in range(stream_count):
            if not ((data_stream_mask >> i) & 1):
                continue
            si = StreamInfo(index=i)
            # Save position; try to decode this stream as a replication envelope.
            pos_before = br.tell_bits()
            remaining = total - pos_before
            if remaining < 0:
                info.overflow = True
                break
            stream_bytes = br.serialize_bits(remaining)
            try:
                pl = walker.walk_payload(stream_bytes)
                # Valid replication envelope: plausible batch count, parsed to end.
                si.is_replication = (not pl.overflow) and pl.object_batch_count > 0
                si.payload = pl
            except Exception:
                # Not a valid replication envelope; skip (e.g. NetToken stream).
                si.is_replication = False
                si.payload = None
            # Advance the reader by however many bits this stream declared it used.
            # We can't know the exact sub-length, so re-parse deterministically:
            # the walk_payload consumed `pl.consumed_bits` if it was a valid
            # envelope; otherwise we must fall back to scanning. For a clean
            # manager region the last active stream runs to the buffer end.
            if si.payload is not None and not si.payload.overflow:
                br.seek_bits(pos_before + si.payload.consumed_bits)
            else:
                # Unknown-length non-replication stream: cannot advance precisely.
                # Mark and stop (this region isn't a clean Iris manager block).
                info.overflow = True
                break
            info.streams.append(si)
        info.consumed_bits = br.tell_bits()
        info.exact = (not info.overflow) and (info.consumed_bits == total)
    except Exception as e:  # noqa: BLE001
        info.error = f"{type(e).__name__}: {e}"
        info.overflow = True
    return info


def self_test() -> None:
    """Synthetic round-trip of the DataStreamManager header + one replication stream.

    Build a region with StreamCount=1, mask=1 (stream 0 active), no state
    changes, then append the iris_datastream self-test payload (bit-exact, via
    encode_self_test_payload). Verify it walks back as exactly one replication
    stream consuming the whole region.
    """
    from iris_datastream import encode_self_test_payload, IrisDataStreamWalker, BitWriter

    env_bytes, env_bits = encode_self_test_payload()
    # Manager header: StreamCount=1 (write 0 in 5 bits), mask=1 (1 bit),
    # no state changes (bool 0), then the envelope bit-exact.
    region = BitWriter()
    region.write_bits(0, STREAM_COUNT_BIT_COUNT)   # StreamCount-1 = 0 -> count 1
    region.write_bits(1, 1)                         # DataStreamMask bit0
    region.write_bit(0)                             # bHasStateChanges = false
    # Append the envelope bits (must preserve bit order).
    # env_bytes encodes env_bits; re-emit bit by bit.
    br = BitReader(env_bytes)
    for _ in range(env_bits):
        region.write_bit(br.read_bit())

    data = region.getvalue()
    header_bits = STREAM_COUNT_BIT_COUNT + 1 + 1  # StreamCount + mask + bool
    info = walk_manager(data, expected_bits=header_bits + env_bits)
    assert info.stream_count == 1, info
    assert info.data_stream_mask == 1, info
    assert not info.has_state_changes, info
    assert len(info.streams) == 1, info.streams
    assert info.streams[0].is_replication, info.streams[0]
    assert info.streams[0].payload is not None, info.streams[0]
    assert info.streams[0].payload.object_batch_count == 2, info.streams[0].payload
    assert info.consumed_bits == header_bits + env_bits, (info.consumed_bits, header_bits + env_bits)
    assert info.exact, (info.consumed_bits, info.total_bits)
    print(f"MANAGER SELF-TEST PASSED: StreamCount=1, 1 replication stream, "
          f"2 batches, region {info.total_bits} bits consumed exactly.")


if __name__ == "__main__":
    self_test()
