# tools/ — TYR replay parser harness

## Language choice
Prototyping and validation harness are written in **Python 3.13** (already
available on this host). The hard part of this project is *structure
understanding* of a bit-packed, engine-version-specific format, not raw
throughput — Python lets us re-run byte-offset experiments fast. Once each
phase is validated, the finalized logic can be ported to a compiled target
(Rust/C++) if performance later demands it. This matches
`docs/00-overview-and-setup.md` Step 0.4.

## Reference resources (already present in repo, do not regenerate)
- `UE/` — UE 5.6 engine source excerpts (bit primitives, replay driver,
  Iris core, etc.). Source of truth cited per phase doc.
- `dumper-7/` — Dumper-7 SDK for the exact Tyr build.
  - `dumper-7/CppSDK/SDK/*.hpp` — full C++ class/struct/property SDK.
  - `dumper-7/Dumpspace/*.json` — normalized reflection data
    (ClassesInfo / StructsInfo / FunctionsInfo / EnumsInfo / OffsetsInfo).
  - `dumper-7/Mappings/*.usmap` — name→offset mapping for the build.
  - `dumper-7/GObjects-Dump*.txt` — runtime object dump (used for Iris
    evidence and class-name cross-reference).
- `sample/` — 10 `.replay` files from the same build/version, for
  differential and cross-file-consistency analysis.

## Tools
- `bitreader.py` — `BitReader` with absolute bit-position tracking and
  built-in trace logging (the bit-level trace helper, Phase 00 deliverable
  #3). Emulates UE5.6 `FBitReader` MSB-first bit consumption.
- `dump_sdk.py` — consolidates `dumper-7/Dumpspace/*.json` into a single
  queryable `out/sdk_index.json` (class/struct/enum/offset index) for fast
  SDK cross-referencing from Phase 04 onward (Phase 00 deliverable #4).
- `selftest_bitreader.py` — validation harness for `BitReader`.

## Conventions
- Tool/script outputs go to `out/` (gitignored; force-add specific resolved
  maps that must ship with a fresh clone).
- Prefer JSON over CSV for machine-readable artifacts.
- Every read from a replay buffer should be traceable (byte offset, bit
  offset, n bits, value) — use `BitReader`'s trace for debugging Phases 3–8.
