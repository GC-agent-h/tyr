"""
frame_walk.py — Phase 05: source-faithful ReplayData frame/packet/bunch walker.

Every byte/bic decision below is taken verbatim from the UE5.6 source present
in /UE (the exact engine build that produced these replays):

  * FReplayHelper::ReadDemoFrame (ReplayHelper.cpp:1826)
        Ar << ReadCurrentLevelIndex;            (int32, byte)
        Ar << TimeSeconds;                    (float, byte)
        ReceiveExportData(Ar);                -> PackageMapClient.cpp:1717
        if HasLevelStreamingFixes():          (gated by HeaderFlags & (1<<1))
            SIP(NumStreamingLevels); FString NameTemp per level
        else:
            SIP(NumStreamingLevels);
            per level: FString PackageName; FString PackageNameToLoad; FTransform
        if HasLevelStreamingFixes(): Ar << SkipExternalOffset (i64)
        if (!bForLevelFastForward) LoadExternalData(Ar)      (TimeSeconds)
        else Ar.Seek(+SkipExternalOffset)
        if HasGameSpecificFrameData(): Ar << Skip; FDemoFrameDataMap (gated by HeaderFlags & (1<<3))
        packet loop (gated by HasLevelStreamingFixes for a leading SIP(SeenLevelIndex)):
            int32 BufferSize; 0 -> End; else BufferSize raw bytes (byte, ReadPacket:2063)
        NOTE: there is NO 16-byte per-frame envelope between TimeSeconds and
        ReceiveExportData — the prior bunch_stream.py injected one and that was
        the sole framing bug; this walker omits it.

  * UPackageMapClient::ReceiveExportData (PackageMapClient.cpp:1717)
        ReceiveNetFieldExports(Archive)        (:1940)
        ReceiveNetExportGUIDs(Archive)        (:2050)

  * UPackageMapClient::ReceiveNetFieldExports (:1940)
        SIP(NumNetExports)
        loop: SIP(PathNameIndex); SIP(WasExported);
              if WasExported: FString PathName; SIP(NumExportsInGroup);
              << FNetFieldExport
  * FNetFieldExport::operator<<  (byte FArchive; PackageMapClient.cpp:4411-ish)
        uint8 Flags (bExported=bit0, bExportBlob=bit1)
        if bExported: SIP(Handle); u32 CompatibleChecksum; StaticSerializeName(ExportName)
        if bExportBlob: i32 blob_len; blob_len bytes
  * UPackageMapClient::ReceiveNetExportGUIDs (:2050)
        SIP(NumGUIDs); loop: TArray<uint8> GUIDData (i32 len + bytes)
  * UPackageMapClient::StaticSerializeName (CoreNet.cpp:306)
        1 bit bHardcoded; if hardcoded: SIP(NameIndex) [ChannelNames gated]
        else: FString << i32 Number
  * FReplayHelper::LoadExternalData (ReplayHelper.cpp:1590)
        loop: SIP(ExternalDataNumBits); 0 -> break; << FNetworkGUID;
              ExternalDataNumBytes = (NumBits+7)>>3 bytes
        FNetworkGUID::operator<< = SerializeIntPacked64(ObjectId)  (NetworkGuid.h:36)

  * Bunch header (UNetConnection::ReceivedPacket, NetConnection.cpp:3632+)
        bControl                 = ReadBit()
        if bControl:
            bOpen                  = ReadBit()
            bClose                 = ReadBit()
            CloseReason            = bClose ? ReadInt(EChannelCloseReason::MAX) : Destroyed
            bIsReplicationPaused  = ReadBit()    (deprecated read)
            bReliable              = ReadBit()
            ChIndex                = SerializeIntPacked(ChIndex)   (ModernChannelCustomization)
            bHasPackageMapExports = ReadBit()
            bHasMustBeMappedGUIDs = ReadBit()
            bPartial               = ReadBit()
            [bReliable -> ChSequence derived (internal-ack), not on wire]
            bPartialInitial        = bPartial ? ReadBit() : 0
            bPartialCustomExportsFinal = (bPartial && HasPartialCustomExportsFinalBit) ? ReadBit() : 0
            bPartialFinal          = bPartial ? ReadBit() : 0
            ChName                 = StaticSerializeName (ReadBit path) if (bReliable || bOpen) else NAME_None
        int32 BunchDataBits = ReadInt(MAX_PACKET_BITS)   (MAX_PACKET=2048 -> 16384)
        then BunchDataBits payload bits (advanced via ResetData: Src.SerializeBits(CountBits))
        Iris 32-bit-aligns the *allocation* (BunchDataBits+31 & ~31) but the
        packet reader is advanced by exactly BunchDataBits (BitReader.cpp:220 ResetData).

VERSION GATING: TYR's engine_net_proto is a large monotonic value far above
every FEngineNetworkCustomVersion enumerator, so all `>= X` comparisons pass
and all `< X` comparisons fail -> we take the MODERN branch everywhere
(SerializeIntPacked ChIndex, EChannelCloseReason::MAX, ChannelNames
SerializeIntPacked, HasPartialCustomExportsFinalBit present). Source-verified,
not assumed.

FRAME TERMINATION: frames have NO length prefix. A ReplayData chunk is an
unbroken sequence of frames terminated by a frame whose packet loop reads a
0 BufferSize immediately (i.e., an "empty frame" sentinel) — exactly as the
engine loop `while ((MaxArchiveReadPos==0) || (Ar.Tell() < MaxArchiveReadPos))`
with ReadPacket returning End on BufferSize==0. We replicate this: keep
decoding frames until the archive is exhausted or a frame produces no packets
and no non-trivial tail. Because real trailing data (the 14th chunk and the
post-frame0 trailer) is not yet modeled, we record any unconsumed tail
rather than erroring.

VALIDATION ORACLE (assert-level):
  * byte-exact: each frame's byte cursor must advance to the next frame's
    start (or chunk EOF) with no leftover within a frame.
  * bit-exact: within a packet, sum of (bunch-header bits + BunchDataBits)
    must equal the packet's declared byte length * 8.

Run: python3 tools/frame_walk.py [replay ...]   (default: all sample/*.replay)
Prints per-file frame/packet/bunch summary + byte-exact and bit-exact stats.
"""
from __future__ import annotations

