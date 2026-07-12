"""
container.py — Phase 01: Outer Container Format skeleton pass for TYR `.replay`.

Faithful reimplementation of the UE5.6 LocalFileNetworkReplayStreaming
top-level layout, derived from the engine source:

  Engine/Source/Runtime/NetworkReplayStreaming/LocalFileNetworkReplayStreaming/
    Public/LocalFileNetworkReplayStreaming.h
    Private/LocalFileNetworkReplayStreaming.cpp

Source of truth for the on-disk layout (ReadReplayInfo / WriteReplayInfo):
  * FileMagic = 0x1CA2E27F  (FLocalFileNetworkReplayStreamer::FileMagic)
  * The 32-bit "FileVersion" field is the *deprecated* per-file version.
    For version >= FLocalFileReplayCustomVersion::CustomVersions (7), a
    FCustomVersionContainer is serialized immediately after it, and the
    real version used for gating is that custom-version number.
    TYR files are version 7 -> CustomVersions branch is taken, so the
    FCustomVersionContainer IS present.

  Header (file-level) byte layout, all little-endian:
    u32 MagicNumber
    u32 FileVersion (deprecated; == custom version here)
    int32 CustomVersionCount
      per version:  FGuid(16 bytes) + int32 Version
    int32  LengthInMS
    u32    NetworkVersion
    u32    Changelist
    FString FriendlyName            (fixed 256-char buffer, forced Unicode)
    u32    IsLive
    FDateTime Timestamp             (present: version >= RecordingTimestamp=3)
    u32    bCompressed              (present: version >= CompressionSupport=2)
    u32    bEncrypted               (present: version >= EncryptionSupport=6)
      TArray<uint8> EncryptionKey   (present when EncryptionSupport branch taken;
                                     length 0 when not encrypted)

  Chunk table (the rest of the file, until EOF):
    while not AtEnd():
      ELocalFileChunkType ChunkType  (u32)
      int32 SizeInBytes
      <SizeInBytes payload bytes>

  ELocalFileChunkType:
    0 Header, 1 ReplayData, 2 Checkpoint, 3 Event, 0xFFFFFFFF Unknown

This module performs ONLY the skeleton pass (magic/version/metadata + chunk
walk with exact EOF landing). It does not interpret chunk *contents* (that is
Phases 2, 5, 8).

Run:  python3 tools/container.py [replay ...]
  default: all sample/*.replay
"""

from __future__ import annotations

import json
import os
import struct
import sys
from dataclasses import dataclass, field
from typing import List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SAMPLE_DIR = os.path.join(REPO, "sample")

# FLocalFileNetworkReplayStreamer::FileMagic (LocalFileNetworkReplayStreaming.cpp:83)
FILE_MAGIC = 0x1CA2E27F

# FLocalFileReplayCustomVersion (Public header)
CV_BEFORE = 0
CV_FIXED_SIZE_FRIENDLY_NAME = 1
CV_COMPRESSION_SUPPORT = 2
CV_RECORDING_TIMESTAMP = 3
CV_STREAM_CHUNK_TIMES = 4
CV_FRIENDLY_NAME_CHAR_ENCODING = 5
CV_ENCRYPTION_SUPPORT = 6
CV_CUSTOM_VERSIONS = 7
CV_LATEST = 7  # VersionPlusOne - 1

CHUNK_TYPE_NAMES = {
    0: "Header",
    1: "ReplayData",
    2: "Checkpoint",
    3: "Event",
    0xFFFFFFFF: "Unknown",
}


class ContainerError(Exception):
    pass


