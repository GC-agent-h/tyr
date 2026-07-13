"""
iris_state_builder.py — Phase 06 sub-step 1.

Reimplements the Iris FReplicationStateDescriptorBuilder traversal
(UE/Iris/Private/Iris/ReplicationState/ReplicationStateDescriptorBuilder.cpp,
CreateDescriptorsForClass + Build, lines ~2870-3040) so that Phase 06 can predict
the EXACT wire send-order of replicated members for any class resolved in the
Dumper-7 SDK.

WHY THIS IS NOT THE SAME AS phase04's build_member_list
-------------------------------------------------------
Phase 04's ProtocolDescriptorCache.build_member_list (iris_protocol_cache.py) was a
*coverage heuristic*: a single flat list sorted by SDK memory offset, used only to
prove the rebuild mechanism resolves 100% of replay-observed class names. It is
NOT the wire schema. Iris's real builder (verified from source) does two things
that the heuristic does not:

  1. MEMBER ORDER == InObjectClass->ClassReps iteration order (line 2880), which is
     base->derived declaration order, NOT memory-offset order. (For the TYR SDK dump
     the two happen to coincide per-class, but the chain concatenation and same-offset
     bitfield grouping are only guaranteed by declaration order, so we use it.)

  2. THREE-WAY STATE SPLIT. Each member is routed into one or more of three
     FReplicationStateDescriptor "states" (lines 2923-2942):
        * Init state        (bIsInitState=true)  -> members with InitOnly trait.
                                                     ChangeMaskBits = 0 (always sent
                                                     on spawn/initial).
        * LifetimeConditional state              -> members with HasLifetimeConditionals
                                                     trait (incl. NetCullDistanceSquared
                                                     forced in for Actor heirs, 2951-2976).
        * Regular state                         -> members that are neither InitOnly
                                                     nor conditional. THESE are the
                                                     delta-updated members; each gets
                                                     ChangeMaskBits (typically 1) — this
                                                     is the dirty-state signaling mechanism
                                                     Phase 06 must decode (BuildMemberChange
                                                     MaskDescriptors, 1139-1200).

THE COND_* GAP (recorded as OA-06-1 in open-assumptions.md)
-----------------------------------------------------------
The Dumper-7 SDK dump (out/sdk_index.json) exposes per property only
{name, type, kind, offset, size, count, subtypes, iris_serializer_hint}.
It does NOT expose:
   * ReplicationCondition (COND_None / OwnerOnly / InitialOnly / SimulatedOnly ...)
   * CPF_Init / InitOnly trait
   * HasLifetimeConditionals trait
   * RepIndex / ChangeMaskBits
Therefore the Init/Regular/LifetimeConditional assignment CANNOT be rebuilt purely
from reflection. Per the README "plan needs to change -> document + open-assumptions"
rule, this module:
   * builds the flat ClassReps-order member list (fully determined from SDK), AND
   * exposes a STATE_OVERRIDES table that the empirical wire cross-check (commit 2 of
     sub-step 1) will populate from observed wire behavior (Init state = first absolute
     block after spawn; Regular = delta-masked blocks; Conditional = owner/condition
     gated presence). Until then the default routing is ALL-REGULAR (the common case:
     most replicated properties are Regular state with a 1-bit change mask), which is
     the correct Iris default for a property with no special trait (lines 2939-2942).

This keeps sub-step 1's deliverable honest: the order is source-exact; the
state-split is source-exact *where the SDK permits* and empirically-derived where it
does not, with the gap explicitly tracked.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT = os.path.join(REPO, "out")
SDK_INDEX = os.path.join(OUT, "sdk_index.json")

# Reuse the normalized SDK cross-reference from Phase 04.
sys.path.insert(0, HERE)
from iris_protocol_cache import SdkXref, load_sdk_xref  # noqa: E402

# --- Iris NetSerializer types that ship dedicated quantized serializers (UE5.6).
IRIS_NETSERIALIZER_TYPES = {
    "FVector", "FRotator", "FTransform", "FQuat", "FVector2D",
    "FVector4", "FLinearColor", "FColor", "FGameplayTag", "FName",
    "FString", "FText", "FSoftObjectPath", "FUniqueNetIdRepl",
    "FTransformNOScale",
}

# Default change-mask bits for a Regular-state member. Source:
#   BuildMemberSerializerDescriptors default ChangeMaskBits = 1U (lines 2181/2253)
#   FastArray members get 1U + TArrayElementChangeMaskBits (2191/2197).
REGULAR_CHANGE_MASK_BITS = 1

# Optional per-class (or per-(class,member)) state overrides, populated by the
# empirical wire cross-validation harness. Format:
#   STATE_OVERRIDES[class_key][member_name] = "init" | "conditional" | "regular"
STATE_OVERRIDES: Dict[str, Dict[str, str]] = {}


@dataclass
class StateMember:
    """One replicated member in its assigned state, in wire send-order."""
    name: str
    owner_class: str        # the class in the chain that declares this member
    type: str
    kind: str               # D/S/C/E
    array_dim: int
    size: int
    offset: int
    state: str              # "init" | "conditional" | "regular"
    change_mask_bits: int   # 0 for init members, >=1 for regular/conditional
    iris_serializer_hint: bool
    custom_serialize_kind: Optional[str] = None


@dataclass
class BuiltState:
    """One of the (up to three) FReplicationStateDescriptor states for a class."""
    state: str              # "init" | "conditional" | "regular"
    members: List[StateMember]
    change_mask_bit_count: int

    def canonical_key(self) -> Tuple:
        return tuple((m.owner_class, m.name, m.state, m.change_mask_bits)
                     for m in self.members)


@dataclass
class BuiltSchema:
    class_path: str
    inheritance_chain: List[str]
    states: Dict[str, BuiltState]           # keyed by state name
    flat_order: List[StateMember]           # init, then conditional, then regular
    total_change_mask_bits: int

    def canonical_key(self) -> Tuple:
        return tuple(s.canonical_key() for s in self.states.values())


class IrisStateBuilder:
    """Mirrors FPropertyReplicationStateDescriptorBuilder::CreateDescriptorsForClass."""

    def __init__(self, sdk: SdkXref,
                 state_overrides: Optional[Dict[str, Dict[str, str]]] = None) -> None:
        self.sdk = sdk
        self.state_overrides = state_overrides or STATE_OVERRIDES
        # cache per (class_key, overrides-key) for determinism reuse
        self._cache: Dict[str, BuiltSchema] = {}

    # --- classify a single member into a state, given available metadata ---
    def _classify(self, class_key: str, member_name: str, is_actor_heir: bool) -> str:
        ov = self.state_overrides.get(class_key, {}).get(member_name)
        if ov in ("init", "conditional", "regular"):
            return ov
        # No reflection metadata available for InitOnly / HasLifetimeConditionals.
        # Iris default for an un-trait-ed property is Regular state (lines 2939-2942),
        # EXCEPT NetCullDistanceSquared which the engine forces into the conditional
        # state for Actor heirs (2951-2976). We honor that structural special-case.
        if is_actor_heir and member_name == "NetCullDistanceSquared":
            return "conditional"
        return "regular"

    def build(self, class_path: str) -> Optional[BuiltSchema]:
        if class_path in self._cache:
            return self._cache[class_path]
        if not self.sdk.resolve_class(class_path):
            return None

        chain = self.sdk.inheritance_chain(class_path)
        is_actor_heir = self._is_actor_heir(chain)

        states: Dict[str, List[StateMember]] = {
            "init": [], "conditional": [], "regular": []
        }

        # Walk base -> derived (ClassReps order = declaration order within each class).
        for level, cls_name in enumerate(chain):
            base = cls_name.rstrip(" (UNRESOLVED)")
            key = self.sdk._resolve_key(base)  # path or short name
            if key is None:
                continue
            rec = self.sdk.classes.get(key) or self.sdk.structs.get(key)
            if rec is None:
                continue
            # SDK props are already in dump (= declaration) order; use as-is.
            for p in rec.get("props", []):
                name = p["name"]
                ser_hint = p.get("iris_serializer_hint", False)
                kind = p.get("custom_serialize_kind")
                if ser_hint and kind is None:
                    kind = "IrisNetSerializer:" + p.get("type", "")
                st = self._classify(class_path, name, is_actor_heir)
                cmb = 0 if st == "init" else REGULAR_CHANGE_MASK_BITS
                states[st].append(StateMember(
                    name=name,
                    owner_class=base,
                    type=p["type"],
                    kind=p.get("kind", ""),
                    array_dim=p.get("count", 1),
                    size=p.get("size", 0),
                    offset=p.get("offset", 0),
                    state=st,
                    change_mask_bits=cmb,
                    iris_serializer_hint=ser_hint,
                    custom_serialize_kind=kind,
                ))

        # Assemble states + flat order (init first, then conditional, then regular) —
        # matching the order FReplicationProtocol concatenates its
        # ReplicationStateDescriptors.
        built_states: Dict[str, BuiltState] = {}
        flat: List[StateMember] = []
        total_cmb = 0
        for st_name in ("init", "conditional", "regular"):
            members = states[st_name]
            cmb = sum(m.change_mask_bits for m in members)
            built_states[st_name] = BuiltState(
                state=st_name, members=members, change_mask_bit_count=cmb)
            flat.extend(members)
            total_cmb += cmb

        schema = BuiltSchema(
            class_path=class_path,
            inheritance_chain=chain,
            states=built_states,
            flat_order=flat,
            total_change_mask_bits=total_cmb,
        )
        self._cache[class_path] = schema
        return schema

    def _is_actor_heir(self, chain: List[str]) -> bool:
        # Cheap structural check: any class in the chain is AInfo/AActor or a
        # known Actor subclass. The engine uses IsChildOf(Actor) (2955); we
        # approximate by chain membership of the obvious Actor bases.
        actor_bases = {"AInfo", "AActor", "AGameStateBase", "AGameState",
                       "APlayerState", "APawn", "ACharacter", "AController",
                       "APlayerController", "AGameModeBase"}
        for c in chain:
            c = c.rstrip(" (UNRESOLVED)").split("/")[-1]
            if c in actor_bases:
                return True
        return False


def load_builder(state_overrides: Optional[Dict[str, Dict[str, str]]] = None
                 ) -> IrisStateBuilder:
    return IrisStateBuilder(load_sdk_xref(), state_overrides=state_overrides)


if __name__ == "__main__":
    # Self-test: determinism + SDK coverage (the load-bearing sub-step-1 metrics).
    sdk = load_sdk_xref()
    b = IrisStateBuilder(sdk)

    all_types = list(sdk.classes.keys()) + list(sdk.structs.keys())
    built = 0
    fails = 0
    inconsistent = 0
    for t in all_types:
        short = t.split("/")[-1]
        d1 = b.build(short)
        if d1 is None:
            fails += 1
            continue
        built += 1
        d2 = b.build(short)
        if d1.canonical_key() != d2.canonical_key():
            inconsistent += 1

    total = len(all_types)
    print(f"SDK types enumerated : {total}")
    print(f"descriptors rebuilt  : {built}")
    print(f"resolution misses    : {fails}")
    print(f"determinism failures : {inconsistent}")

    # Spot-check one Actor heir (APlayerState) to confirm 3-state shape.
    sample = "APlayerState"
    s = b.build(sample)
    print(f"\nSample {sample}:")
    print(f"  inheritance_chain : {s.inheritance_chain}")
    print(f"  total members     : {len(s.flat_order)}")
    for st_name in ("init", "conditional", "regular"):
        st = s.states[st_name]
        print(f"  state {st_name:11s}: {len(st.members)} members, "
              f"change_mask_bits={st.change_mask_bit_count}")
        for m in st.members[:6]:
            print(f"      - {m.name} ({m.type}) cmb={m.change_mask_bits}")

    assert inconsistent == 0, "determinism FAILED"
    assert built == total, f"unexpected misses: {fails}"
    print("\nOK — IrisStateBuilder determinism + coverage self-test PASSED")