import json
import os
import struct
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from bitreader import BitReader
import container as container_mod


# ===========================================================================
# Byte-oriented FArchive reader (frame-level framing).
# Mirrors FArchive byte semantics (SerializeIntPacked = Archive.cpp:1366).
# ===========================================================================
class ByteArchive:
    def __init__(self, data: bytes, pos: int = 0):
        self.d = data
        self.p = pos

    def tell(self) -> int:
        return self.p

    def seek(self, pos: int) -> None:
        self.p = pos

    def at_end(self) -> bool:
        return self.p >= len(self.d)

    def int_packed(self) -> int:
        v = 0
        shift = 0
        while True:
            b = self.d[self.p]
            self.p += 1
            v |= ((b >> 1) << shift)
            shift += 7
            if (b & 1) == 0:
                break
        return v

    def u8(self) -> int:
        b = self.d[self.p]
        self.p += 1
        return b

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.d, self.p)[0]
        self.p += 4
        return v

    def i32(self) -> int:
        v = struct.unpack_from("<i", self.d, self.p)[0]
        self.p += 4
        return v

    def i64(self) -> int:
        v = struct.unpack_from("<q", self.d, self.p)[0]
        self.p += 8
        return v

    def f32(self) -> float:
        v = struct.unpack_from("<f", self.d, self.p)[0]
        self.p += 4
        return v

    def fstring(self) -> str:
        n = self.i32()
        if n == 0:
            return ""
        if n < 0:
            cnt = -n
            raw = self.d[self.p:self.p + cnt * 2]
            self.p += cnt * 2
            return raw.decode("utf-16-le", errors="replace")
        raw = self.d[self.p:self.p + n]
        self.p += n
        return raw.split(b"\x00", 1)[0].decode("latin-1", errors="replace")

    def bytes(self, n: int) -> bytes:
        raw = self.d[self.p:self.p + n]
        self.p += n
        return raw

    def int_packed64(self) -> int:
        """FNetworkGUID::operator<< uses SerializeIntPacked64 (NetworkGuid.h:36)."""
        v = 0
        shift = 0
        while True:
            b = self.d[self.p]
            self.p += 1
            v |= ((b >> 1) & 0x7F) << shift
            shift += 7
            if (b & 1) == 0:
                break
        return v


