# Phase 06 — Todo 7: U1 bundle wire grammar (binary deep-dive)

STATUS: IN PROGRESS (2026-07-14). NOT closed. No validated positive decode yet.

## Source-verified Iris (UE5.6) per-type SERIALIZER grammar
Read from /home/gcurr/tyr/UE/Iris (verified UE5.6 tree). CONFIRMED by both
direct reads and a delegated source-research subagent (subagent report saved
to ~/.hermes/cache/delegation/subagent-summary-0-20260714_164353_557161.txt).
- Bit stream: LSB-first, 32-bit LE words (NetBitStreamReader.cpp:54-99). Bit-packed.
- bool: 1 bit (BoolNetSerializer.cpp:38).
- int8/uint8: 8 raw bits, NO zero-opt (ZVO only at BitCount>=16, IntNetSerializerBase.h:268).
- int/uint of N>=16 bits: 1-bit isZero-opt then N bits (IntNetSerializerBase.h:37-57).
- enum: BitCount = ceil(log2(range)) from enum min/max (InternalEnumNetSerializers.cpp:47-49),
  same zero-opt (IntRangeNetSerializerUtils.h:20-23).
- float: 1-bit isNonZero then 32-bit IEEE, or just 1 bit if zero (FloatNetSerializers.cpp:78-96).
- double: 1-bit isNonZero then 64 bits (FloatNetSerializers.cpp:117-142).
- array: 1-bit empty marker else count(GetBitsNeeded(MaxCount) bits)+elems
  (ArrayPropertyNetSerializer.cpp:81-117).
- struct: recurses into inner FReplicationStateDescriptor (StructNetSerializer.cpp:48-74).
- quantized rotator: 3-bit XYZ-is-not-zero mask + 16/8 bits per component
  (RotatorNetSerializers.cpp:95-113).
- NetRefHandle (=object handle on the wire): WritePackedUint64 = 3-bit byte-count
  + that many bytes LSB-first (NetBitStreamUtil.cpp:32-67). NOT a plain 7-bit
  SerializeIntPacked; NOT u16.

## Stock Iris OBJECT ENVELOPE (for reference; tested below)
FReplicationWriter::WriteObjectAndSubObjects (ReplicationWriter.cpp:2582-2840):
- Batch header (ROOT ONLY): bIsDestructionInfo(1b) + optional sentinel(0 bits in
  Shipping, gated UE_NET_REPLICATIONDATASTREAM_DEBUG:4724) + WriteNetRefHandleId(root)
  (WritePackedUint64) + WriteBits(0,16) BATCH-SIZE PLACEHOLDER (filled later with the
  actual batch bit-length, ReplicationWriter.cpp:3132-3161; NumBitsUsedForBatchSize=16,
  ReplicationTypes.h:33) + bHasBatchOwnerData(1b) + bHasExports(1b) + creation-dependency loop.
- Per-object record (root + each subobject): if IsSubObject: WriteNetRefHandleId(subhandle);
  destroy-header(GetDestroyHeaderFlagsBitCount()=3 bits, ReplicationTypes.h:43/48);
  bHasState(1b); bIsInitialState(1b); bDeltaComp(1b) -> CreatedBaselineIndex(2b);
  WriteNetRefHandleCreationInfo (= Factory->WriteHeader, factory-specific,
  ObjectReplicationBridge.cpp:1301-1354); then SerializeObjectStateDelta.
- Change mask: SPARSE BIT ARRAY (RLE of non-zero words) via WriteSparseBitArray
  (NetBitStreamUtil.cpp:589-647; called ReplicationOperations.cpp:1312). For INITIAL
  state it is all-ones and serialized with the ContainsMostlyOnes hint (inverted/RLE).
  => an initial changemask does NOT appear as a raw run of 1 bits on the wire.
- InitState descriptor members carry BitCount=0 changemask bits when bIsInitState
  (ReplicationStateDescriptorBuilder.cpp:1157) — sent wholesale at creation.

## REVISED findings (this session, after correcting prior wrong models)

### RETRACTED (prior session falsifications were built on WRONG MODELS — not valid)
- Prior H2 "no leading all-ones changemask run -> not Iris initial state": WRONG MODEL.
  The changemask is a sparse bit array (RLE), not a raw 1s run. Absence of a raw 1s
  run proves nothing. RETRACTED.
- Prior H1 "decoded handles 12,73,40 != carrier header 595,603 -> not stock Iris":
  WRONG COMPARISON. Used a plain 7-bit packed-uint instead of WritePackedUint64, AND
  compared Iris 64-bit handles to TYR's COMPACTED U16 handles (a different namespace,
  documented disjoint at PROGRESS.md:262). The blob's `12` is actually consistent with
  a small WritePackedUint64 root handle. RETRACTED.

### VALIDATED NEGATIVE (model-correct) — stock single Iris BATCH envelope REFUTED
- Test: the 16-bit batch-size field (NumBitsUsedForBatchSize=16) is filled with the
  actual batch bit-length, so (placeholder_offset + 16 + batchsize) MUST == TOTAL bits
  (15488) for a stock batch. tools/_probe_batchsize2.py scans all start offsets 0..63
  x root-handle widths 1..5 bytes: ZERO matches. Robust to any TYR prefix shift.
  => The 1936B blob is NOT a stock single Iris WriteObjectAndSubObjects batch output.

