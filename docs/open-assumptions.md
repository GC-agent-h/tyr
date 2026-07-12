# Open Assumptions Tracker

This file is the honest replacement for "confirmed via live debugger" on this
project. No live/debuggable game session is available (see A2), so every item
that would normally be settled by a live diff is recorded here with its
supporting (non-definitive) evidence and its current confidence.

Confidence scale: `CONFIRMED` (strong static evidence), `PROBABLE`
(supporting evidence, some uncertainty), `CANDIDATE` (plausible, limited
evidence), `UNKNOWN` (insufficient evidence — acceptable).

---

## A1 — Iris replication backend in use
- **Status:** CONFIRMED (static evidence)
- **Evidence:** `docs/iris-evidence.md` (E1 compiled-in IrisCore package;
  E2 Iris runtime objects in GObjects dump; E3 build version match).
- **Note:** Confirmed via file evidence, not a live debugger. Treated as
  settled per `README.md` / `00-overview-and-setup.md` Step 0.1.

## A2 — No live debugging session is available for this project
- **Status:** CONFIRMED (project constraint)
- **Evidence:** Stated by project owner; reflected throughout `README.md`
  and `00-overview-and-setup.md` Step 0.3 (revised). All phase validations
  substitute the static methodology (redundant decode paths, static
  disassembly, cross-file consistency, documented assumptions, statistical/
  round-trip checks).
- **Consequence:** Every phase's "live-debugger cross-check" item is replaced
  by a static cross-check; do not add live-debugger items back.

## A3 — No Oodle / zlib compression on replay data
- **Status:** CANDIDATE (owner statement, not yet empirically re-checked)
- **Evidence:** Per project owner statement (see `README.md`). Not yet
  confirmed from the actual file bytes.
- **To resolve:** Phase 01 must read and assert the `bCompressed` flag across
  all 10 sample files; if any file reports compressed, this assumption is
  falsified and decompression support must be built.

## OA-04-1 — Cannot recompute exact CityHash32 `FReplicationProtocolIdentifier` from SDK alone
- **Status:** CANDIDATE (source-confirmed mechanism; exact constants unavailable)
- **Evidence:** `ReplicationProtocolManager.cpp:170-184` — the 32-bit
  `FReplicationProtocolIdentifier` is `CityHash32` over the per-descriptor
  `FReplicationStateDescriptor::DescriptorIdentifier (Value, DefaultStateHash)` pairs.
  Those `DescriptorIdentifier` constants are compiled into the running binary and are
  NOT present in the Dumper-7 SDK dump, so we cannot reproduce the exact hash value from
  the SDK reflection we have.
- **Why this is fine for the parser:** Iris sends only the 32-bit hash on the wire and
  rebuilds the descriptor locally on the remote side (`ObjectReplicationBridge.cpp
  :1681-1709`), so the replay parser likewise rebuilds the descriptor from the resolved
  class via SDK reflection — it never needs to invert the hash. We validate the rebuild
  via determinism + cross-file consistency + 100% SDK class-match (see
  `docs/phase04-static-crosscheck.md`). The exact `ProtocolId↔descriptor` binding will
  be confirmed once Phase 05 recovers the real 32-bit ids from creation headers.
- **To resolve (later):** when Phase 05 decodes creation headers, assert the observed
  32-bit id is stable per class across files and matches the class the descriptor was
  rebuilt for. If needed, the binary's `DescriptorIdentifier` table can be recovered
  statically (Step 0.3 #2 disassembly) to recompute the exact hash as a redundant check.