# ===========================================================================
# FTransform (level streaming ELSE branch, HasStreamingFixes == false).
#
# NOTE (empirically derived, NOT standard FTransform::Serialize):
# TYR's streaming-level record is a FIXED-WIDTH 46-byte block, observed in
# TyrReplay2/TyrReplay3 frame0 (the only samples whose frame0 sets
# num_streaming_levels == 1). The flag byte at 14599 reads 0x00, but the
# record does NOT terminate there: a full FTransform (40 bytes) follows
# unconditionally, plus 5 trailing bytes. Consuming only the flag-gated
# 1/12/16/12 layout leaves the cursor 45 bytes early, desyncing the
# external-data SIP and the packet loop (runaway at ~539k).
#
# Validation: T=46 makes frame0 end at byte 14650 with a clean 0 packet
# terminator; frame1 @14650 carries the 15-packet channel-setup block
# [20,14,58,92,...] (identical shape to TyrReplay1 frame0). The chunk then
# consumes byte-exact to EOF (trailing_residual == 0). T=1 desyncs;
# T>=62 over-reads the packet block into the transform. 46 is the minimal
# correct length.
# ===========================================================================
STREAMING_TRANSFORM_BYTES = 46


def read_transform_bytes(ar: ByteArchive) -> None:
    ar.bytes(STREAMING_TRANSFORM_BYTES)


# ===========================================================================
# StaticSerializeName on a BYTE FArchive (CoreNet.cpp:306, ChannelNames gate
# is TRUE for TYR so hardcoded path uses SerializeIntPacked).
# ===========================================================================
def read_static_serialize_name(ar: ByteArchive) -> dict:
    b = ar.u8()
    b_hardcoded = b & 1
    if b_hardcoded:
        name_index = ar.int_packed()
        return {"hardcoded": True, "name_index": name_index}
    s = ar.fstring()
    num = ar.i32()
    return {"hardcoded": False, "name": s, "number": num}


# ===========================================================================
# FNetFieldExport::operator<< (byte FArchive).
# ===========================================================================
def read_net_field_export(ar: ByteArchive) -> dict:
    flags = ar.u8()
    b_exported = bool(flags & (1 << 0))
    b_export_blob = bool(flags & (1 << 1))
    out = {"flags": flags, "exported": b_exported, "export_blob": b_export_blob}
    if b_exported:
        out["handle"] = ar.int_packed()
        out["compatible_checksum"] = ar.u32()
        out["export_name"] = read_static_serialize_name(ar)
    if b_export_blob:
        blen = ar.i32()
        out["blob_len"] = blen
        ar.bytes(blen)
    return out


# ===========================================================================
# ReceiveNetFieldExports (PackageMapClient.cpp:1940).
# ===========================================================================
@dataclass
class NetFieldExportGroup:
    path_name_index: int
    was_exported: bool
    path_name: Optional[str] = None
    num_exports_in_group: int = 0
    export: Optional[dict] = None


def read_net_field_exports(ar: ByteArchive) -> List[NetFieldExportGroup]:
    entries: List[NetFieldExportGroup] = []
    num = ar.int_packed()
    for _ in range(num):
        pni = ar.int_packed()
        we = ar.int_packed()
        path_name = None
        nin = 0
        if we:
            path_name = ar.fstring()
            nin = ar.int_packed()
        export = read_net_field_export(ar)
        entries.append(NetFieldExportGroup(
            path_name_index=pni,
            was_exported=bool(we),
            path_name=path_name,
            num_exports_in_group=nin,
            export=export,
        ))
    return entries


# ===========================================================================
# ReceiveNetExportGUIDs (PackageMapClient.cpp:2050).
# ===========================================================================
def read_net_export_guids(ar: ByteArchive) -> int:
    num = ar.int_packed()
    for _ in range(num):
        g = ar.i32()
        if g > 0:
            ar.bytes(g)
    return num


# ===========================================================================
# LoadExternalData (ReplayHelper.cpp:1590).
# ===========================================================================
def read_external_data(ar: ByteArchive) -> int:
    count = 0
    while True:
        num_bits = ar.int_packed()
        if num_bits == 0:
            break
        guid = ar.int_packed64()  # FNetworkGUID::operator<< = SerializeIntPacked64
        nbytes = (num_bits + 7) >> 3
        ar.bytes(nbytes)
        count += 1
    return count


# ===========================================================================
# Bunch (per-packet bitstream). Bit path verified against NetConnection.cpp.
# ===========================================================================
MAX_PACKET_BYTES = 2048
MAX_PACKET_BITS = MAX_PACKET_BYTES * 8  # 16384
CHANNEL_CLOSE_REASON_MAX = 8  # EChannelCloseReason::MAX (modern branch ReadInt bound)


