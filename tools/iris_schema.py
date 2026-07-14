"""Phase 06 sub-step 1 (source-faithful reimplementation of Iris
``FReplicationStateDescriptorBuilder::CreateDescriptorsForClass``).

Goal: from the Dumper-7 SDK (out/sdk_index.json) produce, for each replicated
class, the *expected wire schema* (= ordered list of replicated members in
ClassReps order, classified into Init / LifetimeConditional / Regular states).

Source of truth:
  UE/Iris/Private/Iris/ReplicationState/ReplicationStateDescriptorBuilder.cpp
  lines ~2870-3040 (CreateDescriptorsForClass / Build). Key facts:
    * It iterates ``InObjectClass->ClassReps`` (the reflected member list, NOT
      raw UPROPERTY declaration order necessarily, but Dumper-7's ``props``
      are in ClassReps/reflection order — confirmed equal to offset order in the
      TYR dump, see OA-06-1).
    * Members with ``InitOnly`` trait -> Init state.
    * Members with a non-None ReplicationCondition (incl. the
      force-injected ``NetCullDistanceSquared`` for Actor heirs) ->
      LifetimeConditional state.
    * Everything else -> Regular state (gets ChangeMaskBits, default 1).

Caveat (OA-06-1): the SDK dump exposes NO per-property ReplicationCondition /
InitOnly / RepIndex trait. So the Init/Regular split CANNOT be rebuilt from
reflection alone. Per OA-06-1 we default every member to Regular (the correct
Iris default for an un-trait-ed property) and force-inject
NetCullDistanceSquared as LifetimeConditional for Actor heirs. The precise
Init/Regular split is then derived empirically from the wire in u1_decode.py
(spawn body = Init+Regular unmasked; delta body = Regular under change mask).

This module ONLY builds the member ORDER + TYPE schema (the layout the decoder
consumes). It does not assert byte-exactness — that is u1_decode.py's job
against real carrier bodies.
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from typing import Optional

SDK_PATH = os.path.join(os.path.dirname(__file__), "..", "out", "sdk_index.json")


@dataclass
class Member:
    name: str
    ctype: str          # SDK 'type' (e.g. float, int32, FVector, TArray, ...)
    kind: str           # D/S/C/E
    offset: int
    size: int
    count: int
    subtypes: list
    state: str = "Regular"   # Init | LifetimeConditional | Regular


@dataclass
class ClassSchema:
    cpp_name: str
    super_chain: list
    members: list = field(default_factory=list)   # ordered Member list (ClassReps order)
    n_init: int = 0
    n_lifetime: int = 0
    n_regular: int = 0

    @property
    def total_bytes(self) -> int:
        # Sum of member sizes ONLY for layouts we can naively lay out
        # (primitives + fixed arrays). Structs/containers make this a lower bound.
        return sum(m.size for m in self.members if m.kind in ("D", "E"))


def load_sdk(path: str = SDK_PATH) -> dict:
    with open(path, "r", encoding="latin-1") as f:
        return json.load(f)


def _super_chain(sdk: dict, cpp_name: str, _seen=None) -> list:
    if _seen is None:
        _seen = []
    entry = sdk.get("classes", {}).get(cpp_name) or sdk.get("structs", {}).get(cpp_name)
    if not entry:
        return _seen
    supers = entry.get("super", [])
    for s in supers:
        if s not in _seen:
            _seen.append(s)
            _super_chain(sdk, s, _seen)
    return _seen


def _member_from_prop(p: dict, state: str = "Regular") -> Member:
    return Member(
        name=p["name"],
        ctype=p["type"],
        kind=p.get("kind", "D"),
        offset=p.get("offset", 0),
        size=p.get("size", 0),
        count=p.get("count", 1),
        subtypes=p.get("subtypes", []),
        state=state,
    )


def build_class_schema(sdk: dict, cpp_name: str) -> Optional[ClassSchema]:
    """Build the wire schema for one C++ class name (e.g. 'APlayerState').

    Walks the super-chain (base-first) collecting reflected props in ClassReps
    order. Classifies NetCullDistanceSquared on Actor heirs as
    LifetimeConditional (force-injected by Iris builder, source lines 2951-2976).
    All other members default to Regular (OA-06-1: no trait info available).
    """
    if cpp_name not in sdk.get("classes", {}) and cpp_name not in sdk.get("structs", {}):
        return None
    chain = _super_chain(sdk, cpp_name)
    # ensure the class itself is present
    if cpp_name not in chain:
        chain.append(cpp_name)
    members: list = []
    is_actor_heir = any(c in ("AActor", "UObject") for c in chain)
    seen_names = set()
    for cls in chain:
        entry = sdk.get("classes", {}).get(cls) or sdk.get("structs", {}).get(cls)
        if not entry:
            continue
        for p in entry.get("props", []):
            key = (cls, p["name"])
            if key in seen_names:
                continue  # derived classes override base members in ClassReps
            seen_names.add(key)
            state = "Regular"
            # Force-injected LifetimeConditional for Actor heirs (source 2951-2976)
            if is_actor_heir and p["name"] == "NetCullDistanceSquared":
                state = "LifetimeConditional"
            members.append(_member_from_prop(p, state))
    schema = ClassSchema(cpp_name=cpp_name, super_chain=chain, members=members)
    schema.n_init = sum(1 for m in members if m.state == "Init")
    schema.n_lifetime = sum(1 for m in members if m.state == "LifetimeConditional")
    schema.n_regular = sum(1 for m in members if m.state == "Regular")
    return schema


def is_primitive(m: Member) -> bool:
    """Can this member be laid out as a fixed-width primitive for bootstrap?"""
    if m.kind == "E":
        return True
    if m.kind != "D":
        return False
    return m.ctype in {
        "float", "double", "int8", "int16", "int32", "int64",
        "uint8", "uint16", "uint32", "uint64", "bool", "FName",
    }


def primitive_size_bytes(m: Member) -> int:
    return {
        "float": 4, "double": 8, "int8": 1, "int16": 2, "int32": 4,
        "int64": 8, "uint8": 1, "uint16": 2, "uint32": 4, "uint64": 8,
        "bool": 1, "FName": 8, "FString": 0,
    }.get(m.ctype, m.size)


if __name__ == "__main__":
    sdk = load_sdk()
    for name in ["APlayerState", "ACharacter", "APawn", "AActor"]:
        sc = build_class_schema(sdk, name)
        if not sc:
            print(name, "NOT IN SDK"); continue
        prim = [m for m in sc.members if is_primitive(m)]
        print(f"{name}: super={sc.super_chain[:4]} members={len(sc.members)} "
              f"primitives={len(prim)} Init={sc.n_init} Lifetime={sc.n_lifetime} "
              f"Regular={sc.n_regular}")
        for m in prim[:8]:
            print(f"    {m.state:18} {m.ctype:10} {m.name} (off {m.offset}, {m.size}B)")
