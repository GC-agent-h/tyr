# Phase 06 — Todo 7: U1 bundle wire grammar (binary deep-dive)

STATUS: IN PROGRESS (2026-07-14). NOT closed. Validated negatives only.

## Source-verified Iris (UE5.6) per-type SERIALIZER grammar
Read directly from /home/gcurr/tyr/UE/Iris (the verified UE5.6 tree):
- Bit stream: LSB-first, 32-bit little-endian words (NetBitStreamReader.cpp:54-99).
  INTEL_ORDER32 is a no-op on x86, so ReadBits reads LSB-first within each
  4-byte word. This CONFIRMS the wire is pure bit-packed (not byte/varint).
- bool: 1 bit (BoolNetSerializer.cpp:38).
- int/uint of N bits: 1-bit isZero-opt when N>=16, then N bits
  (IntNetSerializerBase.h:37-57; ZeroValueOptimizationBitCount=16).
- enum: BitCount = ceil(log2(range)), same zero-opt, value offset by enum min
  (InternalEnumNetSerializers.cpp:49 + IntNetSerializerBase).
- float: 1-bit isNonZero then 32-bit IEEE, or just 1 bit if zero
  (FloatNetSerializers.cpp:78-96). EXPLAINS the `0,0` markers in earlier
  varint streams (the zero-val-opt bit).
- double: 1-bit isNonZero then 64 bits (FloatNetSerializers.cpp:117-142).
- array: 1-bit empty marker, else count(ElementCountBitCount) + elements
  (ArrayPropertyNetSerializer.cpp:81-117).
- quantized vector: PackedVectorNetSerializers.cpp (per-component scale bits).

## Stock Iris OBJECT ENVELOPE (read for reference; FALSIFIED for TYR blob)
Per FReplicationWriter::WriteObjectAndSubObjects (ReplicationWriter.cpp:2744-2840)
+ SerializeObjectStateDelta (2508-2535), a batch = for each subobject:
  WriteNetRefHandleId(handle) [packed uint64, only if IsSubObject]
  + destroy-header (GetDestroyHeaderFlagsBitCount bits)
  + bHasState(1b) -> HasState sentinel(if debug)
  + bIsInitialState(1b) -> bDeltaCompressionEnabled(1b) -> CreatedBaselineIndex(2b)
  + WriteNetRefHandleCreationInfo (CLASS PATH -> usmap struct mapping!)
  + SerializeObjectStateDelta: LastAckedBaselineIndex(2b) + SerializeWithMask
    (changemask = all-ones for initial state via GetInitialChangeMask.SetAllBits,
     ReplicationWriter.cpp:519-524 + 613) + member state bits.

## FALSIFIED hypotheses (validated negatives — these are real findings)
H1. TYR blob = stock Iris `WriteObjectAndSubObjects` batch output.
    FALSIFIED (tools/iris_decode.py walk): reading the blob as
    [WriteNetRefHandleId + destroy-hdr + bHasState + ...] decodes handles
    `12,73,40,...` that DO NOT match the carrier header's `595,603,...`,
    and bHasState is mostly 0 (an initial-state batch must be all-1s).
    => TYR does NOT emit the stock Iris object envelope.

H2. 1936B blob = 31 fixed 499-bit subobject records, each starting with an
    all-ones changemask (initial state).
    FALSIFIED (tools/_probe_lead1.py): the 499-bit blocks begin with
    `0,0,1,1`-style bits, zerofrac ~0.77, NO all-ones leading run. The 499
    figure was pure arithmetic (15488/31), not structural evidence.

H3. (prior, 2026-07-13) Single flat/recursive usmap struct decodes the blob.
    FALSIFIED (bb90e80/9aa9bf1): Mode2 = 0/5347; Mode1 "hits" tautological.

## What is KNOWN vs UNKNOWN (honest state)
KNOWN:
  - usmap is a real runtime schema anchor (14,050 structs) but does NOT by
    itself close U1 (H3).
  - The carrier is a hierarchical object bundle: header [u16 count][N u16
    handles] + blob (OA-06-2, carrier_decode.py).
  - Iris per-TYPE serializer bit-grammar (above) — verified from engine src.
  - TYR does NOT use the stock Iris object envelope for this blob (H1,H2).
UNKNOWN (the actual U1 gap):
  - TYR's CUSTOM per-subobject wire envelope: how subobjects are delimited in
    the blob, and how each subobject's handle (from header) maps to a usmap
    struct (the type/class mapping). The stock Iris CreationInfo (class path)
    is NOT present in the TYR framing, so the usmap<-handle binding is the
    missing link.
  - Whether Iris per-type serializers are even used inside the blob, or TYR
    uses an entirely separate serialization for the payload.

## Next step to close U1 (not yet done)
Recover TYR's custom per-subobject envelope from the Shipping binary:
  - Anchor the per-subobject record serializer (the function that writes the
    blob after the handle list) via the Iris module PDB strings
    (ReplicationSystemUtil/EngineReplicationBridge/NetSubObjectFactory) +
    the 17,648 .reloc function-pointer tables.
  - Disassemble to recover: (a) how the subobject type/class is encoded
    (or confirmed absent -> then the type is implied by handle order), and
    (b) the per-subobject member serialization order/widths, so the usmap
    struct members can be mapped onto the bit stream.
  This requires the binary deep-dive the todo was scoped for; the source
  grammar above is the necessary cross-reference but is insufficient alone
  because TYR diverges at the ENVELOPE layer, not the type layer.
