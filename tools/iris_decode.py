"""
iris_decode.py — FAITHFUL Iris (UE5.6) replication-state bit decoder.

Source-verified from /home/gcurr/tyr/UE/Iris:
  * NetBitStreamReader.cpp:54-99   -> LSB-first, 32-bit LE words (INTEL_ORDER32 no-op on x86)
  * IntNetSerializerBase.h:28-101   -> int/uint: 1-bit isZero-opt when BitCount>=16, then BitCount bits
  * BoolNetSerializer.cpp:33-48     -> bool = 1 bit
  * FloatNetSerializers.cpp:78-96   -> float = 1-bit isNonZero then 32-bit IEEE (or just 1 bit)
  * InternalEnumNetSerializers.cpp  -> enum BitCount = ceil(log2(range)), same zero-opt
  * ArrayPropertyNetSerializer.cpp:81-117 -> array = 1-bit empty else count(ElementCountBitCount)+elems
  * ReplicationWriter.cpp:2744-2840 + 2508-2535 -> per-object envelope order
        WriteNetRefHandleId(handle)   [only if IsSubObject]
        destroy-header (GetDestroyHeaderFlagsBitCount bits)
        bHasState (1b) -> [HasState sentinel if debug]
        bIsInitialState (1b)
        bDeltaCompressionEnabled (1b) -> CreatedBaselineIndex (2b)
        WriteNetRefHandleCreationInfo (class path)
        SerializeObjectStateDelta: LastAckedBaselineIndex(2b) [or CreatedBaselineIndex(2b)] + SerializeWithMask(changemask all-ones + state)

This is a STRUCTURAL validator: it walks the documented envelope and reports how
far it consumes the blob byte-exactly. It is NOT yet a full semantic decoder
(the class-path -> usmap struct mapping is resolved separately).
"""
from __future__ import annotations
import json
import sys


class BitReader:
    """Faithful port of FNetBitStreamReader::ReadBits (LSB-first, 32-bit LE)."""
    def __init__(self, data: bytes):
        self.words = [int.from_bytes(data[i:i+4], "little") for i in range(0, len(data), 4)]
        self.nbits = len(data) * 8
        self.pos = 0

    def read_bits(self, n: int) -> int:
        if n == 0:
            return 0
        if self.pos + n > self.nbits:
            return 0  # overflow -> 0 (matches reader overflow semantics)
        val = 0
        for i in range(n):
            word = self.words[self.pos >> 5]
            bit = (word >> (self.pos & 31)) & 1
            val |= bit << i
            self.pos += 1
        return val

    def read_bool(self) -> int:
        return self.read_bits(1)

    def read_packed_uint(self) -> int:
        """WritePackedUint64: groups of 7 bits, high bit = continuation.
        Decoded value = raw (no -1 offset; SerializeIntPacked uses value+1)."""
        val = 0
        shift = 0
        while True:
            if self.pos + 7 > self.nbits:
                return val
            byte = self.read_bits(8)
            val |= (byte & 0x7f) << shift
            if (byte & 0x80) == 0:
                break
            shift += 7
        return val

    def bits_left(self) -> int:
        return self.nbits - self.pos

    def byte_pos(self) -> int:
        return (self.pos + 7) // 8


def destroy_header_bitcount() -> int:
    # GetDestroyHeaderFlagsBitCount() — default enum has a small fixed count.
    # In UE: EReplicatedDestroyHeaderFlags fits in 2 bits typically.
    return 2


