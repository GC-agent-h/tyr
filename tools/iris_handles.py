"""
iris_handles.py — Phase 04 (sub-step 1): source-verified Iris wire decoders for
FNetRefHandle and FNetToken, plus the NetToken export-stream consumer.

Every encoding below is taken DIRECTLY from the engine source now present in this
repo (no legacy assumption, no guesswork):

  FNetRefHandle (wire)          UE/NetRefHandle.h
                                UE/Iris/Private/Iris/ReplicationSystem/NetRefHandle.cpp:69-102
    * Layout (NetRefHandle.h:36-89):
        Static               : 1 bit
        Serial               : 53 bits   (UE_NET_IRIS_NETREFHANDLE_SERIAL_SIZE)
        ReplicationSystemId  : 10 bits
      -> Id = (Serial << 1) | (Static & 1);  GetId() returns Id.
      -> Static handles have ODD Id; dynamic handles have EVEN Id.
    * operator<< (NetRefHandle.cpp:69):
        bIsValid  = SerializeBool()
        if valid:  Id = SerializeIntPacked64()     # only the 54-bit Id is on the wire
      The ReplicationSystemId is NOT serialized; it is reconstructed via
      MakeNetRefHandleFromId(Id, ReplicationSystemId) using the local
      replication system id. We therefore accept replication_system_id as
      context when decoding (defaults to 1, matching a single-replication-system
      demo recording).

  FNetToken (wire)             UE/NetToken.h
                                UE/Iris/Private/Iris/ReplicationSystem/NetTokenStore.cpp:128-177
    * Layout (NetToken.h:97-107):
        Index       : 20 bits (TokenBits)
        TypeId      : 3  bits (TokenTypeIdBits)
        bIsAuth     : 1  bit
    * InternalReadNetToken (NetTokenStore.cpp:128):
        Index    = ReadPackedUint32()              # = SerializeIntPacked
        if Index != 0:
            bIsAuth  = ReadBool()
            if known_type_id == InvalidTokenTypeId:
                TypeId = ReadBits(3)               # only read TypeId when not provided
      When read inside a typed store (e.g. FStringTokenStore::ReadNetToken) the
      TypeId is NOT on the wire (known_type_id supplied); in the NetTokenDataStream
      export loop the TypeId IS on the wire.

  NetToken export stream       UE/Iris/Private/Iris/ReplicationSystem/NetTokenDataStream.cpp:207-217
    * ReadData loop:
        while (Reader->ReadBool())
            Token = NetTokenStore->ReadNetToken(Context)        # TypeId ON wire
            NetTokenStore->ReadTokenData(Context, Token, ...)    # per-TypeId FString
      ReadTokenData for FString/Name store = an FString
      (StringTokenStore.cpp:122-138 / NameTokenStore.cpp:122-136).

Decoder primitives are reused from tools/bitreader.py (LSB-first, SerializeIntPacked
and SerializeIntPacked64 already proven byte-exact vs the engine). The encoder
helpers here are used ONLY by the self-test round-trip (tools/selftest_iris_handles.py);
the engine is the encoder in production.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

from bitreader import BitReader, BitWriter


# ---------------------------------------------------------------------------
# FNetRefHandle
# ---------------------------------------------------------------------------
@dataclass
class NetRefHandle:
    raw_id: int                 # the 54-bit value carried on the wire: (Serial<<1)|Static
    replication_system_id: int = 1   # reconstructable context, not on the wire

    # Layout constants straight from NetRefHandle.h.
    SERIAL_BITS = 53
    STATIC_BITS = 1
    REPLICATION_SYSTEM_ID_BITS = 10
    ID_BITS = STATIC_BITS + SERIAL_BITS          # 54
    MAX_REPLICATION_SYSTEM_ID = (1 << REPLICATION_SYSTEM_ID_BITS) - 1

    @property
    def is_valid(self) -> bool:
        # Fields.Serial != InvalidValue (0). raw_id==0 means invalid.
        return self.raw_id != 0

    @property
    def is_static(self) -> bool:
        # Static handles have ODD Id (Static bit set).
        return self.is_valid and (self.raw_id & 1) == 1

    @property
    def is_dynamic(self) -> bool:
        return self.is_valid and not self.is_static

    @property
    def serial(self) -> int:
        return self.raw_id >> 1

    @property
    def is_complete(self) -> bool:
        # IsCompleteHandle: valid and replication_system_id != 0.
        return self.is_valid and self.replication_system_id != 0

    @classmethod
    def make(cls, serial: int, is_static: bool, replication_system_id: int = 1) -> "NetRefHandle":
        raw_id = ((serial << 1) & ((1 << cls.ID_BITS) - 1)) | (1 if is_static else 0)
        return cls(raw_id=raw_id, replication_system_id=replication_system_id)

    def __eq__(self, other: "NetRefHandle") -> bool:
        # Equality is on Id (per FNetRefHandle::operator== which compares GetId()).
        return isinstance(other, NetRefHandle) and other.raw_id == self.raw_id

    def __hash__(self) -> int:
        return hash(self.raw_id)

    def to_compact_string(self) -> str:
        kind = "INVALID" if not self.is_valid else ("STATIC" if self.is_static else "DYNAMIC")
        return (f"NetRefHandle[{kind} id={self.raw_id} serial={self.serial} "
                f"rsid={self.replication_system_id}]")


def read_net_ref_handle(reader: BitReader, replication_system_id: int = 1) -> NetRefHandle:
    """Mirror FNetRefHandle::operator<< (NetRefHandle.cpp:69-102).

    Wire: 1 valid-bit, then (if valid) SerializeIntPacked64(Id).
    The ReplicationSystemId is reconstructed from context, not read.
    """
    b_is_valid = reader.read_bit()
    if not b_is_valid:
        return NetRefHandle(raw_id=0, replication_system_id=replication_system_id)
    raw_id = reader.serialize_int_packed64()
    return NetRefHandle(raw_id=raw_id, replication_system_id=replication_system_id)


def write_net_ref_handle(writer: BitWriter, handle: NetRefHandle) -> None:
    """Encoder mirror of read_net_ref_handle — used by the self-test only."""
    writer.write_bit(1 if handle.is_valid else 0)
    if handle.is_valid:
        writer.serialize_int_packed64(handle.raw_id)


# ---------------------------------------------------------------------------
# FNetToken
# ---------------------------------------------------------------------------
@dataclass
class NetToken:
    index: int                 # TokenBits (20)
    type_id: int               # TokenTypeIdBits (3)
    is_assigned_by_authority: bool = False
    INVALID_INDEX = 0

    @property
    def is_valid(self) -> bool:
        return self.index != self.INVALID_INDEX

    def value(self) -> int:
        # Reconstruct the packed uint32 Value union for hashing/equality.
        v = (self.index & ((1 << 20) - 1)) | ((self.type_id & 7) << 20) | \
            ((1 if self.is_assigned_by_authority else 0) << 23)
        return v

    def __eq__(self, other: "NetToken") -> bool:
        return isinstance(other, NetToken) and other.value() == self.value()

    def __hash__(self) -> int:
        return hash(self.value())

    def to_compact_string(self) -> str:
        return (f"NetToken[idx={self.index} type={self.type_id} "
                f"auth={1 if self.is_assigned_by_authority else 0}]")


def read_net_token(reader: BitReader, known_type_id: Optional[int] = None) -> NetToken:
    """Mirror FNetTokenStore::InternalReadNetToken (NetTokenStore.cpp:128-160).

    Wire: SerializeIntPacked(Index); if Index != 0 { ReadBool(authority);
           if known_type_id is None: ReadBits(3, TypeId) }.

    known_type_id should be None when reading from the NetTokenDataStream export
    loop (TypeId IS on the wire); supply it only when decoding inside a typed
    store (e.g. FStringTokenStore::ReadNetToken passes its own TypeId).
    """
    index = reader.serialize_int_packed()
    if index == NetToken.INVALID_INDEX:
        return NetToken(index=0, type_id=0, is_assigned_by_authority=False)
    authority = bool(reader.read_bit())
    if known_type_id is None:
        type_id = reader.read_bits(3)
    else:
        type_id = known_type_id
    return NetToken(index=index, type_id=type_id, is_assigned_by_authority=authority)


def write_net_token(writer: BitWriter, token: NetToken, write_type_id: bool = True) -> None:
    """Encoder mirror of read_net_token — self-test only."""
    writer.serialize_int_packed(token.index)
    if token.index != NetToken.INVALID_INDEX:
        writer.write_bit(1 if token.is_assigned_by_authority else 0)
        if write_type_id:
            writer.write_bits(token.type_id, 3)


# ---------------------------------------------------------------------------
# NetToken payload (data) readers — per TypeId, the store reads an FString.
# ---------------------------------------------------------------------------
def read_token_data_fstring(reader: BitReader) -> str:
    """Mirror FStringTokenStore::ReadTokenData / FNameTokenStore::ReadTokenData
    (StringTokenStore.cpp:122-138, NameTokenStore.cpp:122-136): the store issues a
    ReadAlign() before reading the FString payload."""
    reader.read_align()
    s = reader.read_fstring()
    # UE FString::Serialize writes a null terminator; strip for clean storage.
    return s.rstrip("\x00")


# Map of TypeId -> payload reader. For sub-step 1 (static path-name resolution)
# the path/name tokens are FStrings; that is the only payload shape we decode.
# Additional type ids (e.g. GameplayTag) are wired in later sub-steps; until
# then an unknown type id is decoded as FString and flagged (see cache).
DEFAULT_TOKEN_DATA_READERS: Dict[int, Callable[[BitReader], object]] = {
    # type id 0 is the reserved/invalid token type; never carries data.
}


# ---------------------------------------------------------------------------
# NetToken export-stream consumer
# ---------------------------------------------------------------------------
def consume_net_token_export_stream(
    reader: BitReader,
    on_token: Callable[[NetToken, object], None],
    token_data_readers: Optional[Dict[int, Callable[[BitReader], object]]] = None,
) -> int:
    """Mirror UNetTokenDataStream::ReadData (NetTokenDataStream.cpp:207-217).

        while (Reader->ReadBool())
            Token   = NetTokenStore->ReadNetToken(Context)   # TypeId ON wire
            NetTokenStore->ReadTokenData(Context, Token, ...) # per-TypeId payload

    For each exported (Token, data) pair, calls on_token(token, data).
    Returns the number of tokens consumed. The caller owns storage/persistence.
    """
    readers = token_data_readers if token_data_readers is not None else DEFAULT_TOKEN_DATA_READERS
    count = 0
    while reader.read_bit():
        if reader.is_error():
            break
        token = read_net_token(reader, known_type_id=None)  # TypeId on wire
        reader_fn = readers.get(token.type_id, read_token_data_fstring)
        data = reader_fn(reader)
        on_token(token, data)
        count += 1
    return count
