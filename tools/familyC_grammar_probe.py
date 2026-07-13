"""
familyC_grammar_probe.py — characterize Family-C (pl[1] in 08-0b) INTERNAL frame
and TEST candidate sub-entry grammars for a NON-TAUTOLOGICAL self-validation:
greedy parse must consume exactly to the terminal 00 with 0 leftover bytes.

Two structural hypotheses tested:
  H1 (prefix): the first 12 bytes of pl[2:] are a per-channel CONSTANT
      (expect << distinct prefixes than records; random 2^96 impossible).
  H2 (sub-entry grammar): after the 12B prefix, the tail is a sequence of
      typed sub-entries that consume exactly to the terminal 00.

Grammar hypotheses by subtype (from dumps):
  0x09: 08 u8 04 80 u8 4b 00   (8B)   [array of indexed sub-components]
  0x08: 82 ?? ...              (variable; probe)
  0x0a: c0 ...                 (variable; probe)
  0x0b: mixed small; probe

We measure greedy-consume-to-terminal pass% for each tested grammar.
ALL OBSERVATION.
"""
from __future__ import annotations
import sys, glob
from collections import Counter, defaultdict
import container as container_mod
import frame_walk as fw
import carrier_decode as cd

PREFIX = 12  # hypothesis: first 12 bytes of pl[2:] constant per channel

GRAMMARS = {
    0x09: [("fixed8", b"\x08", 1), ("u8", None, 1), ("const", b"\x04\x80", 2),
           ("u8", None, 1), ("const", b"\x4b\x00", 2)],
}


def greedy_consume(tail: bytes, grammar) -> bool:
    """Return True if `tail` is fully consumed by `grammar` with 0 leftover.
    grammar = list of (kind, literal_or_None, size). kind 'fixed' = literal
    must match; 'u8'/'u16' = consume N bytes of arbitrary data."""
    i = 0
    n = len(tail)
    for kind, lit, sz in grammar:
        if i + sz > n:
            return False
        if kind == "const" and tail[i:i + sz] != lit:
            return False
        i += sz
    return i == n  # exactly consumed, no leftover


def main(argv):
    files = argv[1:] or sorted(glob.glob("sample/*.replay"))
    prefix_counts = {st: Counter() for st in (0x08, 0x09, 0x0a, 0x0b)}
    g09_total = g09_pass = 0
    for path in files:
        c = container_mod.parse_container(path)
        rep = [ch for ch in c.chunks if ch.type_name == "ReplayData"]
        raw = open(path, "rb").read()
        for ch in rep:
            data = raw[ch.data_offset: ch.data_offset + ch.size_in_bytes]
            ar = fw.ByteArchive(data)
            ar.bytes(16)
            while not ar.at_end() and (len(data) - ar.tell()) >= 12:
                fstart = ar.tell()
                try:
                    fr, _ = fw.read_frame(ar, False, False)
                except Exception:
                    break
                if fr is None or ar.tell() <= fstart:
                    break
                for pkt in fr.packets:
                    for b in pkt.bunches:
                        pl = b.reassembled_payload
                        if not pl or len(pl) < 3:
                            continue
                        if pl[1] not in prefix_counts or pl[-1] != 0x00:
                            continue
                        st = pl[1]
                        content = pl[2:-1]
                        if len(content) < PREFIX:
                            continue
                        prefix_counts[st][content[:PREFIX].hex()] += 1
                        if st == 0x09:
                            g09_total += 1
                            if greedy_consume(content[PREFIX:],
                                              GRAMMARS[0x09]):
                                g09_pass += 1
    for st in (0x08, 0x09, 0x0a, 0x0b):
        pc = prefix_counts[st]
        tot = sum(pc.values())
        nd = len(pc)
        top = pc.most_common(3)
        print(f"subtype 0x{st:02x}: records={tot} distinct_12B_prefix={nd} "
              f"top_prefixes(hex:n)={top}")
    if g09_total:
        print(f"\n0x09 grammar '08 u8 04 80 u8 4b 00' consume-to-terminal: "
              f"{g09_pass}/{g09_total} = {100.0*g09_pass/g09_total:.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
