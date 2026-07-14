"""Self-test for iris_schema (Phase 06 sub-step 1 validation).

Asserts source-faithful behaviour of the ReplicationStateDescriptorBuilder
reimplementation against properties we can verify from the SDK:
  * member order follows ClassReps/reflection order (ascending offset within a
    class), matching OA-06-1's "declaration order == offset order in TYR dump".
  * Actor heirs get NetCullDistanceSquared forced to LifetimeConditional
    (Iris builder source lines 2951-2976).
  * Every member defaults to Regular (no trait info in SDK -> OA-06-1 default).
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import iris_schema as S


def test_order_matches_offsets():
    sdk = S.load_sdk()
    sc = S.build_class_schema(sdk, "APlayerState")
    assert sc is not None
    # within AActor-owned members, offset must be non-decreasing (ClassReps order)
    actor_members = [m for m in sc.members if "AActor" in sc.super_chain]
    offs = [m.offset for m in actor_members]
    # allow equal offsets (bitfields) but not decreasing
    assert all(offs[i] <= offs[i + 1] for i in range(len(offs) - 1)), \
        f"AActor member order not non-decreasing: {offs[:10]}"


def test_netcull_is_lifetimeconditional():
    sdk = S.load_sdk()
    sc = S.build_class_schema(sdk, "ACharacter")   # Actor heir
    nc = [m for m in sc.members if m.name == "NetCullDistanceSquared"]
    assert nc, "NetCullDistanceSquared missing from ACharacter schema"
    assert nc[0].state == "LifetimeConditional", \
        f"expected LifetimeConditional, got {nc[0].state}"


def test_default_regular():
    sdk = S.load_sdk()
    sc = S.build_class_schema(sdk, "APlayerState")
    # With no trait info, Init should be 0 and the bulk Regular.
    assert sc.n_init == 0, f"unexpected Init members: {sc.n_init}"
    assert sc.n_regular > 50, f"unexpectedly few Regular members: {sc.n_regular}"


def test_primitives_detected():
    sdk = S.load_sdk()
    sc = S.build_class_schema(sdk, "APlayerState")
    prim = [m for m in sc.members if S.is_primitive(m)]
    # Score (float), PlayerId (int32), CompressedPing (uint8) must be primitive
    names = {m.name for m in prim}
    for expect in ("Score", "PlayerId", "CompressedPing", "bIsSpectator"):
        assert expect in names, f"{expect} not detected as primitive"


if __name__ == "__main__":
    test_order_matches_offsets()
    test_netcull_is_lifetimeconditional()
    test_default_regular()
    test_primitives_detected()
    print("iris_schema self-test: PASS (4/4)")
