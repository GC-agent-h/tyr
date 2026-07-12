# Phase 3 — Bit-Level Primitives

## Goal

Implement a bit-exact reimplementation of `FBitReader` and the core serialization primitives (`SerializeBits`, `SerializeInt`, `SerializeIntPacked`, `FString`/`FName` serialization, GUID serialization) that everything from Phase 4 onward depends on. Every property, handle, and index in the replay stream flows through these primitives — get this wrong and every later phase produces subtly corrupted data that can still *look* plausible, which makes bugs here especially dangerous.

## Source of truth

- `Engine/Source/Runtime/Core/Public/Serialization/BitReader.h` and `BitWriter.h`
- `Engine/Source/Runtime/Core/Private/Serialization/BitArchive.cpp`
- `Engine/Source/Runtime/Core/Public/Serialization/Archive.h` — look for `FArchive::SerializeIntPacked`
- `Engine/Source/Runtime/CoreUObject/Public/UObject/NameTypes.h` — `FName` serialization
- `Engine/Source/Runtime/Core/Public/Containers/UnrealString.h` — `FString` serialization (`operator<<` for `FArchive`)
- `Engine/Source/Runtime/CoreUObject/Public/UObject/CoreNetTypes.h` or similar — `FNetworkGUID` serialization

## Primitives to implement

### 1. Bit ordering and buffering

UE's bit archives read/write bits packed into bytes. Confirm precisely (do not assume from other engines/formats you've worked with) whether bits are consumed **LSB-first or MSB-first** within each byte by reading `FBitReader::SerializeBits` directly — it's a tight loop, read it character by character rather than skimming, since off-by-one bit ordering bugs are invisible until you try to decode a multi-bit integer and get consistently wrong-but-plausible values.

Implement:
```
class BitReader:
    read_bit() -> bool
    read_bits(count: int) -> raw bit sequence (not yet interpreted as int)
```
Keep a running "absolute bit position" counter from the start of the archive — you will use this constantly for debugging (see the bit-trace helper from Phase 0).

### 2. Fixed-width integer serialization

