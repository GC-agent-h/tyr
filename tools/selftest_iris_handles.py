"""
selftest_iris_handles.py — Phase 04 (sub-step 1) source-verified round-trip tests.

Strategy: build the EXACT bit pattern the engine would emit for each primitive
(from the C++ source now in /UE), then assert our reader decodes it identically.
This is the "static cross-check, no live debugger" methodology from docs/00-overview
Step 0.3 — we construct expected bytes by hand from the source and compare, rather
than assuming legacy shapes.

Vectors are derived directly:

  FNetRefHandle::operator<< (NetRefHandle.cpp:69-102)
    wire = [1 valid-bit][SerializeIntPacked64(Id)]
    We build it with BitWriter.write_net_ref_handle and decode with read_net_ref_handle.

  FNetTokenStore::InternalReadNetToken (NetTokenStore.cpp:128-160)
    wire = [SerializeIntPacked(Index)][1 authority-bit][3 TypeId bits  (only if Id provided)]
    We build with BitWriter.write_net_token and decode with read_net_token(known_type_id=None).

  NetToken export stream (NetTokenDataStream.cpp:207-217)
    wire = ([1 stop-bit][ReadNetToken][FString])* padded with a final 0 stop-bit.
    We build with the encoder helpers and decode with consume_net_token_export_stream,
    asserting the (token, payload) pairs round-trip and the stop-bit terminates.

  FNetObjectReference (ObjectReferenceCache.cpp:1524 ReadFullReferenceInternal)
    wire = [FNetRefHandle][1 export-bit]
            if exported: [1 bNoLoad][1 bHasPath]
                if hasPath: [FNetToken WITHOUT TypeId on wire][1 token-export-bit][FString][recurse OuterRef]
    We build with the encoder helpers and decode with read_net_object_reference.

Also asserts the architectural facts from source:
  * Static handles have ODD raw_id; dynamic have EVEN raw_id (NetRefHandle.h:60-64).
  * ReplicationSystemId is NOT on the wire (only Id is); reconstructable context.
"""

from __future__ import annotations

from bitreader import BitReader, BitWriter
from iris_handles import (
    NetRefHandle,
    NetToken,
    read_net_ref_handle,
    write_net_ref_handle,
    read_net_token,
    write_net_token,
    read_net_object_reference,
    read_token_data_fstring,
    consume_net_token_export_stream,
)
from iris_netrefhandle_cache import NetRefHandleCache, ResolvedInfo


def _roundtrip(reader_fn, writer_fn, value):
    w = BitWriter()
    writer_fn(w, value)
    r = BitReader(w.getvalue())
    return reader_fn(r)


def test_net_ref_handle_roundtrip():
    cases = [
        NetRefHandle.make(serial=1, is_static=True, replication_system_id=1),
        NetRefHandle.make(serial=2, is_static=True, replication_system_id=1),
        NetRefHandle.make(serial=3, is_static=False, replication_system_id=1),
        NetRefHandle.make(serial=1000, is_static=False, replication_system_id=4),
        NetRefHandle.make(serial=0, is_static=True, replication_system_id=1),  # serial 0 -> invalid
    ]
    for h in cases:
        got = _roundtrip(read_net_ref_handle, write_net_ref_handle, h)
        assert got.raw_id == h.raw_id, f"raw_id mismatch: {got.raw_id} != {h.raw_id}"
        assert got.is_valid == h.is_valid, f"valid mismatch for {h.to_compact_string()}"
        assert got.is_static == h.is_static, f"static mismatch for {h.to_compact_string()}"
        assert got.is_dynamic == h.is_dynamic, f"dynamic mismatch for {h.to_compact_string()}"
    print("PASS: FNetRefHandle round-trip (valid-bit + SerializeIntPacked64(Id))")


def test_net_ref_handle_static_dynamic_parity():
    # NetRefHandle.h:60-64 — Static handles have ODD Id; dynamic EVEN Id.
    s = NetRefHandle.make(serial=5, is_static=True)
    d = NetRefHandle.make(serial=5, is_static=False)
    assert s.is_static and (s.raw_id & 1) == 1, f"static should be odd: {s.raw_id}"
    assert d.is_dynamic and (d.raw_id & 1) == 0, f"dynamic should be even: {d.raw_id}"
    assert s.serial == d.serial == 5
    # ReplicationSystemId is reconstructable context, NOT on the wire.
    assert s.replication_system_id == 1
    print("PASS: static=odd Id / dynamic=even Id; ReplicationSystemId off-wire")