def _read_u32(b: bytes, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


def _read_i32(b: bytes, o: int) -> int:
    return struct.unpack_from("<i", b, o)[0]


@dataclass
class CustomVersion:
    guid: str
    version: int


@dataclass
class ChunkInfo:
    index: int
    chunk_type: int
    type_name: str
    type_offset: int
    data_offset: int
    size_in_bytes: int


@dataclass
class ReplayContainer:
    file: str
    file_size: int
    magic: int
    file_version: int
    custom_versions: List[CustomVersion]
    length_in_ms: int
    network_version: int
    changelist: int
    friendly_name: str
    is_live: bool
    timestamp_ticks: int
    b_compressed: bool
    b_encrypted: bool
    encryption_key_len: int
    chunks: List[ChunkInfo] = field(default_factory=list)
    header_end_offset: int = 0  # byte offset of first chunk (end of file-level header)
    reached_eof: bool = False
    # The effective serialization version used for gating:
    serialization_version: int = 0


def _read_fstring(b: bytes, o: int):
    """Read an FString. Returns (string, new_offset).

    Layout: int32 Len. If Len < 0 -> Unicode (UTF-16LE), char count = -Len.
    If Len >= 0 -> ANSI, byte count = Len. Trailing NUL is part of the
    serialized buffer in both cases (included in Len)."""
    slen = _read_i32(b, o)
    o += 4
    if slen < 0:
        nchars = -slen
        raw = b[o: o + nchars * 2]
        s = raw.decode("utf-16-le", errors="replace")
        o += nchars * 2
    else:
        raw = b[o: o + slen]
        s = raw.decode("latin-1", errors="replace")
        o += slen
    return s, o


def parse_container(path: str) -> ReplayContainer:
    with open(path, "rb") as f:
        data = f.read()
    n = len(data)
    off = 0

    magic = _read_u32(data, off)
    off += 4
    if magic != FILE_MAGIC:
        raise ContainerError(
            f"{path}: bad magic {hex(magic)} (expected {hex(FILE_MAGIC)})"
        )

    file_version = _read_u32(data, off)
    off += 4

    # CustomVersions branch (file_version >= 7 in TYR).
    custom_versions: List[CustomVersion] = []
    serialization_version = file_version
    if file_version >= CV_CUSTOM_VERSIONS:
        cv_count = _read_i32(data, off)
        off += 4
        if cv_count < 0 or cv_count > 1024:
            raise ContainerError(f"{path}: implausible custom version count {cv_count}")
        for _ in range(cv_count):
            guid = data[off: off + 16]
            off += 16
            cv_ver = _read_i32(data, off)
            off += 4
            custom_versions.append(CustomVersion(guid=guid.hex(), version=cv_ver))
        # The custom-version number for the "LocalFileReplay" tag drives gating.
        serialization_version = file_version

    # Standard summary fields.
    length_in_ms = _read_i32(data, off); off += 4
    network_version = _read_u32(data, off); off += 4
    changelist = _read_u32(data, off); off += 4

    friendly_name, off = _read_fstring(data, off)

    # Version-gated fields. TYR serialization version == 7 (CustomVersions),
    # so ALL optional branches are taken (RecordingTimestamp=3,
    # CompressionSupport=2, EncryptionSupport=6 are all <= 7).
    ver = serialization_version

    is_live = False
    timestamp_ticks = 0
    b_compressed = False
    b_encrypted = False
    encryption_key_len = 0

    # NOTE: source order is FriendlyName -> IsLive -> Timestamp -> Compressed
    # -> Encrypted -> EncryptionKey.  IsLive is NOT version-gated (it is always
    # serialized, right after the friendly name), so read it unconditionally.
    is_live = (_read_u32(data, off) != 0); off += 4

    if ver >= CV_RECORDING_TIMESTAMP:
        # FDateTime serializes as int64 ticks (100ns since 0001-01-01).
        timestamp_ticks = struct.unpack_from("<q", data, off)[0]
        off += 8

    if ver >= CV_COMPRESSION_SUPPORT:
        compressed = _read_u32(data, off); off += 4
        b_compressed = (compressed != 0)

    if ver >= CV_ENCRYPTION_SUPPORT:
        encrypted = _read_u32(data, off); off += 4
        b_encrypted = (encrypted != 0)
        # TArray<uint8> EncryptionKey always written in this branch.
        key_len = _read_i32(data, off); off += 4
        if key_len < 0 or key_len > 4096:
            raise ContainerError(f"{path}: implausible encryption key len {key_len}")
        encryption_key_len = key_len
        off += key_len  # skip key bytes

    header_end_offset = off

    # Chunk table walk.
    chunks: List[ChunkInfo] = []
    idx = 0
    while off < n:
        type_offset = off
        chunk_type = _read_u32(data, off)
        off += 4
        size_in_bytes = _read_i32(data, off)
        off += 4
        data_offset = off
        if size_in_bytes < 0 or data_offset + size_in_bytes > n:
            raise ContainerError(
                f"{path}: chunk {idx} invalid size {size_in_bytes} at offset {type_offset}"
            )
        chunks.append(
            ChunkInfo(
                index=idx,
                chunk_type=chunk_type,
                type_name=CHUNK_TYPE_NAMES.get(chunk_type, f"0x{chunk_type:08X}"),
                type_offset=type_offset,
                data_offset=data_offset,
                size_in_bytes=size_in_bytes,
            )
        )
        off = data_offset + size_in_bytes
        idx += 1

    reached_eof = (off == n)
    if not reached_eof:
        raise ContainerError(f"{path}: chunk walk ended at {off}, file size {n} (leftover {n - off})")

    c = ReplayContainer(
        file=os.path.basename(path),
        file_size=n,
        magic=magic,
        file_version=file_version,
        custom_versions=custom_versions,
        length_in_ms=length_in_ms,
        network_version=network_version,
        changelist=changelist,
        friendly_name=friendly_name,
        is_live=is_live,
        timestamp_ticks=timestamp_ticks,
        b_compressed=b_compressed,
        b_encrypted=b_encrypted,
        encryption_key_len=encryption_key_len,
        chunks=chunks,
        header_end_offset=header_end_offset,
        reached_eof=reached_eof,
        serialization_version=serialization_version,
    )
    return c


def _ticks_to_iso(ticks: int) -> str:
    # FDateTime ticks = 100ns intervals since 0001-01-01 UTC.
    # Unix epoch in ticks = 621355968000000000.
    if ticks == 0:
        return "0"
    import datetime
    epoch_ticks = 621355968000000000
    dt = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc) + \
        datetime.timedelta(microseconds=(ticks - epoch_ticks) / 10)
    return dt.isoformat()


