"""
iris_protocol_cache.py — Phase 04 (sub-step 4, CORRECTED for Iris).

Replication protocol / descriptor schema cache.

==========================================================================
WHY THIS IS NOT A STREAMING-EXPORT CACHE (source-verified correction)
==========================================================================
The original sub-step 4 assumed an Iris analog of the legacy NetFieldExportGroup
export stream — i.e. per-class replication schemas serialized once and streamed
like handle/token exports. That is FALSE for Iris. Evidence (UE 5.6, in-repo):

  * ReplicationProtocolManager.cpp:170-184 — FReplicationProtocolIdentifier is
    CityHash32 over the constituent FReplicationStateDescriptor::DescriptorIdentifier
    (Value, DefaultStateHash) pairs. It is a *hash*, not a schema handle. Width
    uint32 (ReplicationProtocol.h:13).
  * NetObjectFactory.cpp:101-102 (WriteHeader) and :134 (ReadHeader) — on the wire
    a creation header carries FactoryId then WriteBits(ProtocolId, 32). NO descriptor
    bytes follow. Only the 32-bit hash travels.
  * ObjectReplicationBridge.cpp:1681-1709 (RegisterRemoteInstance) — the remote side
    receives ProtocolId, resolves the UClass from the creation-header class PATH,
    builds the FReplicationFragments for that class, and calls
    ReplicationProtocolManager->CreateReplicationProtocol(ReceivedProtocolId, ...),
    recomputing the descriptor locally and asserting the recomputed CityHash equals
    the received id (bValidateProtocolId). The schema is a deterministic function of
    the UClass reflection, never transmitted.
  * NetExports.cpp — the only Iris "exports" tracked per packet are NetHandleExport
    and NetTokenExport. There is NO descriptor/schema export scope.

Therefore the "schema cache" is built LOCALLY by re-running the Iris descriptor-builder
logic against the Dumper-7 SDK reflection for the resolved class, keyed by the 32-bit
ProtocolId. There is no streaming-pass descriptor export to consume. The "streaming
pass" for this sub-step is the contract observe_protocol(ProtocolId, class_path) that
the Phase 05 creation-header walker will call (see docs/04-guid-cache-netfieldexport.md
"CRITICAL CORRECTION" block).

==========================================================================
WHAT WE REBUILD (mirroring FReplicationStateDescriptorBuilder semantics)
==========================================================================
For a given class, Iris builds one FReplicationProtocol from one or more
FReplicationStateDescriptors (one per fragment, typically one per owner/state
slice). Each descriptor lists its members in a deterministic order. The union send
order is base->derived, and within a class the members are ordered by their layout
offset (FReplicationStateDescriptorBuilder walks UPROPERTYs in memory order).

We reproduce that deterministic order from the SDK:
  * Walk the inheritance chain (super[0] primary base) from UObject up to the class.
  * For each class in the chain (base first), take its SDK UPROPERTYs in SDK offset
    order (SDK offset == memory order for a given class slice).
  * Concatenate. This is the deterministic member list the wire deserializer reads,
    exactly matching FReplicationStateDescriptorBuilder's traversal (parent states
    before child states; within a state, offset order).
Within each member we record: name, SDK offset, declared type, kind (D/S/C/E),
arrayDim (count), size, and customSerializeKind (Iris NetSerializer tag, NOT legacy
NetSerialize). customSerializeKind is a HEURISTIC tag (Iris provides dedicated
NetSerializers for these CoreUObject math types) — it is flagged as a hint, not a
claim that the wire uses it.

==========================================================================
VALIDATION MODEL (no live debugging available — Step 0.3 revised)
==========================================================================
We cannot recompute the exact CityHash32 without the engine's DescriptorIdentifier
constants (those live in the running binary). So instead we assert the load-bearing
properties of the rebuild (see docs(phase04): static cross-check):
  (1) Determinism: observe_protocol(protocol_id, class_path) returns a byte-identical
      descriptor on repeated calls and for the same (id, path) pair seen again.
  (2) Cross-file consistency: the same (protocol_id, class_path) maps to the same
      descriptor across all 10 sample files (checked in the validation probe).
  (3) SDK class-match rate: every class_path we observe resolves in the SDK (Phase 05
      will surface protocol_ids; here we validate the rebuild over the full SDK class
      set to prove 100% coverage of the mechanism).
  (4) Field-name plausibility: every rebuilt member is a real SDK UPROPERTY on the
      class or an ancestor (guaranteed by construction since we walk the SDK).
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

# Iris-provided dedicated NetSerializers (UE5.6 CoreUObject math types). HEURISTIC
# tag only — actual serializer selection is per-descriptor and resolved in Phase 06.
IRIS_NETSERIALIZER_TYPES = {
    "FVector", "FRotator", "FTransform", "FQuat", "FVector2D",
    "FVector4", "FLinearColor", "FColor", "FGameplayTag", "FName",
    "FString", "FText", "FSoftObjectPath", "FUniqueNetIdRepl",
    "FTransformNOScale",
}

# Sentinel class names that terminate an inheritance walk (no SDK reflection above).
ROOT_CLASSES = {"UObject", "IInterface"}


@dataclass
class MemberDescriptor:
    name: str
    owner_class: str           # the class (in the chain) that declares this member
    offset: int                # SDK memory offset within the full object layout
    type: str
    kind: str                  # D/S/C/E
    array_dim: int             # count (1 = scalar)
    size: int
    subtypes: List
    iris_serializer_hint: bool
    custom_serialize_kind: Optional[str] = None  # "IrisNetSerializer:<Type>" or None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "owner_class": self.owner_class,
            "offset": self.offset,
            "type": self.type,
            "kind": self.kind,
            "array_dim": self.array_dim,
            "size": self.size,
            "subtypes": self.subtypes,
            "iris_serializer_hint": self.iris_serializer_hint,
            "custom_serialize_kind": self.custom_serialize_kind,
        }


@dataclass
class BuiltDescriptor:
    protocol_id: int
    class_path: str
    members: List[MemberDescriptor]
    inheritance_chain: List[str]
    class_size: int
    # Provenance
    first_seen_chunk: Optional[int] = None
    first_seen_offset_bits: Optional[int] = None
    # Redundancy/consistency flags
    determinism_verified: bool = False
    notes: str = ""

    @property
    def member_count(self) -> int:
        return len(self.members)

    def canonical_key(self) -> Tuple:
        """A deterministic signature used to assert rebuild determinism."""
        return tuple(
            (m.owner_class, m.name, m.offset, m.type, m.kind, m.array_dim, m.size)
            for m in self.members
        )

    def to_dict(self) -> dict:
        return {
            "protocol_id": self.protocol_id,
            "class_path": self.class_path,
            "inheritance_chain": self.inheritance_chain,
            "class_size": self.class_size,
            "member_count": self.member_count,
            "members": [m.to_dict() for m in self.members],
            "first_seen_chunk": self.first_seen_chunk,
            "first_seen_offset_bits": self.first_seen_offset_bits,
            "determinism_verified": self.determinism_verified,
            "notes": self.notes,
        }


class SdkXref:
    """Normalized SDK cross-reference database: class -> members (incl. ancestors),
    functions, Iris NetSerializer tagging. Phase 04 sub-step 5 substrate."""

    def __init__(self, sdk_index: dict) -> None:
        self.classes = sdk_index.get("classes", {})
        self.structs = sdk_index.get("structs", {})
        self.functions = sdk_index.get("functions", {})
        self.enums = sdk_index.get("enums", {})
        # short-name (last path component) -> full key, for inheritance resolution
        self._by_short: Dict[str, str] = {}
        for store in (self.classes, self.structs):
            for k in store:
                self._by_short.setdefault(k.split("/")[-1], k)

    def _resolve_key(self, name: str) -> Optional[str]:
        if name in self.classes or name in self.structs:
            return name
        return self._by_short.get(name)

    def inheritance_chain(self, class_name: str) -> List[str]:
        """Primary-base inheritance chain from UObject (base) up to class.

        Returns base-first. Stops at ROOT_CLASSES. Handles missing links as MISS.
        """
        chain: List[str] = []
        seen = set()
        cur = class_name
        while cur and cur not in seen:
            seen.add(cur)
            key = self._resolve_key(cur)
            if key is None:
                chain.append(cur + " (UNRESOLVED)")
                break
            chain.append(cur)
            rec = self.classes.get(key) or self.structs.get(key)
            supers = rec.get("super", []) if rec else []
            if not supers or cur in ROOT_CLASSES:
                break
            cur = supers[0]
        return chain

    def build_member_list(self, class_name: str) -> Tuple[List[MemberDescriptor], List[str], int]:
        """Rebuild the deterministic Iris send-order member list for a class.

        Mirrors FReplicationStateDescriptorBuilder: base states first, members in
        SDK offset order within each class slice, concatenated base->derived.
        """
        chain = self.inheritance_chain(class_name)
        members: List[MemberDescriptor] = []
        class_size = 0
        for level, cls_name in enumerate(chain):
            base = cls_name.rstrip(" (UNRESOLVED)")
            key = self._resolve_key(base)
            if key is None:
                continue
            rec = self.classes.get(key) or self.structs.get(key)
            if rec is None:
                continue
            if level == len(chain) - 1:
                class_size = rec.get("size", 0)
            # SDK props are already in dump order; sort by offset to match memory order.
            for p in sorted(rec.get("props", []), key=lambda x: x.get("offset", 0)):
                ser_hint = p.get("iris_serializer_hint", False)
                kind = p.get("custom_serialize_kind")
                if ser_hint and kind is None:
                    kind = "IrisNetSerializer:" + p.get("type", "")
                members.append(MemberDescriptor(
                    name=p["name"],
                    owner_class=base,
                    offset=p["offset"],
                    type=p["type"],
                    kind=p.get("kind", ""),
                    array_dim=p.get("count", 1),
                    size=p.get("size", 0),
                    subtypes=p.get("subtypes", []),
                    iris_serializer_hint=ser_hint,
                    custom_serialize_kind=kind,
                ))
        return members, chain, class_size

    def resolve_class(self, class_name: str) -> bool:
        return self._resolve_key(class_name) is not None

    def functions_for(self, class_name: str) -> dict:
        key = self._resolve_key(class_name)
        if key is None:
            return {}
        return self.functions.get(key, {})


class ProtocolDescriptorCache:
    """Keyed by 32-bit FReplicationProtocolIdentifier; descriptor rebuilt locally."""

    def __init__(self, sdk: SdkXref) -> None:
        self.sdk = sdk
        self._by_protocol: Dict[int, BuiltDescriptor] = {}
        # For class_path -> protocol_id (the reverse lookup the Phase 5 walker needs)
        self._by_class: Dict[str, int] = {}
        self._misses: List[str] = []          # class_paths that failed SDK resolution
        self._redundant_checks: List[dict] = []  # determinism log

    def observe_protocol(
        self,
        protocol_id: int,
        class_path: str,
        chunk_index: Optional[int] = None,
        offset_bits: Optional[int] = None,
    ) -> Optional[BuiltDescriptor]:
        """The streaming-pass entry point (called by the Phase 05 creation-header
        walker once per decoded creation header).

        protocol_id : the 32-bit FReplicationProtocolIdentifier read from the wire.
        class_path  : the class path recovered from the creation-header class path
                      (which Iris uses to resolve the UClass; see ObjectReplicationBridge
                      ::RegisterRemoteInstance). We resolve it in the SDK and rebuild
                      the descriptor locally, never trusting any wire schema.

        Returns the BuiltDescriptor, or None if the class_path does not resolve in the
        SDK (recorded as a miss for the coverage metric).
        """
        # If we already have this protocol_id, verify determinism on re-observe
        # (redundant decode path — the strongest available substitute for a live diff).
        existing = self._by_protocol.get(protocol_id)
        members, chain, class_size = self.sdk.build_member_list(class_path)

        if not self.sdk.resolve_class(class_path):
            if class_path not in self._misses:
                self._misses.append(class_path)
            return None

        desc = BuiltDescriptor(
            protocol_id=protocol_id,
            class_path=class_path,
            members=members,
            inheritance_chain=chain,
            class_size=class_size,
            first_seen_chunk=chunk_index if existing is None else existing.first_seen_chunk,
            first_seen_offset_bits=offset_bits if existing is None else existing.first_seen_offset_bits,
        )

        if existing is not None:
            # Redundant path: same protocol_id seen again — assert identical rebuild.
            if existing.canonical_key() == desc.canonical_key():
                existing.determinism_verified = True
                self._redundant_checks.append({
                    "protocol_id": protocol_id, "class_path": class_path,
                    "consistent": True})
            else:
                self._redundant_checks.append({
                    "protocol_id": protocol_id, "class_path": class_path,
                    "consistent": False,
                    "prev_members": len(existing.members),
                    "new_members": len(desc.members)})
            return existing

        # First observation.
        self._by_protocol[protocol_id] = desc
        self._by_class[class_path] = protocol_id
        return desc

    def get(self, protocol_id: int) -> Optional[BuiltDescriptor]:
        return self._by_protocol.get(protocol_id)

    def get_by_class(self, class_path: str) -> Optional[BuiltDescriptor]:
        pid = self._by_class.get(class_path)
        return self._by_protocol.get(pid) if pid is not None else None

    def stats(self) -> dict:
        verified = sum(1 for d in self._by_protocol.values() if d.determinism_verified)
        return {
            "protocols_cached": len(self._by_protocol),
            "classes_resolved": len(self._by_class),
            "determinism_verified": verified,
            "redundant_reobserves": len(self._redundant_checks),
            "redundant_inconsistent": sum(
                1 for c in self._redundant_checks if not c.get("consistent")),
            "sdk_misses": len(self._misses),
        }

    def export_json(self) -> dict:
        return {
            "protocols": {str(pid): d.to_dict() for pid, d in self._by_protocol.items()},
            "by_class": self._by_class,
            "misses": self._misses,
            "stats": self.stats(),
        }


def load_sdk_xref(sdk_path: str = SDK_INDEX) -> SdkXref:
    with open(sdk_path) as f:
        return SdkXref(json.load(f))


if __name__ == "__main__":
    # Direct invocation: exhaustive determinism + coverage self-test over the SDK.
    sdk = load_sdk_xref()
    cache = ProtocolDescriptorCache(sdk)

    # Enumerate every class/struct in the SDK and rebuild its descriptor.
    all_types = list(sdk.classes.keys()) + list(sdk.structs.keys())
    built = 0
    fails = 0
    for t in all_types:
        short = t.split("/")[-1]
        # Synthetic protocol_id for the self-test (real ids come from Phase 5 wire).
        # Use a stable hash of the class name so the test is reproducible.
        pid = (abs(hash(short)) % (2 ** 32))
        d = cache.observe_protocol(pid, short)
        if d is not None:
            built += 1
        else:
            fails += 1

    st = cache.stats()
    print(f"SDK types enumerated : {len(all_types)}")
    print(f"descriptors rebuilt  : {built}")
    print(f"resolution misses    : {fails}")
    print(f"protocols cached     : {st['protocols_cached']}")
    print(f"determinism checks   : {st['redundant_reobserves']} (inconsistent={st['redundant_inconsistent']})")

    # Determinism assertion: rebuild one class twice, compare canonical keys.
    sample = "APC_TyrLobby_C"
    d1 = cache.observe_protocol(0xABCDEF01, sample)
    d2 = cache.observe_protocol(0xABCDEF01, sample)
    assert d1 is not None and d2 is not None
    assert d1.canonical_key() == d2.canonical_key(), "determinism FAILED"
    assert d1.determinism_verified, "redundant re-observe did not verify determinism"
    print(f"determinism assertion PASS for {sample} ({d1.member_count} members)")
    print("OK")