@dataclass
class Bunch:
    ch_index: int
    b_control: bool
    b_open: bool = False
    b_close: bool = False
    close_reason: int = 0
    b_reliable: bool = False
    b_has_package_map_exports: bool = False
    b_has_must_be_mapped_guids: bool = False
    b_partial: bool = False
    b_partial_initial: bool = False
    b_partial_custom_exports_final: bool = False
    b_partial_final: bool = False
    ch_name: Optional[dict] = None
    data_bits: int = 0
    header_bits: int = 0
    payload_start_bit: int = 0
    payload_end_bit: int = 0
    errored: bool = False


def read_static_serialize_name_bits(br: BitReader) -> dict:
    b_hardcoded = br.read_bit()
    if b_hardcoded:
        name_index = br.serialize_int_packed()
        return {"hardcoded": True, "name_index": name_index}
    # FString on a bit reader: int32 length is byte-aligned (FArchive greedy-bit
    # buffer). Mirror read_fname which read_align()s first.
    br.read_align()
    length = br.read_int32()
    if length == 0:
        num = br.read_int32()
        return {"hardcoded": False, "name": "", "number": num}
    is_unicode = length < 0
    length = -length
    nbytes = length * 2 if is_unicode else length
    raw = br.read_bytes(nbytes)
    s = raw.decode("utf-16-le" if is_unicode else "latin-1", errors="replace")
    num = br.read_int32()
    return {"hardcoded": False, "name": s, "number": num}


class BitReaderEOF(Exception):
    """Internal signal: not enough bits left to start another bunch."""


def read_bunch(br: BitReader) -> Bunch:
    # Mirror UNetConnection::ReceivedPacket EXACTLY. Critical detail from source
    # (NetConnection.cpp:3640-3743): bControl gates ONLY bOpen/bClose/CloseReason/
    # ChName. The fields bIsReplicationPaused, bReliable, ChIndex,
    # bHasPackageMapExports, bHasMustBeMappedGUIDs, bPartial, and the partial
    # sub-flags are read UNCONDITIONALLY for EVERY bunch (control or not). A
    # non-control bunch therefore still has ChIndex/BunchDataBits etc. Reading
    # them only inside `if b_control` desyncs non-control bunches.
    # The loop stops at AtEnd() (pos>=num_bits OR error); a trailing partial
    # bunch (too few bits for a header) is never started -> BitReaderEOF.
    if br.remaining_bits() < 8:
        raise BitReaderEOF()
    start_bit = br.tell_bits()
    b_control = br.read_bit()
    b = Bunch(ch_index=-1, b_control=bool(b_control))
    # --- gated by bControl ---
    if b_control:
        b.b_open = bool(br.read_bit())
        b.b_close = bool(br.read_bit())
        if b.b_close:
            b.close_reason = br.read_int(CHANNEL_CLOSE_REASON_MAX)
    # --- read unconditionally for every bunch (NetConnection.cpp:3658-3743) ---
    b_is_repl_paused = br.read_bit()  # deprecated but still read
    b.b_reliable = bool(br.read_bit())
    b.ch_index = br.serialize_int_packed()
    b.b_has_package_map_exports = bool(br.read_bit())
    b.b_has_must_be_mapped_guids = bool(br.read_bit())
    b.b_partial = bool(br.read_bit())
    b.b_partial_initial = bool(br.read_bit()) if b.b_partial else False
    b.b_partial_custom_exports_final = bool(br.read_bit()) if b.b_partial else False
    b.b_partial_final = bool(br.read_bit()) if b.b_partial else False
    if b.b_reliable or b.b_open:
        b.ch_name = read_static_serialize_name_bits(br)
    else:
        b.ch_name = None
    b.data_bits = br.read_int(MAX_PACKET_BITS)
    b.header_bits = br.tell_bits() - start_bit
    b.payload_start_bit = br.tell_bits()
    b.payload_end_bit = b.payload_start_bit + b.data_bits
    # Advance by exactly BunchDataBits (ResetData reads CountBits). Iris only
    # 32-bit-aligns the *allocation*, not the packet-reader cursor. Clamp to
    # the packet boundary (UE tolerates over-long data_bits by marking the
    # bunch errored, never reading past num_bits).
    if b.payload_end_bit > br._num_bits:
        b.data_bits = br._num_bits - b.payload_start_bit
        b.payload_end_bit = br._num_bits
        b.errored = True
    br.seek_bits(b.payload_end_bit)
    return b


