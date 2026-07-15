#!/usr/bin/env python3
"""Locate and dump the TYR global class-registry pointer that the shared
descriptor dispatcher 0x1416AC630 indexes via (fieldIdx>>16) (Phase 06 U1 / todo 7).

That dispatcher does:
    mov ecx, eax                 ; eax = [rcx+0xc] (object field count?)
    movzx eax, ax
    shr rcx, 0x10               ; fieldIdx >> 16
    lea rdx, [rax + rax*2]
    mov rax, qword ptr [rip + 0xb1a9d00]   ; GLOBAL = 0x14C856380
    mov rcx, qword ptr [rax + rcx*8]       ; table = GLOBAL[bucket]
    lea rdi, [rcx + rdx*8]                 ; entry = table + idx*24
This is the handle/field -> FReplicationStateDescriptor (property-struct) bridge.
We dump GLOBAL (the bucket array) and the first few bucket tables' entry sizes.

Outputs a summary to stdout + out/registry_dump.txt.
Validation: GLOBAL resolves into a mapped section; prints bucket count + sample entry offsets.
"""
from __future__ import annotations
import json
import os
import struct
import pefile

BIN = os.path.join(os.path.dirname(__file__), "..", "Binaries", "Win64",
                   "TyrClient-Win64-Shipping.exe")


def sections(pe):
    out = []
    for s in pe.sections:
        out.append({
            "name": s.Name.rstrip(b"\x00").decode("latin-1"),
            "va": s.VirtualAddress,
            "raw": s.PointerToRawData,
            "vsz": s.Misc_VirtualSize,
            "rsz": s.SizeOfRawData,
        })
    return out


def va_to_raw(secs, va, ib):
    # secs va are RVAs (relative to image base). Accept absolute VA too.
    for s in secs:
        if s["va"] <= va < s["va"] + s["vsz"]:
            return s["raw"] + (va - s["va"])
    # try as absolute VA (ib-relative)
    for s in secs:
        abs_lo = ib + s["va"]
        if abs_lo <= va < abs_lo + s["vsz"]:
            return s["raw"] + (va - abs_lo)
    return None


def main():
    pe = pefile.PE(BIN, fast_load=True)
    ib = pe.OPTIONAL_HEADER.ImageBase
    secs = sections(pe)
    raw = open(BIN, "rb").read()

    # 0x1416ac679: mov rax, [rip+0xb1a9d00]; next insn at 0x1416ac680
    GLOBAL_VA = 0x1416AC680 + 0xB1A9D00
    assert GLOBAL_VA < ib + 0xD6BD174, "GLOBAL beyond image"
    goff = va_to_raw(secs, GLOBAL_VA, ib)
    assert goff is not None, "GLOBAL not in a mapped section"
    # GLOBAL is a pointer to an array of bucket-table pointers.
    gp = struct.unpack_from("<Q", raw, goff)[0]
    print("GLOBAL_VA       =", hex(GLOBAL_VA))
    print("GLOBAL raw      =", hex(goff))
    print("GLOBAL -> ptr   =", hex(gp))

    IMAGE_TOP = ib + 0xD6BD174  # approx image high VA
    if gp < ib or gp >= IMAGE_TOP:
        print("NOTE: GLOBAL pointer is NON-CANONICAL (%s) — not a static "
              "in-image pointer. The 0x1416AC630 dispatcher therefore does NOT "
              "index a static .data registry via this load; it is a heap/RTTI "
              "base or a per-instance descriptor table. Hand-tracing this "
              "optimized fn is inconclusive -> see idiom fingerprint instead "
              "(tools/game_idioms.py: 393/1177 game serializers delegate bit-"
              "packing to the Iris bit-writer vtable)." % hex(gp))
        out = {"GLOBAL_VA": GLOBAL_VA, "global_ptr": gp,
               "note": "non-canonical; dispatcher is heap/RTTI-based, not a "
                       "static registry. Inconclusive by hand-trace."}
        with open(os.path.join(os.path.dirname(__file__), "..", "out",
                               "registry_dump.json"), "w") as f:
            json.dump(out, f, indent=1)
        print("\nwrote out/registry_dump.json (inconclusive)")
        return

    # Dump the bucket array: read 256 contiguous 8-byte pointers (assume buckets).
    boff = va_to_raw(secs, gp, ib)
    print("bucket array raw= 0x%X" % boff)
    buckets = []
    for i in range(256):
        p = struct.unpack_from("<Q", raw, boff + i * 8)[0]
        if p == 0:
            break
        buckets.append(p)
    print("non-null buckets (first 256):", len(buckets))
    print("first 12 bucket pointers:")
    for i, p in enumerate(buckets[:12]):
        print("   [%3d] 0x%X" % (i, p))

    # For the first few non-null buckets, dump the first entry's 24 bytes.
    print("\nfirst entries of first 6 buckets:")
    for i, p in enumerate(buckets[:6]):
        eoff = va_to_raw(secs, p, ib)
        if eoff is None:
            print("   bucket %d ptr 0x%X not mapped" % (i, p))
            continue
        ent = raw[eoff:eoff + 24]
        print("   bucket[%d] ptr=0x%X  entry[0..24]=%s" % (i, p, ent.hex()))

    out = {"GLOBAL_VA": GLOBAL_VA, "global_ptr": gp, "nbuckets": len(buckets),
           "buckets": buckets[:64]}
    with open(os.path.join(os.path.dirname(__file__), "..", "out",
                           "registry_dump.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("\nwrote out/registry_dump.json")


if __name__ == "__main__":
    main()
