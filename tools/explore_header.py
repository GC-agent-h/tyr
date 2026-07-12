"""explore_header.py — Phase 02 empirical inspection of the Header chunk.

Extracts the `Header` chunk (type 0) from each sample .replay and dumps
raw bytes + a structured hex/ascii view so we can derive the real
FNetworkDemoHeader layout from evidence (per SOUL.md: observe before
naming). Does NOT claim field semantics; just presents the bytes.
"""

import glob
import os
import struct

from tools.container import parse_container, FILE_MAGIC

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_DIR = os.path.join(REPO, "sample")


def find_header_chunk(path):
    c = parse_container(path)
    for ch in c.chunks:
        if ch.type_name == "Header":
            with open(path, "rb") as f:
                f.seek(ch.data_offset)
                return c, ch, f.read(ch.size_in_bytes)
    return c, None, None


def hexdump(b, start=0, maxlen=None):
    if maxlen:
        b = b[:maxlen]
    out = []
    for i in range(0, len(b), 16):
        chunk = b[i:i + 16]
        hexs = " ".join(f"{x:02x}" for x in chunk)
        asc = "".join(chr(x) if 32 <= x < 127 else "." for x in chunk)
        out.append(f"{start + i:08x}  {hexs:<47}  {asc}")
    return "\n".join(out)


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def i32(b, o):
    return struct.unpack_from("<i", b, o)[0]


def i64(b, o):
    return struct.unpack_from("<q", b, o)[0]


def fstring(b, o):
    slen = i32(b, o)
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
    return raw.decode("latin-1", "replace"), o


def describe(b):
    """Walk the header with candidate interpretation. Print findings."""
    print(f"  total bytes: {len(b)}")
    off = 0
    # Candidate 1: EngineNetworkVersion (int32) and GameNetworkVersion (int32)
    # In UE5, FNetworkDemoHeader::Serialize writes:
    #   int32 EngineNetworkVersion = GEngineNetVersion
    #   int32 GameNetworkVersion   = GGameNetVersion
    # then EReplayVersionHistory ReplayHeaderVersion (int32)
    if len(b) >= 12:
        eng = i32(b, 0)
        gam = i32(b, 4)
        rev = i32(b, 8)
        print(f"  [0]  EngineNetworkVersion(int32) = {eng}  (0x{eng:08x})")
        print(f"  [4]  GameNetworkVersion(int32)   = {gam}  (0x{gam:08x})")
        print(f"  [8]  ReplayHeaderVersion(int32)  = {rev}  (0x{rev:08x})")
        off = 12
    # Candidate: HeaderFlags uint32 (EReplayHeaderFlags)
    if len(b) >= off + 4:
        flags = u32(b, off)
        print(f"  [{off}] HeaderFlags(uint32)        = {flags}  (0x{flags:08x})")
        off += 4
    # Candidate: Guid FGuid (16 bytes)
    if len(b) >= off + 16:
        g = b[off:off + 16]
        print(f"  [{off}] Guid(FGuid 16B)            = {g.hex()}")
        off += 16
    # Candidate: LevelNamesAndTimes TArray<FLevelNameAndTime>
    # where FLevelNameAndTime = FString LevelName + int32 LevelChangeTimeInMS
    if len(b) >= off + 4:
        nlv = i32(b, off)
        print(f"  [{off}] LevelCount(int32)          = {nlv}")
        off += 4
        for k in range(max(nlv, 0)):
            if len(b) < off + 4:
                break
            name, off = fstring(b, off)
            if len(b) < off + 4:
                break
            t = i32(b, off)
            off += 4
            print(f"        level[{k}] name={name!r} time_ms={t}")
    # Remaining bytes
    print(f"  consumed so far: {off} / {len(b)}; remaining {len(b)-off} bytes:")
    if off < len(b):
        print(hexdump(b[off:], start=off))


def main():
    for path in sorted(glob.glob(os.path.join(SAMPLE_DIR, "*.replay"))):
        c, ch, data = find_header_chunk(path)
        if ch is None:
            print(f"=== {os.path.basename(path)}: NO HEADER CHUNK ===")
            continue
        print(f"=== {os.path.basename(path)} ===")
        print(f"  header chunk: data_off={ch.data_offset} size={ch.size_in_bytes}")
        print(hexdump(data))
        print("  --- candidate interpretation ---")
        describe(data)
        print()


if __name__ == "__main__":
    main()
