# Phase 04 — Static Cross-Check of NetRefHandle Resolution & Protocol Descriptors

Per `00-overview-and-setup.md` Step 0.3 (revised): no live debugger is available,
so the "live-debugger diff" validation items for Phase 04 are replaced by a static
cross-check. This document records what was hand-traced against source and what was
asserted via redundant decode paths / cross-file consistency.

## Scope

Two distinct mechanisms (per `04-guid-cache-netfieldexport.md`):

- **A. `FNetRefHandle` → Object/Class resolution** — sub-steps 1 & 2 (DONE in prior
  commits; re-confirmed here).
- **B. Replication protocol / descriptor schema cache** — sub-step 4 (CORRECTED for
  Iris; no wire descriptor export). See the "CRITICAL CORRECTION" block in the phase
  doc.

## B. Source hand-trace (descriptor construction)

We read the engine source directly (no disassembly required — it is present in `/UE`):

1. **`FReplicationProtocolIdentifier` is a hash, not a schema.** —
   `ReplicationProtocolManager.cpp:170-184` `CalculateProtocolIdentifier` does:
   ```
   for each FReplicationFragmentInfo:
       IdBuffer.Add(Descriptor->DescriptorIdentifier.Value)
       IdBuffer.Add(Descriptor->DescriptorIdentifier.DefaultStateHash)
   ProtocolIdentifier = CityHash32(IdBuffer, sizeof(uint64)*IdBuffer.Num())
   ```
   So the 32-bit id on the wire (`ReplicationProtocol.h:13` `typedef uint32 ...`) is a
   CityHash32 over the per-descriptor `DescriptorIdentifier` `(Value, DefaultStateHash)`
   pairs. It cannot be inverted to a schema; it is a content fingerprint.

2. **On the wire only the hash travels.** — `NetObjectFactory.cpp:101-102`
   `WriteHeader`: `Writer->WriteBits(Header->GetNetFactoryId(), GetMaxBits());`
   then `Writer->WriteBits(Header->GetProtocolId(), 32);` then the factory-specific
   `SerializeHeader`. `ReadHeader` (`:134`) reads `Reader->ReadBits(32)` for the
   ProtocolId. **No descriptor bytes follow the 32-bit id.** The factory-specific
   header carries the class PATH (used to resolve the UClass), not the schema.

3. **Remote rebuilds the descriptor locally.** —
   `ObjectReplicationBridge.cpp:1681-1709` `RegisterRemoteInstance`:
   - receives `ReceivedProtocolId = Header->GetProtocolId()` (`:1582`)
   - resolves `UClass` from the creation-header class path (`:1687` `ClassName =
     InstancePtr->GetClass()->GetName()`)
   - builds `FReplicationFragments` for that class
   - calls `ReplicationProtocolManager->CreateReplicationProtocol(ReceivedProtocolId, …)`
     with `bValidateProtocolId = bValidateProtocol` (`:1707-1709`)
   - `CreateReplicationProtocol` (`ReplicationProtocolManager.cpp:254-274`) recomputes
     `CalculateProtocolIdentifier(Fragments)` and `ensure`s it equals the received id.
   The schema is a **deterministic function of the UClass reflection**, never transmitted.

4. **No descriptor export stream exists.** — `NetExports.cpp` tracks only
   `NetHandleExport` and `NetTokenExport` (per-packet export scopes). There is no
   `ProtocolExport` / descriptor export scope. This rules out the original sub-step 4
   assumption of a "streaming-pass descriptor export" analogous to the NetToken export
   stream.

### Consequence for our implementation

The "schema cache" is built **locally** by re-running the Iris descriptor-builder logic
(`ReplicationStateDescriptorBuilder` traversal: base states first, members in memory/
offset order within each class slice, concatenated base→derived) against the Dumper-7
SDK reflection for the resolved class, keyed by the 32-bit `ProtocolId`. There is no
descriptor wire export to consume. The Phase 05 creation-header walker feeds it via
`ProtocolDescriptorCache.observe_protocol(ProtocolId, class_path)`.

## A. Source hand-trace (handle resolution — re-confirmation)

- `FNetRefHandle` bit layout: `NetRefHandle.h:36-89` — 1 static bit + 53 serial bits +
  10 replication-system-id bits; Id = (Serial<<1)|Static. Static handles have ODD Id,
  dynamic EVEN Id. `operator<<` (`NetRefHandle.cpp:69`) writes 1 valid bit then
  `SerializeIntPacked64(Id)`; ReplicationSystemId is reconstructed from context, not read.
- `FNetToken` (`NetTokenStore.cpp:128`, `NetToken.h:97-107`): Index 20 bits, TypeId 3
  bits, authority 1 bit. Two-dimensional `(TypeId, Index) -> payload` resolution
  (`NetTokenStore.h:275` comment; `NetTokenStore.cpp:416` `ValidateAndStoreNetTokenData`).
- Dynamic spawn-info path (`ObjectReferenceCache.cpp:1524` `ReadFullReferenceInternal`):
  even-Id dynamic handle + inline path token (NO TypeId on wire inside a reference) +
  recursive outer chain — matches sub-step 2 decoder `read_net_object_reference`.

## Redundant / static validation actually run (no live debugging)

| Check | Method | Result |
|---|---|---|
| Descriptor rebuild determinism | `observe_protocol` re-called for same (id, class) must yield identical `canonical_key()` | PASS (8 real classes + 14k SDK self-test) |
| Cross-file consistency | same resolved class name rebuilds identically across all 10 files | PASS (0 inconsistent) |
| SDK class-match rate (real replay-resolved names) | token-store resolved paths → candidate SDK keys (convention-driven, SDK-hit required) | 8/8 = 100% |
| SDK class-match rate (full SDK self-test) | enumerate all 14,050 SDK types, rebuild each | 14,050/14,050 = 100% |
| No descriptor wire export | source read (NetObjectFactory + NetExports) | CONFIRMED |
| NetToken path stability | sub-step 3 already validated (token index consistent within file) | carried over |

## Items that remain OPEN (documented, not silently confirmed)

- **OA-04-1**: We cannot recompute the *exact* CityHash32 `ProtocolId` from the SDK
  alone, because `FReplicationStateDescriptor::DescriptorIdentifier` `(Value,
  DefaultStateHash)` constants live in the running binary (not the Dumper-7 dump). We
  therefore validate the rebuild's *determinism + cross-file stability + SDK class
  match*, and will confirm ProtocolId↔descriptor binding when Phase 05 recovers the real
  32-bit ids from creation headers. Tracked in `open-assumptions.md`.

This is the honest substitute for a live-debugger diff, per Step 0.3 (revised) items 1,
3, 4.