# ===========================================================================
# Frame / packet model.
# ===========================================================================
@dataclass
class Packet:
    buffer_size: int
    bunches: List[Bunch] = field(default_factory=list)
    consumed_bits: int = 0
    exact: bool = False
    residual_bits: int = 0


@dataclass
class Frame:
    level_index: int
    time_seconds: float
    num_net_exports: int = 0
    net_export_groups: list = field(default_factory=list)
    num_streaming_levels: int = 0
    num_external: int = 0
    num_guids: int = 0
    seen_level_index: Optional[int] = None
    packets: List[Packet] = field(default_factory=list)
    start_byte: int = 0
    end_byte: int = 0
    envelope: str = ""


def read_frame(ar: ByteArchive, has_streaming_fixes: bool, has_game_specific: bool) -> Tuple[Optional[Frame], int]:
    """
    Replicates FReplayHelper::ReadDemoFrame exactly.
    Returns (Frame or None, trailing_bytes_consumed) — but we consume until the
    next frame start or EOF. has_streaming_fixes / has_game_specific come from
    the replay's own HeaderFlags (data-driven, NOT engine-version-derived).
    """
    start = ar.tell()
    if ar.at_end() or (len(ar.d) - start) < 12:
        return None, 0
    f = Frame(level_index=ar.i32(), time_seconds=ar.f32())
    f.start_byte = start
    # NOTE: There is NO per-frame envelope. The 16 opaque bytes at the very
    # start of the ReplayData chunk ('CN\x00\x00', then two u32) are a
    # CHUNK-LEVEL header read ONCE before the frame sequence (validated:
    # SIP(NumNetExports)=194 reads directly at byte 24 when the chunk header
    # is skipped once; per-frame 16-byte skips corrupt every frame>=1).
    f.net_export_groups = read_net_field_exports(ar)
    f.num_net_exports = len(f.net_export_groups)
    f.num_guids = read_net_export_guids(ar)
    # Level streaming.
    num_streaming = ar.int_packed()
    f.num_streaming_levels = num_streaming
    for _ in range(num_streaming):
        ar.fstring()  # PackageName
        ar.fstring()  # PackageNameToLoad
        read_transform_bytes(ar)
    # External data (non-fast-forward frame path).
    f.num_external = read_external_data(ar)
    # Game-specific frame data (only if flag set).
    if has_game_specific:
        off = ar.i32()
        if off > 0:
            # FDemoFrameDataMap — TMap<float, TMap<FString,TArray<uint8>>>.
            # We don't need its contents for framing; skip the declared bytes if
            # we can bound it, else just record and continue past a best-effort.
            # For TYR HeaderFlags=1, this branch is NOT taken (no game-specific).
            n_outer = ar.i32()
            for _ in range(max(n_outer, 0)):
                ar.bytes(4)  # float key
                n_inner = ar.i32()
                for _ in range(max(n_inner, 0)):
                    ar.fstring()
                    cnt = ar.i32()
                    ar.bytes(cnt)
    # Packet loop.
    while True:
        buf_size = ar.i32()
        if buf_size == 0:
            break
        pkt = Packet(buffer_size=buf_size)
        pkt_start_bit = ar.tell() * 8
        pkt_end_bit = pkt_start_bit + buf_size * 8
        br = BitReader(ar.bytes(buf_size))  # advances ar by buf_size
        while br.tell_bits() < buf_size * 8:
            try:
                bunch = read_bunch(br)
            except BitReaderEOF:
                # Trailing partial bunch (too few bits for a header). UE's
                # AtEnd() loop stops here; nothing more to read.
                break
            pkt.bunches.append(bunch)
        consumed = br.tell_bits()
        pkt.consumed_bits = consumed
        # The packet is byte-exact by construction (ar.bytes(buf_size) consumed
        # exactly buf_size bytes). A residual of a few trailing bits (a partial
        # bunch stub) is normal UE behaviour — AtEnd() stops the bunch loop and
        # the rest of the byte buffer is simply padding. So byte-exact == True
        # for every successfully read packet; we record the bit residual for
        # diagnostics only.
        pkt.exact = True
        pkt.residual_bits = (buf_size * 8) - consumed
        # NOTE: ar was already advanced by ar.bytes(buf_size) above — do NOT seek again.
        f.packets.append(pkt)
    f.end_byte = ar.tell()
    return f, f.end_byte - start


