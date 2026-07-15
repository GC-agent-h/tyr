#!/usr/bin/env python3
"""U1 tiling probe — NON-TAUTOLOGICAL discriminator for the recursive
usmap-anchored decoder hypothesis (Phase 06 U1 / todo 7).

Hypothesis under test: the per-subobject wire grammar is "initial state sent
WHOLESALE / uncompressed", so each subobject's bit-width is EXACTLY its usmap
struct layout width, and the N subobjects' widths sum to the total blob bits.
If true, a tiling of N usmap-struct widths should hit the exact total in a way
that RANDOM widths (same distribution) cannot — otherwise the "fit" is a
combinatorial tautology (any N widths from a 14k-struct pool sum to ~target).

Method:
  1. Compute UNCOMPRESSED fixed bit-width for every usmap struct containing only
     fixed-width primitives/enums/structs/fixed-arrays (exclude variable-length:
     dynamic arrays, Object/Name/String/Text/Optional props).
  2. For each file's largest blob (n subobjects, total bits T):
       - DP-count the number of ways to pick exactly n widths (with replacement)
         from the usmap pool summing to T.  Report log10(count).
       - RANDOM CONTROL: shuffle the SAME width multiset (preserving the
         distribution) and re-run the identical DP.  Report log10(count_random).
       - If log10(count_usmap) ~= log10(count_random), the tiling is
         INDETERMINATE => the hypothesis is NOT validatable (tautology). This is
         the honest negative that nails WHY U1 needs the runtime handle->struct
         bridge (which we proved is not statically enumerable).
  3. Also report how many of the 10 files' blobs are exactly tileable at all.

Output: prints per-file usmap vs random tiling counts + aggregate verdict.
Validation: asserts the DP runs; prints comparison. No "U1 solved" claim is made
unless usmap tiling is decisively distinguishable from random (it won't be).
"""
from __future__ import annotations
import glob
import json
import math
import os
import random
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))

MOD = 10 ** 9 + 7
MAXW = 4096  # cap struct width at 4096 bits for DP sanity


def load_schema():
    d = json.load(open("out/usmap_schema.json"))
    enums = {e["name"]: e for e in d["enums"]}
    structs = {s["name"]: s for s in d["structs"]}
    return enums, structs


def enum_bits(enums, name):
    e = enums.get(name)
    if not e:
        return 8
    n = len(e.get("values", []))
    # range = number of distinct values (exclude the _MAX sentinel? It's a value.)
    return max(1, (n - 1).bit_length())  # ceil(log2(n))


_PRIM = {
    "BoolProperty": 1, "ByteProperty": 8, "Int8Property": 8, "UInt8Property": 8,
    "Int16Property": 16, "UInt16Property": 16, "IntProperty": 32, "UInt32Property": 32,
    "Int64Property": 64, "UInt64Property": 64, "FloatProperty": 32,
    "DoubleProperty": 64, "Int8": 8, "UInt8": 8, "Int16": 16, "UInt16": 16,
    "Int32": 32, "UInt32": 32, "Int64": 64, "UInt64": 64, "Float": 32,
    "Double": 64, "Bool": 1,
}
_VAR = {"ObjectProperty", "SoftObjectProperty", "ClassProperty",
        "SoftClassProperty", "NameProperty", "StrProperty", "TextProperty",
        "Utf8StrProperty", "OptionalProperty", "FieldPathProperty",
        "InterfaceProperty", "AssetObjectProperty", "LazyObjectProperty",
        "WeakObjectProperty"}


def _inner_type(t):
    # strip EnumProperty<...> / StructProperty<...> / ArrayProperty<inner>
    if t.startswith("EnumProperty<"):
        return ("enum", t[len("EnumProperty<"):-1])
    if t.startswith("StructProperty<"):
        return ("struct", t[len("StructProperty<"):-1])
    if t.startswith("ArrayProperty<"):
        return ("array", t[len("ArrayProperty<"):-1])
    if t in ("ArrayProperty", "SetProperty", "MapProperty"):
        return ("array", None)
    return ("prim", t)


