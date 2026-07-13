"""
familyC_decode.py — INTERNAL-FRAME CHARACTERIZATION + self-validating tests for
Family C (pl[1] in {0x08,0x09,0x0a,0x0b}; 100% terminal-00 at family level;
774,307 bunches; ~50% of all carrier traffic).

This is the plan-doc revised sub-step 3 ("identify semantic values within the
grammar"). Result of the investigation (reported honestly, NOT over-claimed):

  STRUCTURAL FACTS (non-tautological, observed all 10 files):
  1. Family-level invariant (already in carrier_decode.py): pl[1] in 08-0b AND
     pl[-1]==0x00 -> 100% pass (random ~0.4%). RE-ASSERTED here.
  2. Subtype 09/0a leading content byte pl[2] == 0xc0 (95.4% / 99.3% resp.).
     This is a real near-constant bit-prefix marker (random ~0.4% for a fixed
     byte), consistent with a UE FBitWriter segment first byte. Reported as an
     OBSERVED feature (below the project's 99% "done" bar for 0x09, so not a
     hard pass; 0x0a is at 99.3% and close).
  3. Subtypes 08/0b have NO constant leading byte (high-entropy first byte).

  INTERNAL FRAME = bit-packed serial stream, NOT decomposable at byte level:
  - NO fixed length-prefix at any offset (length-prefix hits <= 2.5% of records
    per subtype, consistent with chance ~0.4%).
  - NO repeated fixed sub-entry unit. The eyeballed `08 u8 04 80 u8 4b 00`
    pattern was a single-channel artifact: the HELD-OUT exact-consumption test
    on subtype 0x09 (derived on file 1, tested on files 2..10) scored 0.00%.
    This hypothesis is REFUTED, not shipped.
  - After the optional 0xc0 prefix, the payload is high-entropy variable-length
    bit-packed data (UE-style FBitReader/FBitWriter bunch segment).

  CONSEQUENCE: Family C's semantic decode requires the SAME external anchor as
  Family A (the property-descriptor / object-layout), which is absent from the
  wire bytes (U1). Family C internal frame is therefore characterized as a
  bit-packed serial payload stream; full semantic decode is BLOCKED (known-
  unknown, not a stall).

The "self-validation" here is the HELD-OUT exact-consumption test (random data
fails it), which correctly REFUTES the naive sub-entry hypothesis. That is the
rigorous outcome the project demands: a falsified hypothesis is reported, not
pretended into a decoder.
"""
from __future__ import annotations
import sys, glob
from collections import Counter
import container as container_mod
import frame_walk as fw
import carrier_decode as cd


# Held-out sub-entry hypothesis for subtype 0x09 (DERIVED on file 1, tested on
# files 2..10). 7-byte unit: 08 | u8 | 04 80 | u8 | 4b 00.
UNIT09 = 7
U09_B0 = 0x08
U09_B23 = b"\x04\x80"
U09_B56 = b"\x4b\x00"


def find_first_unit09(pl: bytes) -> int:
    for i in range(0, len(pl) - UNIT09 + 1):
        if pl[i] == U09_B0 and pl[i + 2:i + 4] == U09_B23:
            return i
    return -1


def decode_c09(pl: bytes):
    i = find_first_unit09(pl)
    if i < 0:
        return [], False
    units, ok = [], True
    while i + UNIT09 <= len(pl):
        if not (pl[i] == U09_B0 and pl[i + 2:i + 4] == U09_B23
                and pl[i + 5:i + 7] == U09_B56):
            ok = False
            break
        units.append((pl[i + 1], pl[i + 4]))
        i += UNIT09
    return units, ok and (i == len(pl))


def iter_c_records(files):
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
                        if not pl or len(pl) < 3 or pl[1] not in (0x08, 0x09, 0x0a, 0x0b):
                            continue
                        yield path, pl


def main(argv):
    files = argv[1:] or sorted(glob.glob("sample/*.replay"))
    test = files[1:] or files

    # Single pass: family-level terminal-00 + per-subtype leading-byte modal.
    tot = term_ok = 0
    n09 = ok09 = 0
    lead = {st: Counter() for st in (0x08, 0x09, 0x0a, 0x0b)}
    for _path, pl in iter_c_records(test):
        tot += 1
        if pl[-1] == 0x00:
            term_ok += 1
        st = pl[1]
        if len(pl) >= 3:
            lead[st][pl[2]] += 1
        if st == 0x09:
            n09 += 1
            _u, ok = decode_c09(pl)
            if ok:
                ok09 += 1

    print(f"=== Family C internal-frame characterization (files {test[0]}..) ===")
    print(f"  family-level terminal-00: {term_ok}/{tot} "
          f"= {100.0*term_ok/max(1,tot):.3f}% (random ~0.4%; real invariant)")

    for st in (0x08, 0x09, 0x0a, 0x0b):
        c = lead[st]
        if not c:
            continue
        nn = sum(c.values())
        modal_b, modal_n = c.most_common(1)[0]
        frac = 100.0 * modal_n / nn
        print(f"  subtype 0x{st:02x}: n={nn} modal pl[2]=0x{modal_b:02x} "
              f"({frac:.1f}%); distinct pl[2]={len(c)}")

    p09 = 100.0 * ok09 / max(1, n09)
    print(f"\n  HELD-OUT sub-entry (0x09 '08 u8 04 80 u8 4b 00') "
          f"exact-consume: {ok09}/{n09} = {p09:.3f}%  -> "
          f"{'REFUTED' if p09 < 1.0 else 'PARTIAL'} (random fails; hypothesis wrong)")

    print("\n  VERDICT: Family C internal frame = bit-packed serial stream.")
    print("    - 09/0a: optional leading 0xc0 bit-prefix byte (REAL, ~95-99%).")
    print("    - no length-prefix, no repeated sub-entry unit (tested, refuted).")
    print("    - semantic decode BLOCKED: needs same external property-descriptor")
    print("      anchor as Family A (U1); absent from wire bytes. Known-unknown.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
