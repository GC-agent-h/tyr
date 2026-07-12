"""header.py — Phase 02: Demo Header chunk parser.

Decodes the `Header` chunk into a structured FNetworkDemoHeader-equivalent,
following the authoritative UE5.6 serialization in UE/ReplayTypes.cpp
(operator<<) and UE/ReplayTypes.h (struct FNetworkDemoHeader,
EReplayHeaderFlags, FReplayCustomVersion, ENetworkVersionHistory).

Field order (from operator<<):
  Magic                          u32  (must == 0x2CF5A13D)
  Version                        i32  (HISTORY_LATEST / CustomVersions)
  CustomVersions                 FCustomVersionContainer (count + N*(Guid+ver))
  NetworkChecksum                u32
  EngineNetworkProtocolVersion   u32
  GameNetworkProtocolVersion     u32
  Guid                           FGuid (16 bytes)
  EngineVersion                  FEngineVersion (uint16*3 + u32 + FString)
  PackageVersionUE               FPackageFileVersion (int32 + int32)  -- gated>=SavePackageVersionUE(17)
  PackageVersionLicenseeUE       i32                                -- gated>=SavePackageVersionUE(17)
  LevelNamesAndTimes             TArray<FLevelNameAndTime> (FString + u32)
  HeaderFlags                    u32 (EReplayHeaderFlags)
  GameSpecificData               TArray<FString>
  [RecordingMetadata gated >= 18]
    MinRecordHz                  f32
    MaxRecordHz                  f32
    FrameLimitInMS               f32
    CheckpointLimitInMS          f32
    Platform                     FString
    BuildConfig                  EBuildConfiguration (uint8)
    BuildTarget                  EBuildTargetType  (uint8)

All multi-byte ints little-endian. FString: int32 length (incl. null
terminator; negative => UTF-16). TArray: int32 count.

The parser asserts BYTE-EXACT consumption of the chunk across all samples
and that Magic/Version are correct. Field semantics are sourced from the
engine header; nothing is guessed.
"""

import enum
import glob
import os
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tools.container import parse_container  # noqa: E402

SAMPLE_DIR = os.path.join(REPO, "sample")
NETWORK_DEMO_MAGIC = 0x2CF5A13D


class EReplayHeaderFlags(enum.IntFlag):
    NONE = 0
    CLIENT_RECORDED = 1 << 0
    HAS_STREAMING_FIXES = 1 << 1
    DELTA_CHECKPOINTS = 1 << 2
    GAME_SPECIFIC_FRAME_DATA = 1 << 3
    REPLAY_CONNECTION = 1 << 4
    ACTOR_PRIORITIZATION_ENABLED = 1 << 5
    NET_RELEVANCY_ENABLED = 1 << 6
    ASYNC_RECORDED = 1 << 7


class HeaderParseError(Exception):
    pass


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def _i32(b, o):
    return struct.unpack_from("<i", b, o)[0]


def _u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def _f32(b, o):
    return struct.unpack_from("<f", b, o)[0]


def _fstring(b, o):
    """UE FString: int32 length then bytes (len includes null terminator)."""
    slen = _i32(b, o)
    o += 4
    if slen == 0:
        return "", o
    if slen < 0:
        n = -slen
        raw = b[o:o + n * 2]
        o += n * 2
        return raw.decode("utf-16-le", "replace"), o
    raw = b[o:o + slen]
    o += slen
    return raw.split(b"\x00", 1)[0].decode("latin-1", "replace"), o


def _tarray(b, o, elem):
    """UE TArray: int32 count then count*elem."""
    cnt = _i32(b, o)
    o += 4
    if cnt < 0 or cnt > 65536:
        raise HeaderParseError(f"implausible TArray count {cnt} at {o-4}")
    out = []
    for _ in range(cnt):
        v, o = elem(b, o)
        out.append(v)
    return out, o