def print_report(c: ReplayContainer) -> None:
    print(f"=== {c.file} ===")
    print(f"  file_size            : {c.file_size} bytes")
    print(f"  magic                : {hex(c.magic)} (expected {hex(FILE_MAGIC)})")
    print(f"  file_version         : {c.file_version}")
    print(f"  serialization_version: {c.serialization_version}")
    for cv in c.custom_versions:
        print(f"    custom_version guid={cv.guid} ver={cv.version}")
    print(f"  length_in_ms         : {c.length_in_ms} ({c.length_in_ms/1000.0:.1f}s)")
    print(f"  network_version      : {c.network_version}")
    print(f"  changelist           : {c.changelist}")
    print(f"  friendly_name        : {c.friendly_name!r}")
    print(f"  is_live              : {c.is_live}")
    print(f"  timestamp_ticks      : {c.timestamp_ticks} ({_ticks_to_iso(c.timestamp_ticks)})")
    print(f"  b_compressed         : {c.b_compressed}")
    print(f"  b_encrypted          : {c.b_encrypted} (key_len={c.encryption_key_len})")
    print(f"  header_end_offset    : {c.header_end_offset}")
    print(f"  chunks ({len(c.chunks)}):")
    for ch in c.chunks:
        print(f"    [{ch.index:2d}] {ch.type_name:10s} type_off={ch.type_offset:9d} "
              f"data_off={ch.data_offset:9d} size={ch.size_in_bytes:9d}")
    print(f"  EOF landing          : {'OK' if c.reached_eof else 'FAIL'}")
    print()


def container_to_dict(c: ReplayContainer) -> dict:
    return {
        "file": c.file,
        "file_size": c.file_size,
        "magic": hex(c.magic),
        "file_version": c.file_version,
        "serialization_version": c.serialization_version,
        "custom_versions": [
            {"guid": cv.guid, "version": cv.version} for cv in c.custom_versions
        ],
        "length_in_ms": c.length_in_ms,
        "network_version": c.network_version,
        "changelist": c.changelist,
        "friendly_name": c.friendly_name,
        "is_live": c.is_live,
        "timestamp_ticks": c.timestamp_ticks,
        "timestamp_iso": _ticks_to_iso(c.timestamp_ticks),
        "b_compressed": c.b_compressed,
        "b_encrypted": c.b_encrypted,
        "encryption_key_len": c.encryption_key_len,
        "header_end_offset": c.header_end_offset,
        "reached_eof": c.reached_eof,
        "chunks": [
            {
                "index": ch.index,
                "type": ch.type_name,
                "type_offset": ch.type_offset,
                "data_offset": ch.data_offset,
                "size_in_bytes": ch.size_in_bytes,
            }
            for ch in c.chunks
        ],
    }


def main(argv: List[str]) -> int:
    args = list(argv)
    json_out = False
    if "--json" in args:
        json_out = True
        args.remove("--json")

    if args:
        paths = args
    else:
        import glob
        paths = sorted(glob.glob(os.path.join(SAMPLE_DIR, "*.replay")))
        if not paths:
            print("No .replay files found in sample/", file=sys.stderr)
            return 2

    containers: List[ReplayContainer] = []
    for p in paths:
        try:
            c = parse_container(p)
        except ContainerError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        containers.append(c)
        if not json_out:
            print_report(c)

    if json_out:
        out_path = os.path.join(REPO, "out", "phase01_container_report.json")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w") as f:
            json.dump([container_to_dict(c) for c in containers], f, indent=2)
        print(f"Wrote {out_path}")
        sys.stdout = open(os.devnull, "w")

    # Cross-file consistency assertion (Phase 1 validation #2).
    ref = containers[0]
    for c in containers[1:]:
        for field_name in ("file_version", "network_version", "changelist", "serialization_version"):
            if getattr(c, field_name) != getattr(ref, field_name):
                print(f"CONSISTENCY FAIL: {c.file} {field_name}="
                      f"{getattr(c, field_name)} != {getattr(ref, field_name)}", file=sys.stderr)
                return 1

    # All must reach EOF.
    for c in containers:
        if not c.reached_eof:
            print(f"EOF FAIL: {c.file}", file=sys.stderr)
            return 1

    # Compression/encryption must be false (Phase 1 deliverable).
    for c in containers:
        if c.b_compressed or c.b_encrypted:
            print(f"FLAG FAIL: {c.file} compressed={c.b_compressed} encrypted={c.b_encrypted}",
                  file=sys.stderr)
            return 1

    print(f"OK: {len(containers)} files parsed; all reached EOF; cross-file version "
          f"consistency held; bCompressed/bEncrypted both false.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
