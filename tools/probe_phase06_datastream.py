"""
probe_phase06_datastream.py — Phase 06 sub-step 1 (commit #2) validation.

Runs the Iris data-stream decoder self-test: a synthetic Iris batch/object
stream is built from the SAME grammar the decoder models (sourced from
ReplicationReader.cpp / NetBitStreamUtil.cpp / NetObjectFactory.cpp), then
decoded and checked for:

  1. exact EOF consumption (bits consumed == bits encoded — no over/under-read),
  2. correct batch count + boundaries,
  3. correct initial/delta detection (bIsInitialState),
  4. correct observable 32-bit ProtocolId on the initial block.

This validates the DECODER LOGIC against the source-modeled wire grammar.
Real-replay cross-validation is pending the Phase-05 bunch-payload handoff
(Iris streams live inside reassembled bunches; frame_walk.py does not yet
emit payloads) and the bridge class-path source (absent from the /UE subset;
see OA-06-1). Until then, the decoder is gated to the root object per batch
(reads handle flag + ProtocolId, then seeks to the header-declared batch_end).

Exit code 0 = pass, 1 = fail.
"""

import sys

from iris_datastream import self_test


def main() -> int:
    try:
        ok = self_test()
    except AssertionError as e:
        print(f"FAIL: {e}")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {type(e).__name__}: {e}")
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