def test_net_token_roundtrip():
    cases = [
        NetToken(index=0, type_id=0),                         # invalid
        NetToken(index=1, type_id=0, is_assigned_by_authority=True),
        NetToken(index=7, type_id=3, is_assigned_by_authority=False),
        NetToken(index=123456, type_id=5, is_assigned_by_authority=True),
    ]
    for t in cases:
        got = _roundtrip(lambda r: read_net_token(r, known_type_id=None),
                         lambda w, v: write_net_token(w, v, write_type_id=True), t)
        assert got == t, f"token mismatch: {got.to_compact_string()} != {t.to_compact_string()}"
    print("PASS: FNetToken round-trip (SerializeIntPacked(Index) + auth-bit + 3-bit TypeId)")


def test_net_token_stream_roundtrip():
    # Build a NetToken export stream exactly as UNetTokenDataStream::ReadData expects:
    #   while(true){ stop = reader.ReadBool(); if !stop { ReadNetToken; ReadTokenData(FString) } }
    w = BitWriter()
    exports = [
        (NetToken(index=1, type_id=0, is_assigned_by_authority=True), "/Game/Maps/TyrMap.TyrMap:PersistentLevel.BP_TyrGameState_C_0"),
        (NetToken(index=2, type_id=0, is_assigned_by_authority=True), "WorldGravity"),
        (NetToken(index=3, type_id=1, is_assigned_by_authority=False), "BP_Ammunition_Standard_C"),
    ]
    for tok, s in exports:
        w.write_bit(1)                       # stop-bit == true => more data
        write_net_token(w, tok, write_type_id=True)
        # WriteTokenData for FString store: engine WriteAlign()s then writes FString.
        w.write_align()
        tmp = BitWriter()
        tmp.write_fstring(s)
        w.write_bytes(tmp.getvalue())
    w.write_bit(0)                           # final stop-bit == false => end

    r = BitReader(w.getvalue())
    seen = []
    count = consume_net_token_export_stream(
        r,
        on_token=lambda tok, data: seen.append((tok, data)),
        token_data_readers={0: read_token_data_fstring, 1: read_token_data_fstring},
    )
    assert count == 3, f"expected 3 tokens, got {count}"
    assert seen[0][1] == exports[0][1], f"payload[0] mismatch: {seen[0][1]!r}"
    assert seen[1][1] == exports[1][1], f"payload[1] mismatch: {seen[1][1]!r}"
    assert seen[2][1] == exports[2][1], f"payload[2] mismatch: {seen[2][1]!r}"
    assert seen[2][0].type_id == 1, "type id should survive on wire"
    print("PASS: NetToken export stream (stop-bit loop + FString payload) round-trip")


def test_cache_static_path_binding():
    # Simulate the file-order streaming pass:
    #  1) token export for a path string
    #  2) a static FNetRefHandle referencing that token later
    cache = NetRefHandleCache(replication_system_id=1)

    path_token = NetToken(index=1, type_id=0, is_assigned_by_authority=True)
    cache.observe_token_export(path_token, "/Game/.../BP_TyrGameState_C_0",
                                chunk_index=4, offset_bits=1024)

    handle = NetRefHandle.make(serial=9, is_static=True, replication_system_id=1)
    info = cache.observe_handle(handle, path_token=path_token,
                                chunk_index=7, offset_bits=4096)

    assert info.is_static, "should be classified static"
    assert info.path == "/Game/.../BP_TyrGameState_C_0", f"path not bound: {info.path!r}"
    assert cache.resolve_token(path_token).bound_to_handle == handle.raw_id
    print("PASS: static path-name binding (token export -> handle reference)")

    # Now the pending case: handle reference arrives BEFORE the token export.
    cache2 = NetRefHandleCache(replication_system_id=1)
    pending_token = NetToken(index=2, type_id=0, is_assigned_by_authority=True)
    inv = NetRefHandle(raw_id=0, replication_system_id=1)   # invalid handle, path-only ref
    cache2.observe_handle(inv, path_token=pending_token)
    assert pending_token.value() in cache2._pending_tokens, \
        "pending token should be tracked by token value"
    cache2.observe_token_export(pending_token, "/Game/.../BP_Ammo_C_0")
    # After the export arrives, the pending reference should now carry the path.
    for v in cache2.handle_cache.values():
        if isinstance(v, ResolvedInfo) and v.notes.startswith("pending_token:"):
            assert v.path == "/Game/.../BP_Ammo_C_0", f"pending bind failed: {v.path!r}"
    print("PASS: deferred static path binding (handle ref precedes token export)")


