"""
Phase 06 t7 handoff validation: locate the Iris DataStreamManager region.

ARCHITECTURE (proven from source this session):
  In UE5.6 Iris, replication does NOT ride inside legacy UChannel bunch
  payloads. Each connection packet buffer is:
       [legacy bunch stream ...][Iris DataStreamManager region]
  frame_walk's bunch loop stops at AtEnd() of the bunch stream, so the Iris
  region is the trailing residual bits in each packet buffer.

  This probe re-walks each packet buffer with the bunch reader, records the bit
  position where the bunch loop stops, slices the residual bytes, and feeds
  them to iris_datastream_manager.walk_manager. A packet "is Iris" if the
  residual decodes as a clean DataStreamManager region (StreamCount plausible,
  at least one active stream decodes as a valid replication envelope, and the
  region is consumed exactly to its end).

  We report, per packet, whether the residual is a clean Iris region, the
  StreamCount, and how many streams decoded as replication. If ANY packet's
  residual decodes cleanly, the handoff is validated: Iris lives in the
  post-bunch residual, exactly as the source says.
"""
import sys
sys.path.insert(0, 'tools')
import json
import frame_walk as fw
import container as container_mod
from bitreader import BitReader
from iris_datastream_manager import walk_manager


def scan_file(path: str) -> dict:
    c = container_mod.parse_container(path)
    raw = open(path, 'rb').read()
    out = {
        'file': container_mod.container_to_dict(c).get('name', path),
        'packets_with_residual': 0,
        'iris_clean_regions': 0,
        'iris_streams_found': 0,
        'residual_bit_hist': {},
        'first_iris': None,
        'errors': [],
    }
    for ci, ch in enumerate(c.chunks):
        if ch.type_name != 'ReplayData':
            continue
        data = raw[ch.data_offset:ch.data_offset + ch.size_in_bytes]
        ar = fw.ByteArchive(data)
        ar.bytes(16)  # chunk-level header (validated in phase05)
        while not ar.at_end() and (len(data) - ar.tell()) >= 12:
            fstart = ar.tell()
            try:
                fr, _ = fw.read_frame(ar, False, False)
            except Exception as e:  # noqa: BLE001
                out['errors'].append(f"chunk {ci}: {type(e).__name__}: {e}")
                break
            if fr is None or ar.tell() <= fstart:
                break
            for pkt in fr.packets:
                pkt_start = pkt.frame_byte_offset
                pkt_bytes = data[pkt_start:pkt_start + pkt.buffer_size]
                br = BitReader(pkt_bytes)
                # Re-walk the bunch stream to find where it ends.
                while br.tell_bits() < pkt.buffer_size * 8:
                    try:
                        _ = fw.read_bunch(br)
                    except fw.BitReaderEOF:
                        break
                residual_start = br.tell_bits()
                residual_bits = pkt.buffer_size * 8 - residual_start
                if residual_bits < 8:
                    continue
                out['packets_with_residual'] += 1
                out['residual_bit_hist'][str(residual_bits)] = out['residual_bit_hist'].get(str(residual_bits), 0) + 1
                residual = br.serialize_bits(residual_bits)
                try:
                    info = walk_manager(residual)
                except Exception:  # noqa: BLE001
                    continue
                if (not info.overflow and info.stream_count >= 1
                        and any(s.is_replication for s in info.streams)
                        and info.consumed_bits == info.total_bits):
                    out['iris_clean_regions'] += 1
                    nrep = sum(1 for s in info.streams if s.is_replication)
                    out['iris_streams_found'] += nrep
                    if out['first_iris'] is None:
                        out['first_iris'] = {
                            'chunk': ci, 'frame_byte': fr.start_byte,
                            'pkt_byte': pkt_start, 'residual_start_bit': residual_start,
                            'residual_bits': residual_bits,
                            'stream_count': info.stream_count,
                            'replication_streams': nrep,
                        }
    return out


def main(argv):
    files = argv[1:] or ['sample/TyrReplay1.replay']
    results = []
    for f in files:
        try:
            r = scan_file(f)
        except Exception as e:  # noqa: BLE001
            r = {'file': f, 'error': f"{type(e).__name__}: {e}"}
        results.append(r)
        print(json.dumps(r, indent=1))
    total_clean = sum(r.get('iris_clean_regions', 0) for r in results if 'error' not in r)
    total_pkts = sum(r.get('packets_with_residual', 0) for r in results if 'error' not in r)
    print(f"\nAGGREGATE: {total_pkts} packets had post-bunch residual; "
          f"{total_clean} decoded as clean Iris DataStreamManager regions.")
    if total_clean > 0:
        print("VERDICT: Iris DataStreamManager region LOCATED in post-bunch residual. Handoff t7 VALIDATED.")
    else:
        print("VERDICT: no clean Iris region found in post-bunch residual. Handoff NOT yet validated.")


if __name__ == '__main__':
    main(sys.argv)
