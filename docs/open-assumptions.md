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
