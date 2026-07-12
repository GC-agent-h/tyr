"""
iris_netrefhandle_cache.py — Phase 04 (sub-step 1): NetRefHandleCache.

Builds the lookup layer that turns opaque Iris stream IDs into meaningful
references, per docs/04-guid-cache-netfieldexport.md ("A. FNetRefHandle -> Object/Class
resolution"). This sub-step targets STATIC path-name resolution (handles bound to a
UObject/UClass via a NetToken path string), confirming the Iris bit-layout and
path-resolution mechanism from source rather than assuming legacy's shape.

Design (per phase doc, "Implementation approach" #1):
  * The cache is populated incrementally in FILE ORDER by a single forward
    streaming pass. As the Phase 05 packet walker encounters a FNetRefHandle
    export or a NetToken export, it calls NetRefHandleCache.observe_handle(...)
    / .observe_token_export(...) immediately. Caches are populated and consulted
    interleaved, exactly like the legacy GuidCache streaming pass.
  * Static vs dynamic is NOT the legacy single static/dynamic flag on a flat GUID.
    In Iris it is derived from the FNetRefHandle Id parity (Static=odd Id, dynamic
    =even Id; NetRefHandle.h:60-64). We record that explicitly and never assume
    legacy's convention.

What this module does NOT yet do (later sub-steps / phases):
  * Dynamic spawn-info resolution (ObjectReplicationBridge.cpp spawn path) — sub-step 2.
  * The FNetToken store cache's full per-TypeId payload variety — sub-step 3.
  * The replication protocol/descriptor schema cache — separate cache, later.
  * Decoding the raw packet bytes — that is Phase 05. This module is the *consumer*
    contract: it exposes observe_* methods the Phase 05 walker will call.

Static path-name resolution model (source: ObjectReferenceCache.cpp):
  * A static object reference is expressed as FNetRefHandle::Invalid + a path
    FNetToken (ObjectReferenceCache.cpp:257-270 GetOrCreateObjectReferenceUsingPath:
    MakeNetObjectReference(InvalidHandle, ObjectPathToken)). The path string is the
    object's GetPathName() stored in the FStringTokenStore.
  * When the object is first actually created on the remote side, a complete
    FNetRefHandle (with Id) is bound to that path token. So the binding
    (handle -> path string) is formed by correlating the token export (which carries
    the FString) with the handle reference that uses it.

We therefore keep TWO correlated tables and expose both:
  * token_store:  token -> payload string   (the path/name dictionary)
  * handle_cache: handle -> ResolvedInfo    (static or dynamic)
and a deferred-binding mechanism: when a static handle reference arrives carrying a
token (but no complete Id yet, e.g. Invalid handle in an inline reference), we attach
the token; when the same token later appears with a complete Id (spawn), we bind it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from iris_handles import (
    NetRefHandle,
    NetToken,
    read_net_token,
    read_net_object_reference,
    NetObjectReference,
    read_token_data_fstring,
)


@dataclass
class ResolvedInfo:
    # The FNetRefHandle key (raw_id + reconstructable replication_system_id).
    handle: NetRefHandle

    # Static handles resolved by path token; dynamic by spawn.
    kind: str = "unknown"          # "static_path" | "dynamic" | "static_external" | "unknown"

    # For static path resolution: the path string resolved from the NetToken store.
    path: Optional[str] = None

    # Source provenance: where this binding was first established in the stream.
    first_seen_chunk: Optional[int] = None
    first_seen_offset_bits: Optional[int] = None

    # Decoding notes / uncertainty flags (forensic discipline: surface unknowns).
    notes: str = ""

    @property
    def is_static(self) -> bool:
        return self.kind in ("static_path", "static_external")

    @property
    def is_dynamic(self) -> bool:
        return self.kind == "dynamic"


@dataclass
class TokenEntry:
    token: NetToken
    payload: str
    type_id: int
    first_seen_chunk: Optional[int] = None
    first_seen_offset_bits: Optional[int] = None
    bound_to_handle: Optional[int] = None   # raw_id of the handle that uses this token


class NetRefHandleCache:
    def __init__(self, replication_system_id: int = 1):
        self.replication_system_id = replication_system_id

        # token (NetToken.value()) -> TokenEntry
        self.token_store: Dict[int, TokenEntry] = {}

        # handle (raw_id) -> ResolvedInfo  (also holds "pending" path references,
        # keyed by ("pending", token.value()) until a complete handle arrives).
        self.handle_cache: Dict[object, ResolvedInfo] = {}

        # Pending bindings: path token payload we have seen but not yet attached
        # to a complete handle. Keyed by payload string (object path is unique).
        self._pending_path_tokens: Dict[str, NetToken] = {}
        # Pending by token value: for invalid-handle references seen before their
        # token export arrives. Keyed by token.value() -> pending cache key.
        self._pending_tokens: Dict[int, object] = {}

        self._export_count = 0

    # -- NetToken export (path/name dictionary) -----------------------------
    def observe_token_export(
        self,
        token: NetToken,
        payload: str,
        chunk_index: Optional[int] = None,
        offset_bits: Optional[int] = None,
    ) -> TokenEntry:
        """Record a NetToken export (the FString payload for a path/name token).

        This is called by the Phase 05 walker for each (ReadNetToken, ReadTokenData)
        pair emitted by UNetTokenDataStream::ReadData (NetTokenDataStream.cpp:207).
        """
        entry = TokenEntry(
            token=token,
            payload=payload,
            type_id=token.type_id,
            first_seen_chunk=chunk_index,
            first_seen_offset_bits=offset_bits,
        )
        self.token_store[token.value()] = entry
        self._export_count += 1

        # If some handle reference is waiting on this exact path, bind it now.
        if payload in self._pending_path_tokens:
            pending = self._pending_path_tokens.pop(payload)
            for info in self.handle_cache.values():
                if isinstance(info, ResolvedInfo) and info.path is None \
                        and info.notes.startswith("pending_token:"):
                    stored = _reconstruct_token(info.notes[len("pending_token:"):])
                    if stored is not None and stored.value() == pending.value():
                        info.path = payload
                        info.kind = "static_path"
                        entry.bound_to_handle = info.handle.raw_id
        # If an invalid-handle reference arrived before this token export, bind it.
        if token.value() in self._pending_tokens:
            pkey = self._pending_tokens.pop(token.value())
            pin = self.handle_cache.get(pkey)
            if isinstance(pin, ResolvedInfo) and pin.path is None:
                pin.path = payload
                pin.kind = "static_path"
                entry.bound_to_handle = pin.handle.raw_id
        return entry

    # -- FNetRefHandle reference (inline in the stream) ---------------------
    def observe_handle(
        self,
        handle: NetRefHandle,
        path_token: Optional[NetToken] = None,
        kind_hint: Optional[str] = None,
        chunk_index: Optional[int] = None,
        offset_bits: Optional[int] = None,
    ) -> ResolvedInfo:
        """Record/refresh a FNetRefHandle reference seen in file order.

        handle      : decoded FNetRefHandle (raw_id + rsid context).
        path_token  : if the reference carried a path token (static-path reference,
                      e.g. MakeNetObjectReference(InvalidHandle, PathToken)), supply it.
        kind_hint   : optional pre-classification from the walker ("static_path",
                      "dynamic", ...). Otherwise derived from Id parity.
        """
        if not handle.is_valid:
            # An invalid handle with a path token is a pure path reference (no Id yet).
            if path_token is not None:
                payload = self.token_store.get(path_token.value())
                payload_str = payload.payload if payload is not None else None
                # Track the pending reference keyed by token value so the later
                # token export (which carries the payload string) can bind to it.
                info = ResolvedInfo(
                    handle=handle,
                    kind="static_path" if path_token is not None else "unknown",
                    path=payload_str,
                    first_seen_chunk=chunk_index,
                    first_seen_offset_bits=offset_bits,
                    notes=("pending_token:" + _token_to_str(path_token)) if path_token else "",
                )
                self.handle_cache.setdefault(("pending", path_token.value()), info)
                if payload_str is None:
                    # Token not yet exported: remember to bind once it arrives.
                    self._pending_tokens[path_token.value()] = ("pending", path_token.value())
                else:
                    self._pending_path_tokens.setdefault(payload_str, path_token)
                return info

        raw_id = handle.raw_id
        existing = self.handle_cache.get(raw_id)
        if existing is not None:
            # Already bound; update provenance only if missing.
            if existing.first_seen_chunk is None:
                existing.first_seen_chunk = chunk_index
                existing.first_seen_offset_bits = offset_bits
            return existing

        # Classify.
        if kind_hint is not None:
            kind = kind_hint
        elif handle.is_static:
            kind = "static_path"
        elif handle.is_dynamic:
            kind = "dynamic"
        else:
            kind = "unknown"

        # If a path token was supplied, resolve it immediately.
        path = None
        if path_token is not None:
            entry = self.token_store.get(path_token.value())
            if entry is not None:
                path = entry.payload
                entry.bound_to_handle = raw_id
                if kind == "unknown":
                    kind = "static_path"

        info = ResolvedInfo(
            handle=handle,
            kind=kind,
            path=path,
            first_seen_chunk=chunk_index,
            first_seen_offset_bits=offset_bits,
            notes=("token:" + _token_to_str(path_token)) if path_token else "",
        )
        self.handle_cache[raw_id] = info
        return info

    # -- FNetObjectReference (inline, dynamic-spawn resolution) ------------
    def observe_object_reference(
        self,
        ref: "NetObjectReference",
        chunk_index: Optional[int] = None,
        offset_bits: Optional[int] = None,
    ) -> List[ResolvedInfo]:
        """Consume a decoded FNetObjectReference (from read_net_object_reference,
        mirroring ObjectReferenceCache::ReadFullReferenceInternal) and correlate it
        into the cache.

        For a DYNAMIC reference this is the spawn-info path: the reference carries
        the (even-Id) FNetRefHandle, the path token (class/path string), and the
        outer reference recursively. We record each handle, bind the path, and walk
        the outer chain. Returns the list of ResolvedInfo records touched.

        For a STATIC reference the path resolves via the NetToken store (sub-step 1);
        here we just ensure the handle + path are cached.
        """
        touched: List[ResolvedInfo] = []
        if not ref.handle.is_valid:
            return touched

        # Bind the path token payload if exported inline in this reference.
        path = None
        if ref.path_token is not None:
            # The inline path token may or may not also be in the global token store.
            cached = self.token_store.get(ref.path_token.value())
            if cached is not None:
                path = cached.payload
            elif ref.path_payload is not None:
                # Register the inline path token as a token export (it was sent here).
                entry = self.observe_token_export(
                    ref.path_token, ref.path_payload, chunk_index, offset_bits)
                path = ref.path_payload
                cached = entry
            if cached is not None and cached.bound_to_handle is None:
                cached.bound_to_handle = ref.handle.raw_id

        # Record/refresh the handle.
        info = self.observe_handle(
            ref.handle,
            path_token=ref.path_token,
            kind_hint="dynamic" if ref.handle.is_dynamic else "static_path",
            chunk_index=chunk_index,
            offset_bits=offset_bits,
        )
        if path is not None and info.path is None:
            info.path = path
            if info.kind == "unknown":
                info.kind = "dynamic" if ref.handle.is_dynamic else "static_path"
        touched.append(info)

        # Recurse into the outer reference chain.
        if ref.outer is not None:
            touched.extend(self.observe_object_reference(
                ref.outer, chunk_index, offset_bits))
        return touched


    # -- queries -----------------------------------------------------------
    def resolve_handle(self, handle: NetRefHandle) -> Optional[ResolvedInfo]:
        if not handle.is_valid:
            # Maybe a pending path reference.
            return None
        return self.handle_cache.get(handle.raw_id)

    def resolve_token(self, token: NetToken) -> Optional[TokenEntry]:
        return self.token_store.get(token.value())

    def stats(self) -> dict:
        static = sum(1 for i in self.handle_cache.values()
                     if isinstance(i, ResolvedInfo) and i.is_static)
        dynamic = sum(1 for i in self.handle_cache.values()
                      if isinstance(i, ResolvedInfo) and i.is_dynamic)
        pending = sum(1 for i in self.handle_cache.values()
                      if isinstance(i, ResolvedInfo) and i.kind == "unknown")
        return {
            "token_exports": len(self.token_store),
            "handle_refs": len(self.handle_cache),
            "static": static,
            "dynamic": dynamic,
            "unknown_kind": pending,
            "pending_path_tokens": len(self._pending_path_tokens),
            "total_exports_observed": self._export_count,
        }


# Internal helpers ---------------------------------------------------------
def _token_to_str(token: NetToken) -> str:
    return f"{token.index}:{token.type_id}:{1 if token.is_assigned_by_authority else 0}"


# NetToken.from_parts_str is not defined on NetToken; provide local reconstructor.
def _reconstruct_token(s: str) -> Optional[NetToken]:
    parts = s.split(":")
    if len(parts) != 3:
        return None
    try:
        index, type_id, auth = (int(p) for p in parts)
    except ValueError:
        return None
    return NetToken(index=index, type_id=type_id, is_assigned_by_authority=bool(auth))
