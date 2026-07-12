"""
build_sdk_xref.py — Phase 04 sub-step 5 deliverable: normalized SDK cross-reference
database, built once from out/sdk_index.json (the Dumper-7 dump), queryable by later
phases (06 = property deserialization, 07 = RPC function resolution).

Output: out/sdk_xref.json
  {
    "meta": {...build, counts...},
    "classes": {
       <ClassName>: {
          "super": [...],
          "size": int,
          "properties": { <PropName>: {offset,type,kind,arrayDim,size,iris_serializer_kind} },
          "functions":   { <FuncName>: {ret, params:[{name,type,kind}], flags} }
       }
    },
    "misses": []   # populated at runtime when a wire class_path fails to resolve
  }

Iris NetSerializer tagging: a property whose declared type is one of the CoreUObject
math types Iris ships a dedicated NetSerializer for (FVector, FRotator, FTransform,
...) is tagged with customSerializeKind="IrisNetSerializer:<Type>". This is a HEURISTIC
hint (the actual serializer is selected per descriptor at build time and resolved in
Phase 06); it is NOT a claim that the wire uses that serializer for every such property.

This DB is the substrate sub-step 4 (ProtocolDescriptorCache) depends on for
ProtocolId -> class -> descriptor. It is backend-agnostic in shape (matches the original
phase doc's requested JSON structure), with Iris-specific NetSerializer tagging.
"""

import json
import os
import sys
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT = os.path.join(REPO, "out")
SDK_INDEX = os.path.join(OUT, "sdk_index.json")
OUT_FILE = os.path.join(OUT, "sdk_xref.json")

# Iris-provided dedicated NetSerializers (UE5.6 CoreUObject math types). Heuristic tag.
IRIS_NETSERIALIZER_TYPES = {
    "FVector", "FRotator", "FTransform", "FQuat", "FVector2D",
    "FVector4", "FLinearColor", "FColor", "FGameplayTag", "FName",
    "FString", "FText", "FSoftObjectPath", "FUniqueNetIdRepl",
    "FTransformNOScale",
}


def _serializer_kind(t: str) -> Optional[str]:
    return ("IrisNetSerializer:" + t) if t in IRIS_NETSERIALIZER_TYPES else None



def main():
    index = json.load(open(SDK_INDEX))
    classes = index["classes"]
    functions = index["functions"]

    out_classes = {}
    prop_count = 0
    iris_tagged = 0
    for name, rec in classes.items():
        props = {}
        for p in rec.get("props", []):
            # dump_sdk.py already normalizes props to dicts:
            #   {name, type, kind, offset, size, count, subtypes, iris_serializer_hint}
            t = p.get("type", "")
            kind = p.get("kind", "")
            subs = p.get("subtypes", [])
            offset = p.get("offset", 0)
            size = p.get("size", 0)
            count = p.get("count", 1)
            sk = _serializer_kind(t)
            props[p["name"]] = {
                "offset": offset,
                "type": t,
                "kind": kind,
                "arrayDim": count,
                "size": size,
                "subtypes": subs,
                "customSerializeKind": sk,
            }
            prop_count += 1
            if sk is not None:
                iris_tagged += 1
        fns = functions.get(name, {})
        out_classes[name] = {
            "super": rec.get("super", []),
            "size": rec.get("size", 0),
            "properties": props,
            "functions": {
                fn: {
                    "ret": meta["ret"],
                    "params": [{"name": pr["name"], "type": pr["type"], "kind": pr["kind"]}
                               for pr in meta["params"]],
                    "flags": meta.get("flags"),
                }
                for fn, meta in fns.items()
            },
        }

    db = {
        "meta": {
            "source": "out/sdk_index.json (Dumper-7)",
            "build": index["meta"]["build"],
            "generated_by": "tools/build_sdk_xref.py",
            "counts": {
                "classes": len(out_classes),
                "properties": prop_count,
                "iris_serializer_tagged": iris_tagged,
                "function_classes": len(functions),
            },
        },
        "classes": out_classes,
    }
    os.makedirs(OUT, exist_ok=True)
    json.dump(db, open(OUT_FILE, "w"), indent=1)
    print(f"Wrote {OUT_FILE}")
    print(f"  classes                : {db['meta']['counts']['classes']}")
    print(f"  properties             : {db['meta']['counts']['properties']}")
    print(f"  Iris-serializer-tagged : {db['meta']['counts']['iris_serializer_tagged']}")
    print(f"  function classes       : {db['meta']['counts']['function_classes']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