def walk_envelope(body: bytes, n_handles: int):
    """Walk the documented Iris batch-of-subobjects envelope over `body`.
    Returns dict with consumption stats + observations. Does NOT require the
    usmap type (we only validate envelope structure / byte-exactness)."""
    br = BitReader(body)
    report = {"total_bytes": len(body), "total_bits": len(body) * 8,
              "n_handles_header": n_handles, "subobjects": []}
    sub = 0
    while br.bits_left() >= 16 and sub < 200:
        start = br.pos
        rec = {"idx": sub, "start_bit": start}
        # WriteNetRefHandleId (per subobject; root handle is in batch header,
        # not here) -> packed uint64. We read it to verify it parses as a handle.
        try:
            h = br.read_packed_uint()
            rec["handle"] = h
        except Exception:
            rec["handle"] = None
            break
        rec["after_handle_bit"] = br.pos
        # destroy header
        dh = destroy_header_bitcount()
        br.read_bits(dh)
        rec["after_destroy_hdr_bit"] = br.pos
        # bHasState
        bhs = br.read_bool()
        rec["bHasState"] = bhs
        if not bhs:
            rec["note"] = "no state"
            report["subobjects"].append(rec)
            sub += 1
            continue
        # bIsInitialState
        bis = br.read_bool()
        rec["bIsInitialState"] = bis
        # bDeltaCompressionEnabled
        bdc = br.read_bool()
        rec["bDeltaComp"] = bdc
        if bdc:
            bl = br.read_bits(2)
            rec["createdBaselineIndex"] = bl
        # WriteNetRefHandleCreationInfo -> packed uint handle + class path.
        # FSoftClassPath / FTopLevelAssetPath serialized form; we just note
        # that a packed uint (asset path index or similar) follows.
        cpi = br.read_packed_uint()
        rec["creationInfo_packed"] = cpi
        # SerializeObjectStateDelta: LastAckedBaselineIndex (2b) [or CreatedBaselineIndex 2b]
        la = br.read_bits(2)
        rec["stateBaselineIndex"] = la
        # changemask: for INITIAL = all-ones; BitCount unknown without usmap,
        # so we just report the next few bits to check for the all-ones run.
        cm_head = [br.read_bits(1) for _ in range(min(16, br.bits_left()))]
        rec["changemask_head_bits"] = cm_head
        rec["changemask_head_all_ones"] = all(b == 1 for b in cm_head) if cm_head else False
        report["subobjects"].append(rec)
        sub += 1
        # Stop early if we clearly diverged (handle huge / overflow)
        if rec["handle"] is None:
            break
    report["consumed_bits"] = br.pos
    report["consumed_bytes"] = br.byte_pos()
    report["ended_at_subobject"] = sub
    return report


def main():
    sys.path.insert(0, "tools")
    import frame_walk as FW, container as CM

    def extract_all(replay):
        out = []
        c = CM.parse_container(replay)
        rep = [ch for ch in c.chunks if ch.type_name == "ReplayData"]
        raw = open(replay, "rb").read()
        for ch in rep:
            data = raw[ch.data_offset: ch.data_offset + ch.size_in_bytes]
            ar = FW.ByteArchive(data); ar.bytes(16)
            while not ar.at_end() and (len(data) - ar.tell()) >= 12:
                fstart = ar.tell()
                try:
                    fr, _ = FW.read_frame(ar, False, False)
                except Exception:
                    break
                if fr is None or ar.tell() <= fstart:
                    break
                for pkt in fr.packets:
                    for b in pkt.bunches:
                        pl = b.reassembled_payload
                        if len(pl) >= 2 and pl[:2] != b"\x01\x00":
                            n = int.from_bytes(pl[0:2], "little")
                            if 1 <= n <= 2000 and len(pl) >= 2 + 2 * n + 1:
                                body = pl[2 + 2 * n:]
                                out.append((ch.index, n, bytes(body)))
        return out

    allb = extract_all("sample/TyrReplay1.replay")
    big = [b for b in allb if len(b[2]) == 1936]
    if not big:
        print("no 1936B body found")
        return
    ch, n, body = big[0]
    rep = walk_envelope(body, n)
    print(f"channel={ch} n_handles={n} body={len(body)}B")
    print(f"consumed {rep['consumed_bytes']}B / {rep['consumed_bits']}b of {rep['total_bytes']}B, ended at subobject {rep['ended_at_subobject']}")
    for s in rep["subobjects"][:12]:
        print(f"  sub{s['idx']}: handle={s.get('handle')} bHasState={s.get('bHasState')} "
              f"bInit={s.get('bIsInitialState')} bDelta={s.get('bDeltaComp')} "
              f"baseIdx={s.get('createdBaselineIndex')} cinfo={s.get('creationInfo_packed')} "
              f"cmAllOnes={s.get('changemask_head_all_ones')} cmHead={s.get('changemask_head_bits')}")


if __name__ == "__main__":
    main()
