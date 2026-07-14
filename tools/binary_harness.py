"""Binary disassembly harness for TYR's Iris replication carrier.

Goal: locate, in the 220 MB Shipping `TyrClient-Win64-Shipping.exe`, the code
that SERIALIZES the actor-channel bunch payload (the Family-A/E spawn body), so
we can recover the exact wire framing (member order + NetSerializer widths +
leading record structure) that the naive u1_decode.py could not guess.

Strategy (symbol-stripped Shipping build):
  1. Parse PE with pefile -> get section VA/RVA/SIZE, find .text.
  2. Use embedded PDB path strings ("D:\\HordeAgent\\...\\Iris\\...\\X.cpp")
     as *module landmarks*. Each path string sits near the code region compiled
     from that .cpp, giving us a coarse location for ReplicationReader.cpp,
     ReplicationProtocolOperations.cpp, etc.
  3. Disassemble candidate regions with capstone (x86-64) and scan for the
     tell-tale Iris serialization idioms:
       - ReadIntPacked / variable-length int loops (SHL+OR, REX-prefixed)
       - BitReader reads (TEST byte, SHR/AND masks)
       - struct-field offset arithmetic consistent with a generated
         FReplicationStateDescriptor (fixed stride per member).
"""
from __future__ import annotations
import os
import re
import sys
import pefile
import capstone

BIN = os.path.join(os.path.dirname(__file__), "..", "Binaries", "Win64",
                   "TyrClient-Win64-Shipping.exe")


def load_pe(path: str = BIN):
    return pefile.PE(path, fast_load=True)


def section_map(pe):
    out = []
    for s in pe.sections:
        name = s.Name.rstrip(b"\x00").decode("latin-1", "replace")
        out.append({
            "name": name,
            "vaddr": s.VirtualAddress,
            "vsize": s.Misc_VirtualSize,
            "raddr": s.PointerToRawData,
            "rsize": s.SizeOfRawData,
        })
    return out


def rva_to_raw(pe, rva, secs):
    for s in secs:
        if s["vaddr"] <= rva < s["vaddr"] + s["vsize"]:
            return s["raddr"] + (rva - s["vaddr"])
    return None


# Regex for embedded PDB-style source paths (single backslashes in PE)
PATH_RE = re.compile(
    rb"D:\\HordeAgent\\Sandbox\\\+\+Tyr\+release\+Incremental\\Sync\\"
    rb"Engine\\Source\\Runtime\\([A-Za-z0-9_]+)\\.*?\.cpp")


def find_module_landmarks(raw: bytes, secs, text_sec):
    """Return dict module_name -> sorted list of (rva, snippet) for embedded
    PDB path strings that fall inside .text."""
    results = {}
    for m in PATH_RE.finditer(raw):
        pos = m.start()
        # ensure near a .text region (approx): map pos->rva backwards
        # We stored raw offsets; for strings in .text the raw offset == rva offset
        # within that section. Just record raw pos + module.
        module = m.group(1).decode("latin-1")
        results.setdefault(module, []).append(pos)
    # keep only modules with multiple hits (real code regions)
    return {k: sorted(set(v)) for k, v in results.items() if len(v) >= 3}


def disassemble_region(raw, sec, start_raw, length, base_vaddr=None):
    if base_vaddr is None:
        base_vaddr = sec["vaddr"] + (start_raw - sec["raddr"])
    code = raw[start_raw: start_raw + length]
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    out = []
    for ins in md.disasm(code, base_vaddr):
        out.append((ins.address, ins.mnemonic, ins.op_str))
    return out


# Iris serialization idiom scanners -------------------------------------------------
def count_intpacked_loops(instrs):
    """ReadIntPacked idiom: loop reading 7-bit groups, shifting. Approximate by
    counting SHL/OR + conditional jump short patterns. Returns count of likely
    varint loops."""
    score = 0
    for i, (addr, mn, op) in enumerate(instrs):
        if mn == "shl" or mn == "shr":
            score += 1
    return score


def scan_for_call_targets(instrs, text_base, text_end):
    """Collect CALL targets inside .text (helps build the call graph toward the
    serialize function)."""
    targets = []
    for addr, mn, op in instrs:
        if mn == "call" and op.startswith("0x"):
            t = int(op, 16)
            if text_base <= t <= text_end:
                targets.append(t)
    return targets


if __name__ == "__main__":
    pe = load_pe()
    secs = section_map(pe)
    text = next(s for s in secs if s["name"] == ".text")
    print(f".text: vaddr=0x{text['vaddr']:x} vsize=0x{text['vsize']:x} "
          f"raw=0x{text['raddr']:x} rsize=0x{text['rsize']:x}")
    raw = open(BIN, "rb").read()
    landmarks = find_module_landmarks(raw, secs, text)
    print(f"module landmarks found: {len(landmarks)}")
    for mod, positions in sorted(landmarks.items(), key=lambda kv: -len(kv[1]))[:25]:
        # convert first raw pos to rva if inside .text raw range
        r0 = positions[0]
        if text["raddr"] <= r0 < text["raddr"] + text["rsize"]:
            rva0 = text["vaddr"] + (r0 - text["raddr"])
            print(f"  {mod:20} hits={len(positions):4} first_rva=0x{rva0:x}")
        else:
            print(f"  {mod:20} hits={len(positions):4} (first pos 0x{r0:x} outside .text)")
