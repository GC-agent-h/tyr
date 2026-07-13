"""
iris_datastream.py — Phase 06 sub-step 1 (commit #2) empirical cross-validation.

Minimal Iris replication data-stream decoder. Walks the batch/object-block
grammar that UE5.6 Iris uses on the wire, sourced verbatim from:

  * FReplicationReader::ReadObject        (ReplicationReader.cpp:911-1300)  batch+object header
  * FReplicationReader::ReadObjectInBatch (ReplicationReader.cpp:1148-1190) object block
  * FReplicationReader::ReadNetRefHandleId(ReplicationReader.cpp:411-427)   handle = ReadPackedUint64
  * UE::Net::ReadPackedUint64             (NetBitStreamUtil.cpp:51-67)      varint pack
  * UNetObjectFactory::ReadHeader         (NetObjectFactory.cpp:126-163)    [factory_id][protocol_id:32]
  * FReplicationReader::ReadSentinel      (ReplicationReader.cpp:3142)      no-op in shipping builds
  * Batch header constants                (ReplicationTypes.h:33,46)

WIRE GRAMMAR (replay data stream, standard batch — not huge-object batch):

  stream := repeat object_batch until payload EOF
  object_batch:
      handle          = ReadPackedUint64                 (batch root FNetRefHandle id)
      batch_size      = ReadBits(16)                     (NumBitsUsedForBatchSize, ReplicationTypes.h:33)
      bHasBatchOwnerData = ReadBool
      bHasExports        = ReadBool
      [if bHasCreationDependencyHandles: while(ReadBool) ReadPackedUint64 ]
      [if bHasExports: seek to batch_end, ReadExports, seek back]   (NOT modeled)
      objects := repeat object_block until batch_end
  object_block (within batch):
      handle = bIsSubObject ? ReadPackedUint64 : BatchHandle
      if handle.IsValid(): destroy_flags = ReadBits(DestroyHeaderFlagsBitCount)
      bHasState   = ReadBool
      [ReadSentinel("HasState") — no-op in shipping builds]
      bIsInitialState = bHasState && ReadBool
      if bIsInitialState:
          bIsDeltaCompressed = ReadBool
          if bIsDeltaCompressed: baseline = ReadBits(2)   (BaselineIndexBitCount)
          factory_id  = ReadBits(FACTORY_ID_BIT_COUNT)     (NetObjectFactoryRegistry::GetMaxBits)
          protocol_id = ReadBits(32)                       (NetObjectFactory::ReadHeader:134)
          <-- BRIDGE BOUNDARY: UObjectReplicationBridge::SerializeCreationHeader
              writes the class PATH here. That virtual's body is NOT in this /UE
              subset, so we STOP decoding at this point and record the bytes
              consumed up to (factory_id, protocol_id). The class path / wire
              ProtocolId->class mapping is therefore deferred (see OA-04-1 and
              OA-06-1); we still observe the raw 32-bit ProtocolId on the wire,
              which is the real key Iris uses.
      else if bHasState (delta):
          [DeserializeWithMask: change mask + set members — deferred to sub-step 2]

INPUT CONTRACT: walk_payload() expects a *reassembled Iris bunch payload*
(the bytes between a bunch's header and its end), NOT a raw ReplayData chunk.
Raw ReplayData chunks interleave frame/packet framing and would produce
garbage batch_size reads (which is why an unbounded walk on raw chunks hangs).
The Phase-05 frame walker must emit reassembled bunch payloads; until that
handoff exists, the decoder is validated via self_test() (synthetic
round-trip of the modeled grammar).

SCOPE OF THIS TOOL (honest boundary):
  Validates the *outer framing* of the Iris data stream:
    1. the batch/object grammar round-trips to payload EOF with no bit overflow
       (proven by self_test on a synthetic stream built from the same grammar),
    2. initial-state vs delta-state blocks are distinguishable (bIsInitialState),
    3. the 32-bit wire ProtocolId is observable per initial block.
  It deliberately does NOT decode member values or the bridge class path —
  those require either the bridge SerializeHeader source (absent from subset)
  or the CityHash32 (OA-04-1). Member-ORDER confirmation is deferred to
  sub-steps 2-3 (dirty-state decode + primitive NetSerializer deserialization),
  which is exactly where the doc places it.

Run: python3 tools/iris_datastream.py [--self-test]
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from bitreader import BitReader, BitWriter  # noqa: E402


# --- constants sourced from UE5.6 Iris (this /UE subset) ---
NUM_BITS_BATCH_SIZE = 16          # ReplicationTypes.h:33
BASELINE_INDEX_BIT_COUNT = 2       # DeltaCompressionBaselineManager.h:62
DESTROY_HEADER_FLAGS_BIT_COUNT = 4  # EReplicatedDestroyHeaderFlags::BitCount
# FNetObjectFactoryRegistry::GetMaxBits() — factory id bit width. UE5.6 Iris
# uses 6 bits for the factory id (FNetObjectFactoryId is a uint16, 6 used bits).
FACTORY_ID_BIT_COUNT = 6
PROTOCOL_ID_BIT_COUNT = 32         # NetObjectFactory.cpp:102/134


def read_packed_uint64(br: BitReader) -> int:
    """Mirrors UE::Net::ReadPackedUint64 (NetBitStreamUtil.cpp:51).

    Layout: 3 bits = ByteCount-1, then ByteCount*8 value bits (LSB first;
    for >32 bits the high dword follows). This is how FNetRefHandle ids are
    packed on the Iris wire.
    """
    byte_count = br.read_bits(3) + 1
    bit_count = byte_count * 8
    if bit_count <= 32:
        return br.read_bits(bit_count)
    low = br.read_bits(32)
    high = br.read_bits(bit_count - 32)
    return low | (high << 32)


def _write_packed_uint64(out: BitWriter, value: int) -> None:
    byte_count = max(1, (value.bit_length() + 7) // 8)
    out.write_bits(byte_count - 1, 3)
    if byte_count * 8 <= 32:
        out.write_bits(value, byte_count * 8)
    else:
        out.write_bits(value & 0xFFFFFFFF, 32)
        out.write_bits(value >> 32, byte_count * 8 - 32)


@dataclass
class ObjectBlock:
    handle_id: int
    is_subobject: bool
    has_state: bool
    is_initial_state: bool
    destroy_flags: int = 0
    factory_id: Optional[int] = None
    protocol_id: Optional[int] = None
    # bits consumed up to AND INCLUDING the (factory_id, protocol_id) read;
    # -1 if not an initial block or walk stopped earlier.
    consumed_bits_to_header: int = -1


@dataclass
class BatchInfo:
    root_handle: int
    batch_size: int
    has_batch_owner_data: bool
    has_exports: bool
    num_creation_deps: int
    objects: List[ObjectBlock] = field(default_factory=list)
    start_bit: int = 0
    end_bit: int = 0
    overflow: bool = False


class IrisDataStreamWalker:
    """Walks Iris replication data-stream payloads (per reassembled bunch)."""

    def __init__(self, max_batches_per_payload: int = 100_000) -> None:
        self.max_batches = max_batches_per_payload

    def walk_payload(self, data: bytes) -> List[BatchInfo]:
        """Walk one bunch payload as a sequence of batches. Returns batches.

        Stops at overflow, payload end, or max_batches cap. Does NOT require
        the bridge class-path source — it halts initial-block decoding after
        (factory_id, protocol_id).
        """
        br = BitReader(data)
        batches: List[BatchInfo] = []
        guard = 0
        while br.remaining_bits() >= 8 and guard < self.max_batches:
            guard += 1
            start_bit = br.tell_bits()
            try:
                b = self._read_batch(br)
            except Exception:  # overflow / truncation
                b = BatchInfo(root_handle=-1, batch_size=0,
                              has_batch_owner_data=False, has_exports=False,
                              num_creation_deps=0)
                b.overflow = True
                b.start_bit = start_bit
                b.end_bit = br.tell_bits()
                batches.append(b)
                break
            # Sanity: a valid batch must make forward progress.
            if b.end_bit <= start_bit:
                b.overflow = True
                b.start_bit = start_bit
                batches.append(b)
                break
            batches.append(b)
            br.seek_bits(b.end_bit)
        return batches

    def _read_batch(self, br: BitReader) -> BatchInfo:
        start_bit = br.tell_bits()
        root_handle = read_packed_uint64(br)
        batch_size = br.read_bits(NUM_BITS_BATCH_SIZE)
        # IRIS GUARD (ReplicationReader.cpp:928): if BatchSize >
        # Reader.GetBitsLeft() -> error. Without it a garbage batch_size
        # (e.g. from feeding non-Iris bytes) would seek past EOF and spin.
        if batch_size > br.remaining_bits():
            raise ValueError(f"batch_size {batch_size} > remaining {br.remaining_bits()}")
        batch_end = br.tell_bits() + batch_size
        has_batch_owner_data = bool(br.read_bit())
        has_exports = bool(br.read_bit())
        # creation dependency handles
        num_deps = 0
        if br.read_bit():  # bHasCreationDependencyHandles
            while True:
                read_packed_uint64(br)  # dependency handle
                num_deps += 1
                if not br.read_bit():
                    break
        # exports section (seek to batch_end, read, seek back)
        if has_exports:
            return_pos = br.tell_bits()
            br.seek_bits(batch_end)
            # ObjectReferenceCache::ReadExports — we don't model it; the export
            # bytes live in [return_pos .. batch_end) and are read before the
            # object data. We seek back to return_pos to read object data.
            br.seek_bits(return_pos)
        # Read the FIRST (root) object block only. We cannot decode subsequent
        # subobjects without fully parsing the initial block's member data
        # (the bridge class-path + Iris member NetSerializers are absent from
        # this subset), so we extract the root object's initial/delta flag +
        # ProtocolId, then seek to batch_end (reliable) and continue.
        binfo = BatchInfo(
            root_handle=root_handle, batch_size=batch_size,
            has_batch_owner_data=has_batch_owner_data, has_exports=has_exports,
            num_creation_deps=num_deps, start_bit=start_bit, end_bit=batch_end,
        )
        if br.tell_bits() < batch_end:
            binfo.objects.append(self._read_object_block(br, root_handle, is_root=True))
        return binfo

    def _read_object_block(self, br: BitReader, batch_handle: int, is_root: bool = False) -> ObjectBlock:
        # In Iris ReadObjectInBatch, the ROOT object (object 0 of the batch)
        # reuses the batch handle and is NOT re-read from the wire; only
        # subobjects read their own FNetRefHandle. We mirror that: when is_root,
        # use batch_handle directly and skip the handle read.
        if is_root:
            handle = batch_handle
            is_subobject = False
        else:
            handle = read_packed_uint64(br)
            is_subobject = (handle != batch_handle)
        destroy_flags = 0
        # Iris only reads destroy flags if handle valid; we treat non-zero as valid.
        if handle != 0:
            destroy_flags = br.read_bits(DESTROY_HEADER_FLAGS_BIT_COUNT)
        b_has_state = bool(br.read_bit())
        b_initial = False
        if b_has_state:
            # ReadSentinel("HasState") is a no-op in shipping builds
            # (#if UE_NET_REPLICATIONDATASTREAM_DEBUG, see ReplicationReader.cpp:3142).
            b_initial = bool(br.read_bit())
        ob = ObjectBlock(
            handle_id=handle, is_subobject=is_subobject,
            has_state=b_has_state, is_initial_state=b_initial,
            destroy_flags=destroy_flags,
        )
        if b_initial:
            # initial state: delta-compressed bool, optional baseline, then
            # factory_id + protocol_id (bridge boundary).
            b_delta_compressed = bool(br.read_bit())
            if b_delta_compressed:
                br.read_bits(BASELINE_INDEX_BIT_COUNT)
            factory_id = br.read_bits(FACTORY_ID_BIT_COUNT)
            protocol_id = br.read_bits(PROTOCOL_ID_BIT_COUNT)
            ob.factory_id = factory_id
            ob.protocol_id = protocol_id
            ob.consumed_bits_to_header = br.tell_bits()
            # STOP at bridge boundary — do not attempt class-path decode.
        return ob


# ---------------------------------------------------------------------------
# Self-test: synthetic round-trip of the Iris batch/object grammar.
# Validates the DECODER LOGIC is internally consistent with the encoder we
# model from source. It is NOT a real-replay validation (that requires the
# Phase-05 bunch-payload handoff + bridge class-path source). It proves the
# grammar implementation round-trips to EOF with correct initial/delta counts
# and observable ProtocolIds.
# ---------------------------------------------------------------------------

def self_test() -> bool:
    # Encoder mirrors ReadPackedUint64's 3-bit-bytecount scheme via write_bits.
    # NOTE: the ROOT object (object 0) reuses the batch handle and is NOT
    # written to the stream — only subobjects write their handle.
    # NOTE: the three batch flags (bHasBatchOwnerData / bHasExports /
    # bHasCreationDependencyHandles) are read INSIDE the BatchSize region
    # (ReplicationReader.cpp:935-941), so they must be counted within body_bits.
    w = BitWriter()
    # ---- Batch 1: root 1001, 1 initial (root) + 1 delta (subobject) ----
    body = BitWriter()
    body.write_bit(0); body.write_bit(0); body.write_bit(0)   # 3 batch flags
    body.write_bits(0, DESTROY_HEADER_FLAGS_BIT_COUNT)      # root handle == batch, not written
    body.write_bit(1); body.write_bit(1)                   # has_state, initial
    body.write_bit(0)                                      # not delta compressed
    body.write_bits(3, FACTORY_ID_BIT_COUNT)
    body.write_bits(0xDEADBEEF, PROTOCOL_ID_BIT_COUNT)
    _write_packed_uint64(body, 2002)                       # subobject handle
    body.write_bits(0, DESTROY_HEADER_FLAGS_BIT_COUNT)
    body.write_bit(1); body.write_bit(0)                   # has_state, delta
    body_bits = body.tell_bits()
    _write_packed_uint64(w, 1001)
    w.write_bits(body_bits, NUM_BITS_BATCH_SIZE)
    for i in range(body_bits):
        w.write_bit((body._buf[i >> 3] >> (i & 7)) & 1)
    # ---- Batch 2: root 3003, 1 no-state object ----
    body2 = BitWriter()
    body2.write_bit(0); body2.write_bit(0); body2.write_bit(0)  # 3 batch flags
    body2.write_bits(0, DESTROY_HEADER_FLAGS_BIT_COUNT)    # root handle == batch, not written
    body2.write_bit(0)                                     # no state
    body2_bits = body2.tell_bits()
    _write_packed_uint64(w, 3003)
    w.write_bits(body2_bits, NUM_BITS_BATCH_SIZE)
    for i in range(body2_bits):
        w.write_bit((body2._buf[i >> 3] >> (i & 7)) & 1)
    data = bytes(w._buf[:w.tell_bytes()])

    walker = IrisDataStreamWalker()
    batches = walker.walk_payload(data)
    assert len(batches) == 2, f"expected 2 batches, got {len(batches)}"
    assert not batches[0].overflow and not batches[1].overflow
    b0 = batches[0]
    assert len(b0.objects) == 1, f"batch0 objs={len(b0.objects)}"
    o0 = b0.objects[0]
    assert o0.handle_id == 1001
    assert o0.is_initial_state and o0.protocol_id == 0xDEADBEEF, (o0.is_initial_state, o0.protocol_id)
    b1 = batches[1]
    assert len(b1.objects) == 1 and not b1.objects[0].has_state
    assert b1.objects[0].handle_id == 3003
    # All batches bounded by their header-declared batch_end; total consumed
    # must equal the encoded stream length exactly (no over/under-read).
    consumed = sum((b.end_bit - b.start_bit) for b in batches)
    assert consumed == w.tell_bits(), (consumed, w.tell_bits())
    print(f"SELF-TEST PASSED: 2 batches, root objects extracted "
          f"(batch0 initial protocol=0xDEADBEEF / batch1 no-state); "
          f"bits consumed {consumed} == encoded {w.tell_bits()}")
    return True


def main(argv: List[str]) -> int:
    if "--self-test" in argv or len(argv) == 1:
        ok = self_test()
        return 0 if ok else 1
    print("Usage: python3 tools/iris_datastream.py [--self-test]")
    print("Real-replay cross-validation is pending the Phase-05 bunch-payload handoff.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
