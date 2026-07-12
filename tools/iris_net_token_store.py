"""iris_net_token_store.py — Phase 04 (sub-step 3): standalone FNetToken store cache.

This is the FNetToken-store cache from docs/04-guid-cache-netfieldexport.md
("FNetToken store cache implemented for path/name resolution"), conceptually
distinct from handle resolution (sub-steps 1/2).

SOURCE-VERIFIED MODEL (do not assume legacy shape):

  FNetTokenStore (NetTokenStore.h:206, NetTokenStore.cpp)
    * Owns TYPED FNetTokenDataStore instances, each with its own FTypeId.
    * TypeId width: TokenTypeIdBits = 3  => MaxTypeIdCount = 8  (NetToken.h:32,37).
    * Each store has its OWN per-type Index space (0..MaxNetTokenCount).
    * Resolution is two-dimensional: (TypeId, Index) -> payload.
    * Dispatcher FNetTokenStore::ReadTokenData (NetTokenStore.cpp:448) selects the
      store by NetToken.GetTypeId() and calls its ReadTokenData to fetch the payload.

  FNetTokenStoreState (NetTokenStore.h:275 comment)
    * Maps NetTokenIndex -> NetTokenStoreKey (per TypeId). Remote and local states
      are SEPARATE. On the receiving (replay/client) side we import into the
      REMOTE state. ValidateAndStoreNetTokenData (line 416) does
      ReserveTokenCount(TypeId, Index+1) and stores StoreKey at TokenInfoArray[TypeId][Index].

  Payload serialization:
    * FStringTokenStore::ReadTokenData (StringTokenStore.cpp:122) -> ReadString (ReadAlign'd FString).
    * FNameTokenStore::ReadTokenData   (NameTokenStore.cpp:115)   -> ReadString (ReadAlign'd FString) -> FName.
    * Any typed store's payload here is therefore an FString; we decode as FString and
      record the optional FName conversion where the type id is the Name store.

  Export import stream (UNetTokenDataStream::ReadData, NetTokenDataStream.cpp:194):
        while (Reader->ReadBool())
            Token   = NetTokenStore->ReadNetToken(Context)   # WITH TypeId on wire
            NetTokenStore->ReadTokenData(Context, Token, *RemoteNetTokenStoreState)
    This is exactly consume_net_token_export_stream() in iris_handles.py.

  Authority flag: a token assigned by the authority (server) carries
    IsAssignedByAuthority=true. The export stream only ever carries valid tokens.

This module provides:
  * NetTokenStoreCache: typed (TypeId -> {Index -> payload}) store with import
    from the export stream and (TypeId, Index) -> payload resolution, including a
    FNetTokenStoreState-style index-count validity guard.
  * Helpers to import a whole stream and to look up by FNetToken.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from iris_handles import (
    NetToken,
    read_net_token,
    read_token_data_fstring,
    consume_net_token_export_stream,
    DEFAULT_TOKEN_DATA_READERS,
)

# From NetToken.h:32,37 — TypeId is 3 bits => 8 possible typed stores.
MAX_TYPE_ID_COUNT = 8
INVALID_TOKEN_TYPE_ID = (~0) & 0xFFFFFFFF  # FNetToken::InvalidTokenTypeId


@dataclass
class TokenStoreEntry:
    """A single resolved token payload within a typed store."""
    type_id: int
    index: int
    payload: str
    is_assigned_by_authority: bool
    # For Name-typed stores the payload is also a valid FName; store the raw string
    # regardless and let consumers decide. first_seen provenance:
    first_seen_chunk: Optional[int] = None
    first_seen_offset_bits: Optional[int] = None


class NetTokenStoreCache:
    """Standalone FNetToken store cache (typed stores, remote-state resolution).

    Mirrors the resolution model of FNetTokenStore + FNetTokenStoreState:
    resolution is (TypeId, Index) -> payload, with a per-TypeId index-count guard
    analogous to FNetTokenStoreState::ReserveTokenCount / TokenInfoArray sizing.
    """

    def __init__(self) -> None:
        # type_id -> { index -> TokenStoreEntry }
        self._stores: Dict[int, Dict[int, TokenStoreEntry]] = {}
        # type_id -> high-water Index count seen (mirrors FNetTokenStoreState sizing)
        self._type_index_counts: Dict[int, int] = {}
        self._total_imports = 0

    # -- import -------------------------------------------------------------
    def import_token(self, token: NetToken, payload: str,
                     chunk_index: Optional[int] = None,
                     offset_bits: Optional[int] = None) -> Optional[TokenStoreEntry]:
        """Record a single (token, payload) pair, as produced by the export stream.

        Source: UNetTokenDataStream::ReadData -> FNetTokenStore::ReadTokenData
        -> ValidateAndStoreNetTokenData (NetTokenStore.cpp:416): reserves
        Index+1 slots for the type and stores StoreKey at [TypeId][Index].
        """
        if not token.is_valid:
            # The engine never exports an invalid token; defensive no-op.
            return None

        type_id = token.type_id
        index = token.index

        # Reserve index space (mirrors ReserveTokenCount / TokenInfoArray sizing).
        cur = self._type_index_counts.get(type_id, 0)
        if index + 1 > cur:
            self._type_index_counts[type_id] = index + 1

        store = self._stores.setdefault(type_id, {})
        entry = TokenStoreEntry(
            type_id=type_id,
            index=index,
            payload=payload,
            is_assigned_by_authority=token.is_assigned_by_authority,
            first_seen_chunk=chunk_index,
            first_seen_offset_bits=offset_bits,
        )
        # Re-exports of the same (TypeId, Index) must carry identical data
        # (ValidateAndStoreNetTokenData ensure); we keep the first / authoritative one.
        existing = store.get(index)
        if existing is None:
            store[index] = entry
        elif token.is_assigned_by_authority and not existing.is_assigned_by_authority:
            # Prefer the authoritative binding on re-import.
            store[index] = entry
        self._total_imports += 1
        return store[index]

    def import_export_stream(
        self,
        reader,
        chunk_index: Optional[int] = None,
        token_data_readers: Optional[Dict[int, Callable[[object], object]]] = None,
    ) -> int:
        """Consume a UNetTokenDataStream::ReadData export block and import every pair.

        Returns the number of tokens imported.
        """
        readers = token_data_readers if token_data_readers is not None else DEFAULT_TOKEN_DATA_READERS

        def on_token(tok: NetToken, payload):
            # payload may be None if the selected reader returned nothing; skip.
            if payload is None:
                return
            self.import_token(tok, payload, chunk_index=chunk_index)

        return consume_net_token_export_stream(reader, on_token, readers)

    # -- queries ------------------------------------------------------------
    def resolve(self, token: NetToken) -> Optional[TokenStoreEntry]:
        """Resolve a FNetToken to its payload, mirroring FNetTokenStoreState lookup.

        Returns None if the (TypeId, Index) was never imported.
        """
        if not token.is_valid:
            return None
        store = self._stores.get(token.type_id)
        if store is None:
            return None
        return store.get(token.index)

    def resolve_payload(self, token: NetToken) -> Optional[str]:
        entry = self.resolve(token)
        return entry.payload if entry is not None else None

    def get_store(self, type_id: int) -> Dict[int, TokenStoreEntry]:
        return self._stores.get(type_id, {})

    def stats(self) -> dict:
        per_type = {tid: len(store) for tid, store in self._stores.items()}
        return {
            "total_imports": self._total_imports,
            "type_ids_present": sorted(self._stores.keys()),
            "per_type_count": per_type,
            "max_type_id": max(self._stores.keys()) if self._stores else -1,
        }

    def all_entries(self) -> List[TokenStoreEntry]:
        out: List[TokenStoreEntry] = []
        for store in self._stores.values():
            out.extend(store.values())
        return out
