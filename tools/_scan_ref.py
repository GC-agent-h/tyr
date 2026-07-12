
import glob, os, sys
HERE="/home/gcurr/tyr/tools"
sys.path.insert(0, HERE)
from container import parse_container
from bitreader import BitReader
from iris_handles import read_net_object_reference

def looks_like_path(s):
    if not isinstance(s,str): return False
    s=s.rstrip("\x00")
    if not (4<=len(s)<=200): return False
    return all(32<=ord(c)<127 for c in s) and s.strip()!=""

path="/home/gcurr/tyr/sample/TyrReplay2.replay"
c=parse_container(path)
# first Checkpoint chunk
ch=[x for x in c.chunks if x.type_name=="Checkpoint"][0]
with open(path,"rb") as f:
    f.seek(ch.data_offset); data=f.read(ch.size_in_bytes)
print("checkpoint size", len(data))
hits=[]
for bit in range(0, len(data)*8-40):
    r=BitReader(data); r.seek_bits(bit)
    try:
        ref=read_net_object_reference(r)
    except Exception:
        continue
    if ref.handle.is_valid and ref.is_exported and ref.path_payload and looks_like_path(ref.path_payload):
        o=""
        if ref.outer and ref.outer.handle.is_valid:
            o=ref.outer.handle.to_compact_string()
        hits.append((bit, ref.handle.raw_id, ref.handle.is_dynamic, ref.path_payload.rstrip(chr(0)), o))
        if len(hits)>=15: break
print("dynamic-ref hits (bit-offset, raw_id, is_dynamic, path, outer):")
for h in hits[:15]:
    print("  ", h)
print("total hits found (capped 15):", len(hits))