### UNVALIDATED signal (coincidental) — "blob = concatenated Iris per-object records"
- A single coherent initial-snapshot record header (handle + destroy=0 + hasState=1 +
  isInitial=1 + deltaComp=1 + baseline=0) was found at offset 54 bits under Model B
  (leading handle). BUT tools/_probe_control.py random-bit-shuffle control shows
  scrambled data yields a coherent record at mean 0.19 offsets/run (~ the 1/256-per-offset
  chance rate). Real data = 1 hit. Statistically indistinguishable from coincidence.
  => NOT a validated signal. Do NOT treat as evidence.

## What is KNOWN vs UNKNOWN (honest state)
KNOWN:
  - usmap is a real runtime schema anchor (14,050 structs) but does NOT by itself
    close U1 (Mode2 = 0/5347).
  - Carrier = hierarchical object bundle: header [u16 count][N u16 handles] + blob.
  - Iris per-TYPE serializer bit-grammar (above) — verified from engine source.
  - Stock single Iris BATCH envelope is NOT used for this blob (validated negative).
UNKNOWN (the actual U1 gap, NOT yet closed):
  - TYR's CUSTOM per-object wire envelope: how subobjects are delimited in the blob,
    and how each subobject's handle (from header) maps to a usmap struct.
  - The Factory->WriteHeader creation-info format (ObjectReplicationBridge.cpp:1301,
    factory-specific) that immediately follows the per-object header — this is the
    missing bridge from handle -> class -> usmap struct.
  - Whether Iris per-type serializers are used inside the blob, or TYR uses a
    separate serialization for the payload.

## Next step to close U1 (not yet done)
Recover TYR's per-subobject envelope from the Shipping binary:
  - Anchor the per-subobject record writer (the function emitting the blob after the
    handle list) via the Iris module PDB strings (ReplicationSystemUtil,
    EngineReplicationBridge, NetSubObjectFactory) + the 17,648 .reloc serializer tables.
  - Disassemble Factory->WriteHeader for the relevant factories to recover the
    creation-info layout (the handle->class->usmap bridge).
  - Then build a faithful recursive Iris decoder (BitReader LSB-first + per-type
    serializers + usmap struct walk) and validate byte-exact consumption of the 1936B
    blob. This is the function-level deep-dive todo 7 was scoped for.

## STATUS UPDATE (2026-07-15, REVISED) — dumper-7 supplies the external anchor

The 2026-07-15 "U1 = KNOWN-BLOCKER (runtime-only)" conclusion is now
REFUTED by a provided artifact folder `dumper-7/` (at repo root):

- `dumper-7/Mappings/5.6.0-31351+++Tyr+release-Tyr.usmap` is the AUTHORITATIVE
  SHIPPING usmap for the EXACT build our replays were produced by (replay header
  bytes contain "++Tyr+release" + the same gameplay class names). It is parsed by
  `tools/usmap_parse.py` into per-struct property records (name/type/inner/array).
- `dumper-7/GObjects-Dump-WithProperties.txt` (20 MB) is the live UObject registry:
  Class / ScriptStruct / Enum / Function + Default__ CDO instances, each with
  property NAME + TYPE + BYTE OFFSET. Example: BP_BaseTank.BP_BaseTank_C lists 80+
  replicated properties (ObjectProperty TurretComponent @0x730, DoubleProperty
  TrackOffset @0x750, BoolProperty bIsABot @0x7A8, MapProperty VoiceLineMap, ...).
  84 BlueprintGeneratedClass gameplay entries present. This is the handle->struct
  LAYOUT bridge the width-sum tautology could not supply.
- `dumper-7/CppSDK/` full SDK headers + `dumper-7/Dumpspace/*Info.json` + IDA map.

The two 2026-07-15 negatives still HOLD as static-binary facts:
  1. BINARY: the handle->class->FReplicationStateDescriptor bridge is NOT in the
     Shipping binary's static tables (dispatcher global = non-canonical heap/RTTI
     base). tools/dump_registry.py. (commit b777a54)
  2. USMAP: exact width-sum tiling IS a tautology (the struct assignment cannot be
     found by width-sum alone). tools/u1_tiling_probe.py. (commit c2835bb)

BUT the conclusion that U1 is runtime-only is NOW INVALID: the authoritative
runtime type map is available OFFLINE in dumper-7. The remaining missing piece is
only the PER-REPLAY handle->class bijection, which is recoverable FROM THE REPLAY
STREAM ITSELF: actor-creation bunches carry the class path as an FString (observed
in replay header bytes: "BP_CaptureZone.BP_CaptureZone_C", etc.). Combined with
dumper-7's class schemas, that yields the full handle->layout bridge — NON-
tautologically, because the struct assignment is grounded in the replay's own
spawn class names, not a width-sum search.

REVISED CONCLUSION: U1 is UNBLOCKED by dumper-7. The correct next move is to bind
handles via replay spawn-bunch class names (GObjects/CppSDK/usmap schemas) and
re-attempt the recursive usmap-anchored bundle decoder with a held-out
validation (same handle->class->layout binding must tile each file's distinct
blob). Status: IN PROGRESS (option a), re-started.