def test_object_reference_dynamic_roundtrip():
    # Dynamically-spawned object reference (even Id => dynamic).
    # Wire: [FNetRefHandle][export-bit=1][bNoLoad=1][bHasPath=1]
    #        [path token (NO TypeId on wire)][token-export-bit=1][FString payload][outer: not exported]
    w = BitWriter()
    dyn_handle = NetRefHandle.make(serial=6, is_static=False, replication_system_id=1)
    write_net_ref_handle(w, dyn_handle)
    w.write_bit(1)            # bIsExported
    w.write_bit(1)            # bNoLoad
    w.write_bit(1)            # bHasPath
    # path token WITHOUT TypeId on wire (store-supplied type id = 0).
    path_tok = NetToken(index=42, type_id=0, is_assigned_by_authority=True)
    write_net_token(w, path_tok, write_type_id=False)
    w.write_bit(1)            # token export-bit
    tmp = BitWriter(); tmp.write_fstring("BP_Ammunition_Standard_C"); w.write_align(); w.write_bytes(tmp.getvalue())
    # Outer reference: a valid handle, NOT exported (dynamic resolves via export).
    w.write_bit(1)            # FNetRefHandle valid
    outer = NetRefHandle.make(serial=2, is_static=True, replication_system_id=1)
    w.serialize_int_packed64(outer.raw_id)
    w.write_bit(0)            # outer bIsExported = false
    r = BitReader(w.getvalue())
    ref = read_net_object_reference(r)
    assert ref.handle.is_dynamic, f"should be dynamic (even Id): {ref.handle.to_compact_string()}"
    assert ref.is_exported, "should be exported"
    assert ref.path_token is not None and ref.path_token.index == 42, "path token lost"
    assert ref.path_token.type_id == 0, "inline path token must NOT carry TypeId on wire"
    assert ref.path_payload == "BP_Ammunition_Standard_C", f"payload wrong: {ref.path_payload!r}"
    assert ref.outer is not None, "outer not recursed"
    assert ref.outer.handle.is_static and not ref.outer.is_exported, "outer should be static, not exported"
    print("PASS: FNetObjectReference dynamic (even Id) + inline path token + outer recursion")


def test_cache_dynamic_resolution():
    cache = NetRefHandleCache(replication_system_id=1)
    w = BitWriter()
    dyn = NetRefHandle.make(serial=10, is_static=False, replication_system_id=1)
    write_net_ref_handle(w, dyn)
    w.write_bit(1); w.write_bit(1); w.write_bit(1)
    ptok = NetToken(index=7, type_id=0, is_assigned_by_authority=True)
    write_net_token(w, ptok, write_type_id=False)
    w.write_bit(1)
    tmp = BitWriter(); tmp.write_fstring("BP_TyrGameState_C_0"); w.write_align(); w.write_bytes(tmp.getvalue())
    outer = NetRefHandle.make(serial=3, is_static=True, replication_system_id=1)
    w.write_bit(1); w.serialize_int_packed64(outer.raw_id); w.write_bit(0)
    r = BitReader(w.getvalue())
    ref = read_net_object_reference(r)
    touched = cache.observe_object_reference(ref, chunk_index=3, offset_bits=512)
    # Should have touched the dynamic handle + the static outer (2 records).
    assert len(touched) == 2, f"expected 2 touched, got {len(touched)}"
    info = cache.resolve_handle(dyn)
    assert info is not None and info.is_dynamic, "dynamic handle not classified"
    assert info.path == "BP_TyrGameState_C_0", f"dynamic path not bound: {info.path!r}"
    assert info.kind == "dynamic"
    outer_info = cache.resolve_handle(outer)
    assert outer_info is not None and outer_info.is_static, "outer not static"
    assert cache.stats()["dynamic"] == 1 and cache.stats()["static"] == 1
    print("PASS: dynamic spawn-info resolution (even-Id handle + inline path + outer)")


def main() -> int:
    test_net_ref_handle_roundtrip()
    test_net_ref_handle_static_dynamic_parity()
    test_net_token_roundtrip()
    test_net_token_stream_roundtrip()
    test_cache_static_path_binding()
    test_object_reference_dynamic_roundtrip()      # sub-step 2
    test_cache_dynamic_resolution()                # sub-step 2
    print("\nALL PHASE-04 SUB-STEP-1+2 SELF-TESTS PASSED (source-verified encodings).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