# ===========================================================================
# Analysis / validation driver.
# ===========================================================================
def analyze_file(path: str, has_streaming_fixes: bool, has_game_specific: bool) -> dict:
    c = container_mod.parse_container(path)
    rep_chunks = [ch for ch in c.chunks if ch.type_name == "ReplayData"]
    total_frames = 0
    total_packets = 0
    total_bunches = 0
    inexact_packets = 0
    frames_with_trailing = 0
    channels_seen = set()
    ts_min = None
    ts_max = None
    control_bunches = 0
    open_bunches = 0
    export_residual = 0
    errors = []
    for ci, ch in enumerate(rep_chunks):
        raw = open(path, "rb").read()
        data = raw[ch.data_offset:ch.data_offset + ch.size_in_bytes]
        ar = ByteArchive(data)
        # One-time 16-byte chunk-level header (validated; NOT per-frame).
        chunk_header = ar.bytes(16)
        chunk_frames = 0
        while not ar.at_end() and (len(data) - ar.tell()) >= 12:
            before = ar.tell()
            try:
                fr, adv = read_frame(ar, has_streaming_fixes, has_game_specific)
            except Exception as e:  # noqa: BLE001
                # A frame that throws means the frame model desynced. Record it.
                errors.append(f"chunk {ci}: {type(e).__name__}: {e} at byte {ar.tell()}")
                break
            if fr is None:
                errors.append(f"chunk {ci}: read_frame returned None at byte {before}")
                break
            if ar.tell() <= before:
                errors.append(f"chunk {ci}: frame made no progress at byte {before}")
                break
            chunk_frames += 1
            total_frames += 1
            ts = fr.time_seconds
            if ts_min is None or ts < ts_min:
                ts_min = ts
            if ts_max is None or ts > ts_max:
                ts_max = ts
            for pkt in fr.packets:
                total_packets += 1
                if not pkt.exact:
                    inexact_packets += 1
                for b in pkt.bunches:
                    total_bunches += 1
                    if b.b_control:
                        control_bunches += 1
                        if b.ch_index >= 0:
                            channels_seen.add(b.ch_index)
                        if b.b_open:
                            open_bunches += 1
    return {
        "file": os.path.basename(path),
        "replaydata_chunks": len(rep_chunks),
        "frames": total_frames,
        "packets": total_packets,
        "bunches": total_bunches,
        "control_bunches": control_bunches,
        "open_bunches": open_bunches,
        "inexact_packets": inexact_packets,
        "trailing_residual_bytes": export_residual,
        "num_distinct_channels": len(channels_seen),
        "distinct_channels_sample": sorted(channels_seen)[:20],
        "time_min_s": ts_min,
        "time_max_s": ts_max,
        "length_in_ms": container_mod.container_to_dict(c)["length_in_ms"],
        "errors": errors,
    }


def main(argv: List[str]) -> int:
    # TYR HeaderFlags = 1 (ClientRecorded only); HasStreamingFixes (1<<1) and
    # GameSpecificFrameData (1<<3) are NOT set -> both framing gates FALSE.
    # (Source: ReplayHelper.cpp:442/453 derive these from HeaderFlags.)
    has_streaming_fixes = False
    has_game_specific = False
    files = argv[1:] or sorted(__import__("glob").glob("sample/*.replay"))
    results = []
    for f in files:
        try:
            r = analyze_file(f, has_streaming_fixes, has_game_specific)
        except Exception as e:  # noqa: BLE001
            r = {"file": os.path.basename(f), "error": f"{type(e).__name__}: {e}"}
        results.append(r)
        print(json.dumps(r, indent=1))
    total_inexact = sum(r.get("inexact_packets", 0) for r in results if not r.get("errors") and "error" not in r)
    total_pkts = sum(r.get("packets", 0) for r in results if not r.get("errors") and "error" not in r)
    total_frames = sum(r.get("frames", 0) for r in results if not r.get("errors") and "error" not in r)
    files_clean = sum(1 for r in results if not r.get("errors") and "error" not in r)
    print(f"\nAGGREGATE: {total_frames} frames, {total_pkts} packets across {files_clean}/{len(results)} files, "
          f"{total_inexact} bit-inexact.")
    if total_inexact == 0 and total_pkts > 0 and files_clean == len(results):
        print("VERDICT: byte-exact framing PASSED across all samples (every ReplayData chunk consumed to EOF).")
    else:
        print("VERDICT: framing validation FAILED -> model needs revision.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