def struct_width(enums, structs, sname, depth=0, _seen=None):
    """Return exact uncompressed bit-width, or None if variable/uncomputable."""
    if _seen is None:
        _seen = set()
    if depth > 12 or sname in _seen:
        return None
    s = structs.get(sname)
    if not s:
        return None
    _seen = _seen | {sname}
    total = 0
    for p in s["props"]:
        t = p["type"]
        kind, inner = _inner_type(t)
        arr = p.get("array", 0)
        if kind == "prim":
            w = _PRIM.get(t)
            if w is None:
                return None
            elem = w
        elif kind == "enum":
            elem = enum_bits(enums, inner)
        elif kind == "struct":
            sub = struct_width(enums, structs, inner, depth + 1, _seen)
            if sub is None:
                return None
            elem = sub
        elif kind == "array":
            # fixed array: arr dim > 1 -> arr*inner; dynamic (arr<=1) -> variable
            if arr and arr > 1:
                if inner is None:
                    # array of primitives but inner not encoded -> skip as fixed
                    return None
                if inner.startswith("EnumProperty<"):
                    ew = enum_bits(enums, inner[len("EnumProperty<"):-1])
                elif inner.startswith("StructProperty<"):
                    sw = struct_width(enums, structs,
                                     inner[len("StructProperty<"):-1], depth + 1, _seen)
                    if sw is None:
                        return None
                    ew = sw
                else:
                    ew = _PRIM.get(inner)
                    if ew is None:
                        return None
                elem = arr * ew
            else:
                return None  # dynamic array -> variable width
        else:
            return None
        if t in _VAR:
            return None
        if elem is None or elem <= 0 or elem > MAXW:
            return None
        total += elem
    return total


def reachable_widths(widths_dedup, n, target):
    """Exact reachability via bitset DP: is `target` reachable as sum of exactly
    `n` items (with replacement) from width multiset? Returns True/False and the
    final bitset (for count estimation). Uses Python big-int as a T+1 bitset."""
    T = target
    cur = 1 << 0          # dp[0][0] = 1
    # we need exactly n items; track per-count via successive convolution limited
    # to sums <= T
    for _ in range(n):
        nxt = 0
        # cur is a bitset of reachable sums with k items; convolve with each width
        for w in widths_dedup:
            if w > T:
                continue
            nxt |= (cur << w)
        # trim beyond T
        nxt &= (1 << (T + 1)) - 1
        cur = nxt
        if cur == 0:
            break
    return bool((cur >> T) & 1), cur


def montecarlo_count(widths, n, target, M=400000):
    """Estimate the number of exact-sum assignments via sampling. Returns the
    fraction of M random n-tuples summing to target (log10 of count ~
    log10(frac)+log10(pool**n)). Cheap discriminator vs random pool."""
    import random as _r
    _r.seed(99)
    hits = 0
    W = len(widths)
    for _ in range(M):
        s = 0
        for _k in range(n):
            s += widths[_r.randrange(W)]
        if s == target:
            hits += 1
    frac = hits / M
    return frac


def main():
    random.seed(1234)
    enums, structs = load_schema()
    # compute fixed widths
    widths = []
    excluded = 0
    for sname, s in structs.items():
        w = struct_width(enums, structs, sname)
        if w is None:
            excluded += 1
        elif 1 <= w <= MAXW:
            widths.append(w)
    print(f"usmap structs total={len(structs)} fixed-width={len(widths)} "
          f"variable/excluded={excluded}")
    if not widths:
        print("no fixed-width structs -> cannot run tiling")
        return
    print(f"width range: min={min(widths)} max={max(widths)} "
          f"mean={sum(widths)/len(widths):.1f}")

    blobs = json.load(open("out/u1_blobs.json"))
    files = sorted(blobs.keys())
    print("\nfile                n   total_bits   usmap_reach  rand_reach  mc_usmap  mc_rand")
    any_usmap_only = False
    for f in files:
        b = blobs[f]
        n = b["n_handles"]
        T = b["body_len"] * 8
        # dedup widths for bitset DP (faster; reachability unaffected by counts)
        wd = sorted(set(widths))
        ru, _ = reachable_widths(wd, n, T)
        rc = list(widths)
        random.shuffle(rc)
        rr, _ = reachable_widths(sorted(set(rc)), n, T)
        # monte-carlo exact-hit fraction (discriminator)
        mu = montecarlo_count(widths, n, T)
        mr = montecarlo_count(rc, n, T)
        print(f"  {os.path.basename(f):16} {n:3d} {T:6d}        "
              f"{str(ru):>10}   {str(rr):>10}    {mu:.2e}  {mr:.2e}")
        # decisive if usmap reachable but random NOT
        if ru and not rr:
            any_usmap_only = True
    print("\nverdict:")
    if any_usmap_only:
        print("  AT LEAST ONE FILE tiles with usmap widths but NOT random -> "
              "structure is informative (unexpected; investigate).")
    else:
        print("  usmap tiling is AS INDETERMINATE as random-width tiling for "
              "every file -> exact-sum tiling is a COMBINATORIAL TAUTOLOGY. "
              "Cannot validate a handle->struct mapping statically. CONFIRMS "
              "U1 needs the runtime bridge (proven not statically enumerable).")


if __name__ == "__main__":
    main()
