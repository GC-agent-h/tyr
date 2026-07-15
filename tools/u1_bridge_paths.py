#!/usr/bin/env python3
"""Extract embedded class-path FStrings from bOpen spawn bunches in TyrReplay1.
UE writes the actor class as SerializeObject -> for an unresolved object it emits
an FString path (int32 len, bytes, optional). Scan each bOpen bunch payload for
ASCII runs that look like UE class paths (/Game/..., /Script/..., BP_*, .BP_..._C).
Also parse the standard UE spawn layout: bOpen bunch payload = [bIsActor?]
SerializeNewActor writes: uint8 bServer; Ar<<SpawnData; SpawnData = bSingleClient,
bStatic, bRemoteRole, etc. then ActorClassName via SerializeObject. We look for the
FString directly to recover the handle->class binding non-tautologically."""
from __future__ import annotations
import os, sys, re
sys.path.insert(0, os.path.dirname(__file__))
import frame_walk as FW
import container as CM

f = "sample/TyrReplay1.replay"
c = CM.parse_container(f)
rep = [ch for ch in c.chunks if ch.type_name == "ReplayData"]
raw = open(f, "rb").read()
path_re = re.compile(rb"[/A-Za-z0-9_\.]{6,80}")
seen = {}
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
                if not (b.b_control and b.b_open):
                    continue
                pl = b.reassembled_payload
                # find ascii path-like runs
                for m in path_re.finditer(pl):
                    s = m.group()
                    if b"/" in s or s.startswith(b"BP_") or b".BP_" in s or s.endswith(b"_C"):
                        seen.setdefault(s, 0)
                        seen[s] += 1
print(f"distinct path-like tokens in bOpen bunches: {len(seen)}")
for s, n in sorted(seen.items(), key=lambda kv: -kv[1])[:40]:
    print(f"  {n:4d}  {s.decode('latin1')}")
