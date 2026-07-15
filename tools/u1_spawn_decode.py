#!/usr/bin/env python3
"""Decode a bOpen spawn bunch (ch=51, L=843) as UE5.6 SerializeNewActor bit
stream, to recover the actor class path. Reproduces UActorChannel::ProcessBunch
spawn layout (DataChannel.cpp). Bits LSB-first (FBitReader)."""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import frame_walk as FW
import container as CM


class BitR:
    def __init__(self, data: bytes):
        self.b = data
        self.pos = 0
    def bit(self):
        byte = self.b[self.pos >> 3]
        v = (byte >> (self.pos & 7)) & 1
        self.pos += 1
        return v
    def bits(self, n):
        v = 0
        for i in range(n):
            v |= self.bit() << i
        return v
    def align(self):
        if self.pos & 7:
            self.pos += 8 - (self.pos & 7)
    def int32(self):
        self.align()
        v = int.from_bytes(self.b[self.pos >> 3: (self.pos >> 3) + 4], "little")
        self.pos += 32
        return v
    def fstr(self):
        self.align()
        L = self.int32()
        if L == 0:
            return ""
        if L < 0:
            L = -L
        s = self.b[self.pos >> 3: (self.pos >> 3) + L].decode("latin1", "replace")
        self.pos += L * 8
        return s
    def tellbits(self):
        return self.pos


def main():
    f = "sample/TyrReplay1.replay"
    c = CM.parse_container(f)
    rep = [ch for ch in c.chunks if ch.type_name == "ReplayData"]
    raw = open(f, "rb").read()
    target = None
    for ch in rep:
        data = raw[ch.data_offset: ch.data_offset + ch.size_in_bytes]
        ar = FW.ByteArchive(data)
        ar.bytes(16)
        while not ar.at_end() and (len(data) - ar.tell()) >= 12:
            before = ar.tell()
            try:
                fr, _ = FW.read_frame(ar, False, False)
            except Exception:
                break
            if fr is None or ar.tell() <= before:
                break
            for pkt in fr.packets:
                for b in pkt.bunches:
                    if b.b_control and b.b_open and len(b.reassembled_payload) == 843:
                        target = b.reassembled_payload
    if target is None:
        print("ch51 payload not found (maybe not exactly 843)")
        return
    br = BitR(target)
    print(f"payload {len(target)}B ({len(target)*8}b)")
    # SerializeNewActor: bunch already past header. Typical field order:
    #  - bSpawn (1 bit) [actor channel]
    #  - SpawnData: bSingleClient,bStatic,bRootComponentFromReplication,bRemoteRole,
    #               bControl, bHidden, bTearOff (bunch of bools)
    #  - Role: ENetRole (3 bits), RemoteRole: ENetRole (3 bits)
    #  - SerializeObject(ActorClass) -> if unresolved: 1 bit valid, then FString path
    # We'll just walk and try to find an FString class path after some bools.
    # Decode first 64 bool bits
    bools = [br.bit() for _ in range(64)]
    print("first 64 bits:", "".join(map(str, bools)))
    # Try SerializeObject at several bit offsets: it's 1 valid-bit; if valid and
    # exporting, then FString. Scan offsets 0..200 for an aligned FString path.
    best = []
    for off in range(0, min(len(target)*8, 400)):
        br.pos = off
        try:
            valid = br.bit()
            if not valid:
                continue
            # SerializeObject: after valid bit: bIsExport, then if export: path FString
            is_export = br.bit()  # often bNetGUIDIsExported
            if is_export:
                p = br.fstr()
                if p and ("/" in p or p.endswith("_C") or "BP_" in p or "Actor" in p):
                    best.append((off, p))
        except Exception:
            continue
    print(f"class-path candidates found: {len(best)}")
    for off, p in best[:15]:
        print(f"  off={off}b  path={p}")


if __name__ == "__main__":
    main()
