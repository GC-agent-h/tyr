"""
dump_sdk.py — consolidate the Dumper-7 Dumpspace reflection JSON into a single
queryable index for fast SDK cross-referencing (Phase 00 deliverable #4; used
from Phase 04 onward for class/property/function resolution, including Iris
NetSerializer tagging).

Input:  dumper-7/Dumpspace/{Classes,Structs,Functions,Enums}Info.json
        dumper-7/Dumpspace/OffsetsInfo.json
        dumper-7/Mappings/*.usmap  (for build id)
Output: out/sdk_index.json

Property entry shape (from StructsInfo/ClassesInfo dump format):
    "<PropName>": [ [typename, kind, <unk>, [subtypes]], offset, size, count ]
    kind: 'D'=data member, 'S'=struct, 'C'=class/object, 'E'=enum
Function entry shape (FunctionsInfo):
    "<FuncName>": [ ret_type, params, <unk_int>, flags ]
    ret_type / param types: [typename, kind, <unk>, [subtypes]]

Run:  python3 tools/dump_sdk.py
"""

from __future__ import annotations

import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DUMPSPACE = os.path.join(REPO, "dumper-7", "Dumpspace")
MAPPINGS = os.path.join(REPO, "dumper-7", "Mappings")
OUT = os.path.join(REPO, "out")
OUT_FILE = os.path.join(OUT, "sdk_index.json")

# Known Iris NetSerializer-replicated CoreUObject math types. This is a
# HEURISTIC tag only: these types are the ones Iris provides dedicated
# quantized NetSerializers for in UE5.6 (FVectorNetSerializer etc.). It is NOT
# a claim that every such property on the wire uses that serializer — actual
# serializer selection is per-RepNotify/descriptor and resolved in Phase 06.
IRIS_SERIALIZER_TYPES = {
    "FVector", "FRotator", "FTransform", "FQuat", "FVector2D",
    "FVector4", "FLinearColor", "FColor", "FGameplayTag", "FName",
    "FString", "FText", "FSoftObjectPath", "FUniqueNetIdRepl",
    "FTransformNOScale",
}


def _type_of(entry):
    """Return (typename, kind, subtypes) from a [type,kind,unk,sub] list."""
    t = entry[0] if isinstance(entry, list) else entry
    kind = entry[1] if isinstance(entry, list) and len(entry) > 1 else ""
    subs = entry[3] if isinstance(entry, list) and len(entry) > 3 else []
    return t, kind, subs


def parse_member(name, entry):
    """entry = [ [type,kind,unk,sub], offset, size, count ]"""
    t, kind, subs = _type_of(entry[0])
    offset, size, count = entry[1], entry[2], entry[3]
    return {
        "name": name,
        "type": t,
        "kind": kind,  # D/S/C/E
        "offset": offset,
        "size": size,
        "count": count,
        "subtypes": subs,
        "iris_serializer_hint": t in IRIS_SERIALIZER_TYPES,
    }


def parse_classlike(data_list):
    """Shared parser for ClassesInfo / StructsInfo entries.

    Each top-level item is { Name: [ {...inherit...}, {...size...},
    prop1, prop2, ... ] }. Inherit + size dicts carry __ keys.
    """
    out = {}
    for entry in data_list:
        for name, body in entry.items():
            meta = {}
            props = []
            for item in body:
                if not isinstance(item, dict):
                    continue
                for k, v in item.items():
                    if k.startswith("__"):
                        if k == "__InheritInfo":
                            meta["super"] = list(v)
                        elif k == "__MDKClassSize":
                            meta["size"] = v
                    else:
                        # property
                        props.append(parse_member(k, v))
            rec = {"super": meta.get("super", []), "size": meta.get("size", 0),
                   "props": props}
            out[name] = rec
    return out


def parse_enums(data_list):
    out = {}
    for entry in data_list:
        for name, body in entry.items():
            # body = [ [ {Value:Int,...}, ... ], "uint8" ]
            members, underlying = body
            values = {k: v for m in members for k, v in m.items()}
            out[name] = {"underlying": underlying, "values": values}
    return out