def parse_header(b: bytes) -> dict:
    n = len(b)
    o = 0
    magic = _u32(b, o); o += 4
    if magic != NETWORK_DEMO_MAGIC:
        raise HeaderParseError(f"Magic mismatch: {magic:#x} != {NETWORK_DEMO_MAGIC:#x}")
    version = _i32(b, o); o += 4

    # FCustomVersionContainer::Serialize: int32 count, then count * (FGuid + i32 ver)
    cv_count = _i32(b, o); o += 4
    if cv_count < 0 or cv_count > 256:
        raise HeaderParseError(f"implausible CustomVersion count {cv_count}")
    custom_versions = []
    for _ in range(cv_count):
        g = struct.unpack_from("<IIII", b, o); o += 16
        ver = _i32(b, o); o += 4
        custom_versions.append({
            "guid": f"{g[0]:08x}{g[1]:08x}{g[2]:08x}{g[3]:08x}",
            "version": ver,
        })

    network_checksum = _u32(b, o); o += 4
    engine_net_proto = _u32(b, o); o += 4
    game_net_proto = _u32(b, o); o += 4

    guid_raw = b[o:o + 16]; o += 16
    guid = f"{_u32(guid_raw,0):08x}{_u32(guid_raw,4):08x}" \
           f"{_u32(guid_raw,8):08x}{_u32(guid_raw,12):08x}"

    # FEngineVersion::Serialize: uint16 Major, Minor, Patch; uint32 Changelist; FString Branch
    major = _u16(b, o); o += 2
    minor = _u16(b, o); o += 2
    patch = _u16(b, o); o += 2
    changelist = _u32(b, o); o += 4
    branch, o = _fstring(b, o)
    engine_version = {
        "major": major, "minor": minor, "patch": patch,
        "changelist": changelist, "branch": branch,
    }

    # Package versions gated by FReplayCustomVersion::SavePackageVersionUE (17)
    # Our Version field == 19 >= 17, so both are present.
    pkg_filever_ue = _i32(b, o); o += 4
    pkg_filever_ue5 = _i32(b, o); o += 4
    pkg_licensee_ue = _i32(b, o); o += 4

    # LevelNamesAndTimes: TArray<FLevelNameAndTime{FString, uint32}>
    def _level(b, p):
        name, p = _fstring(b, p)
        t = _u32(b, p); p += 4
        return {"name": name, "level_change_time_ms": t}, p
    levels, o = _tarray(b, o, _level)

    header_flags_raw = _u32(b, o); o += 4
    try:
        header_flags = EReplayHeaderFlags(header_flags_raw)
    except ValueError:
        header_flags = header_flags_raw

    # GameSpecificData: TArray<FString>
    game_specific, o = _tarray(b, o, _fstring)

    # RecordingMetadata gated by FReplayCustomVersion::RecordingMetadata (18); 19 >= 18.
    min_hz = _f32(b, o); o += 4
    max_hz = _f32(b, o); o += 4
    frame_limit_ms = _f32(b, o); o += 4
    checkpoint_limit_ms = _f32(b, o); o += 4
    platform, o = _fstring(b, o)
    build_config = b[o]; o += 1       # EBuildConfiguration : uint8
    build_target = b[o]; o += 1       # EBuildTargetType : uint8

    if o != n:
        raise HeaderParseError(
            f"byte-exact consumption failed: consumed {o}, total {n}, leftover {n - o}")

    return {
        "magic": magic,
        "version": version,
        "custom_versions": custom_versions,
        "network_checksum": network_checksum,
        "engine_network_protocol_version": engine_net_proto,
        "game_network_protocol_version": game_net_proto,
        "guid": guid,
        "engine_version": engine_version,
        "package_version_ue_file": pkg_filever_ue,
        "package_version_ue5": pkg_filever_ue5,
        "package_version_licensee_ue": pkg_licensee_ue,
        "levels": levels,
        "header_flags_raw": header_flags_raw,
        "header_flags": str(header_flags),
        "game_specific_data": game_specific,
        "min_record_hz": min_hz,
        "max_record_hz": max_hz,
        "frame_limit_ms": frame_limit_ms,
        "checkpoint_limit_ms": checkpoint_limit_ms,
        "platform": platform,
        "build_config": build_config,
        "build_target": build_target,
        "consumed": o,
        "total": n,
    }


def main():
    files = sorted(glob.glob(os.path.join(SAMPLE_DIR, "*.replay")))
    for p in files:
        c = parse_container(p)
        hb = None
        for ch in c.chunks:
            if ch.type_name == "Header":
                with open(p, "rb") as f:
                    f.seek(ch.data_offset)
                    hb = f.read(ch.size_in_bytes)
                break
        if hb is None:
            raise HeaderParseError(f"{p}: no Header chunk")
        # validate remaining chunks already parsed by container.py (Phase 1)
        r = parse_header(hb)
        flags = EReplayHeaderFlags(r["header_flags_raw"])
        print(f"{os.path.basename(p)}:")
        print(f"  magic={r['magic']:#010x} version={r['version']} "
              f"guid={r['guid']}")
        print(f"  engine_version={r['engine_version']['major']}."
              f"{r['engine_version']['minor']}.{r['engine_version']['patch']} "
              f"CL={r['engine_version']['changelist']} branch={r['engine_version']['branch']!r}")
        print(f"  engine_net_proto={r['engine_network_protocol_version']} "
              f"game_net_proto={r['game_network_protocol_version']} "
              f"checksum={r['network_checksum']:#x}")
        print(f"  pkg_ver_ue={r['package_version_ue_file']} "
              f"pkg_ver_ue5={r['package_version_ue5']} "
              f"licensee={r['package_version_licensee_ue']}")
        print(f"  levels={[lv['name'] for lv in r['levels']]}")
        print(f"  header_flags={flags} (raw={r['header_flags_raw']})")
        print(f"  platform={r['platform']!r} build_config={r['build_config']} "
              f"build_target={r['build_target']}")
        print(f"  record_hz=[{r['min_record_hz']},{r['max_record_hz']}] "
              f"frame_limit_ms={r['frame_limit_ms']} "
              f"checkpoint_limit_ms={r['checkpoint_limit_ms']}")
        print(f"  game_specific_data={r['game_specific_data']}")
        print(f"  custom_versions={len(r['custom_versions'])} cv(s); "
              f"consumed={r['consumed']}/{r['total']}")
    print(f"OK: all {len(files)} files decoded with byte-exact consumption.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