`SerializeInt` in UE is more subtle than "read N bits as an integer" in some cases (it supports non-power-of-two ranges for compact serialization of bounded values, e.g., serializing a value known to be in `[0, MaxValue)` using only `ceil(log2(MaxValue))` bits). Confirm whether this range-compacted form is used anywhere relevant to your replicated properties (it's commonly used for things like enum serialization or bounded indices) — check `RepLayout.cpp`'s handling of enums and small-range integers specifically, since this is where it matters most for Phase 6.

### 3. Packed integer (VLQ) — `SerializeIntPacked`

This is used pervasively for counts, indices, and sizes throughout the format (array counts, NetGUID values, export counts, etc.), so getting it exactly right is high-leverage. The scheme is a 7-bit-payload + 1-bit-continuation variable-length encoding. Read the actual implementation in `Archive.h`/`Archive.cpp` line by line — do not assume it matches a "standard" VLQ/LEB128 scheme from another domain, since UE's bit ordering and continuation-bit placement (whether the continuation bit is the high or low bit of each chunk, and whether chunks are 7 or 8 bits) has specific engine conventions that must match exactly.

**Implementation approach**: write it as a small, isolated, heavily-commented function with a unit test harness (see Validation below) before touching anything else, since this single function is reused in nearly every subsequent phase.

### 4. `FString` serialization

Confirm the exact scheme from `UnrealString.h`'s archive operator: typically a length-prefixed string where:
- A signed length is serialized (via `SerializeIntPacked` or a fixed int, confirm which).
- A **positive** length indicates ANSI/UTF-8-ish single-byte characters; a **negative** length (with absolute value used as character count) indicates UTF-16 (`TCHAR`-wide) characters — this sign-based encoding switch is a classic UE convention, confirm it's still exactly this in your 5.6 source rather than assuming.
- Zero-length / null string handling (an empty string vs. no string at all may be encoded differently — check for a special zero-length short-circuit in the source).

### 5. `FName` serialization

Names in UE are typically **not** serialized as raw strings in network contexts — they usually go through a name-table export mechanism (an index into a table of previously-exported name strings, established once and referenced by index thereafter), similar in spirit to the NetFieldExportGroup mechanism you'll build in Phase 4. Check `NameTypes.h`'s archive operator and, importantly, check whether the *replay-specific* serialization path for names differs from the general `FArchive` path (network archives often have a specialized name-serialization path distinct from disk serialization — check `PackageMapClient.cpp` and `DataBunch`-related code for a network-specific `FName` export/import function, since this is what actually applies to replay data rather than the generic archive operator).

### 6. `FNetworkGUID` serialization

Typically a packed integer (via `SerializeIntPacked`) representing a unique ID, with high bits or a flag distinguishing "static" (stably-named, e.g. level-placed actors) vs. "dynamic" (spawned at runtime) GUIDs — check `PackageMapClient.cpp`/`GuidReferences`-related code for the exact bit convention, since this distinction matters in Phase 4 for correctly resolving GUIDs to their referenced objects.

## Validation

1. **Unit tests against known constructed inputs**: for `SerializeIntPacked` specifically, hand-construct a few byte sequences by working backwards from the source algorithm (encode a few chosen integers like 0, 1, 127, 128, 16384 by hand using the algorithm as written) and confirm your decoder recovers exactly those integers. Do this before touching any real replay file — it isolates bugs to this function alone.
2. **Round-trip test**: implement both the reader and a matching writer for each primitive, and confirm `decode(encode(x)) == x` for a wide range of values, including edge cases (0, negative numbers if signed, max representable values, empty strings).
3. **Static comparison (no live debugging available)**: per Step 0.3 (revised) in `00-overview-and-setup.md`, there's no running session to breakpoint or step through. Substitute: statically disassemble the compiled `SerializeIntPacked`/`FBitReader::SerializeBits` and trace the instruction-level logic by hand against a few chosen input byte sequences, confirming bit-for-bit against your prototype's behavior on the same inputs. This is weaker than a live trace (no register/memory ground truth), so also lean extra hard on item 1's hand-constructed vectors and item 5's statistical check below, since together they're your best substitute.
4. **Cross-check via Phase 1/2 re-validation**: once these primitives are implemented, go back and re-decode the Phase 1/2 structures (which likely use some of these primitives, e.g., `FString` for level names) using your new primitive implementations instead of any shortcuts you took earlier, and confirm you get identical results. This catches primitive bugs that happened to not manifest in your earlier ad hoc string-reading code.
5. **Statistical sanity check on real files**: run your `SerializeIntPacked` decoder across large stretches of real replay data chunks (even before you know what the values *mean*) and check that the distribution of decoded values looks sane for a VLQ scheme (mostly small numbers, since VLQ schemes exist specifically because most real-world values are small) rather than looking like noise (mostly huge/negative/nonsensical numbers), which would indicate a decoding bug even before semantic interpretation is possible.

## Deliverables checklist

- [ ] `BitReader` with absolute bit-position tracking implemented and unit tested.
- [ ] `SerializeIntPacked` implemented, unit tested against hand-constructed values, and validated via static disassembly reading (no live debugging available — see Step 0.3 revised).
- [ ] `FString` serialization implemented, handling both narrow/wide sign convention.
- [ ] `FName` network-specific serialization identified and implemented (export-table based, not raw string, if that's what the source shows).
- [ ] `FNetworkGUID` serialization implemented, including static/dynamic distinction.
- [ ] Round-trip tests passing for all primitives.
- [ ] Phase 1/2 structures re-validated using these primitives with identical results to earlier ad hoc parsing.

## Suggested commit breakdown

This phase has the most independently-testable sub-units of any phase so far — commit each primitive separately, each with its own unit tests in the same commit (don't defer tests to a later commit for this phase; the whole point of these primitives is that they're cheap to verify in isolation, so do it immediately):

1. `feat(phase03): implement BitReader core with bit-position tracking` — include the absolute bit-position counter from the start.
2. `feat(phase03): implement SerializeIntPacked with hand-constructed unit tests` — the highest-leverage single commit in this phase; include the hand-constructed test vectors (0, 1, 127, 128, 16384, etc.) directly in this commit.
3. `docs(phase03): static disassembly validation of SerializeIntPacked` — no live debugging is available on this project; separate commit for the static disassembly cross-check specifically (per Step 0.3 revised), since this function is high-leverage and deserves its own audit trail entry even without a live diff.
4. `feat(phase03): implement FString serialization` — narrow/wide sign-convention handling.
5. `feat(phase03): implement FName network-specific serialization` — including whatever export-table mechanism you find applies to the network path specifically (distinct from the generic archive path).
6. `feat(phase03): implement FNetworkGUID serialization` — static/dynamic bit convention.
7. `test(phase03): round-trip tests for all primitives` — a consolidated round-trip test suite covering all of the above (can also be folded incrementally into each primitive's own commit if you prefer; either is fine, just be consistent — if you fold tests into each primitive's commit, skip this standalone commit).
8. `refactor(phase03): re-validate phase01/02 parsing using new primitives` — go back and swap any ad hoc Phase 1/2 string/int reading for calls into these new, tested primitives; this commit's "test" is that Phase 1/2's existing validation checks still pass identically afterward.

Proceed to `04-guid-cache-netfieldexport.md`.