def parse_functions(data_list):
    out = {}
    for entry in data_list:
        for cls, body in entry.items():
            fnmap = {}
            for item in body:
                if not isinstance(item, dict):
                    continue
                for fn, meta in item.items():
                    ret, params, _unk, flags = meta
                    rtype, rkind, rsub = _type_of(ret)
                    plist = []
                    for p in params:
                        ptype, pkind, psub = _type_of(p[0]) if p else ("", "", [])
                        pname = p[2] if len(p) > 2 else ""
                        plist.append({"type": ptype, "kind": pkind,
                                      "name": pname, "subtypes": psub})
                    fnmap[fn] = {"ret": rtype, "ret_kind": rkind,
                                 "params": plist, "flags": flags}
            out[cls] = fnmap
    return out


def parse_offsets(data):
    out = {}
    for key, val in data.get("data", []):
        out[key] = val
    return out


def detect_iris_classes(classes, structs):
    """HEURISTIC: collect class/struct names that reference Iris in name or
    inheritance chain. Evidence-grounded (name substring only)."""
    iris = set()
    alltypes = {**classes, **structs}
    for name in alltypes:
        low = name.lower()
        if "iris" in low or low.startswith("net") or "replicationsystem" in low \
           or "replicationbridge" in low or "replicationstate" in low \
           or "netblob" in low or "netrefhandle" in low or "nettoken" in low:
            iris.add(name)
    return sorted(iris)


def build_index():
    classes = parse_classlike(json.load(open(os.path.join(DUMPSPACE, "ClassesInfo.json")))["data"])
    structs = parse_classlike(json.load(open(os.path.join(DUMPSPACE, "StructsInfo.json")))["data"])
    enums = parse_enums(json.load(open(os.path.join(DUMPSPACE, "EnumsInfo.json")))["data"])
    functions = parse_functions(json.load(open(os.path.join(DUMPSPACE, "FunctionsInfo.json")))["data"])
    offsets = parse_offsets(json.load(open(os.path.join(DUMPSPACE, "OffsetsInfo.json"))))

    usmaps = glob.glob(os.path.join(MAPPINGS, "*.usmap"))
    build = os.path.basename(usmaps[0]) if usmaps else "unknown"

    iris_tagged = detect_iris_classes(classes, structs)

    # count properties flagged with the serializer hint
    iris_prop_hint = 0
    for store in (classes, structs):
        for rec in store.values():
            iris_prop_hint += sum(1 for p in rec["props"] if p["iris_serializer_hint"])

    index = {
        "meta": {
            "source": "dumper-7/Dumpspace/*.json",
            "build": build,
            "generated_by": "tools/dump_sdk.py",
            "counts": {
                "classes": len(classes),
                "structs": len(structs),
                "enums": len(enums),
                "functions_classes": len(functions),
                "properties_iris_serializer_hint": iris_prop_hint,
            },
        },
        "iris_tagged_types": iris_tagged,
        "classes": classes,
        "structs": structs,
        "enums": enums,
        "functions": functions,
        "offsets": offsets,
    }
    return index


def main():
    os.makedirs(OUT, exist_ok=True)
    index = build_index()
    with open(OUT_FILE, "w") as f:
        json.dump(index, f, indent=1)
    m = index["meta"]
    print(f"Wrote {OUT_FILE}")
    print(f"  build            : {m['build']}")
    print(f"  classes          : {m['counts']['classes']}")
    print(f"  structs          : {m['counts']['structs']}")
    print(f"  enums            : {m['counts']['enums']}")
    print(f"  function classes : {m['counts']['functions_classes']}")
    print(f"  iris-tagged types: {len(index['iris_tagged_types'])}")
    print(f"  iris-serializer-hint properties: {m['counts']['properties_iris_serializer_hint']}")


if __name__ == "__main__":
    sys.exit(main())
