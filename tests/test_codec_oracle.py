"""
Independent-oracle property tests for the wire codec.

Why this exists (and why it isn't redundant with ``tests/test_golden_vectors.py``):

The golden vectors prove the production codec and ``protocol/golden/reference_encoder.py``
agree *with each other*. But both reach the bytes the same way — the same
``struct.pack("<2sBBHIQIBB")`` format string and the same bit-by-bit CRC loop. If that
shared mechanism misread the schema (wrong field width, wrong endianness, a CRC masking
bug), both implementations would be wrong *in lockstep* and the golden vectors would still
match. The vectors also only cover four hand-picked cases.

This file adds an oracle that is independent in *mechanism*, not just in source file:

  * bytes are laid out by hand with ``int.to_bytes`` / ``int.from_bytes`` — never ``struct``,
  * the CRC is computed by a 256-entry lookup table — never the production bitwise loop,
  * signed int16 samples are encoded via explicit two's-complement masking.

Then it checks, over a large generated input space, that the production codec and this
oracle produce identical frames and that the production codec round-trips. Two
independently-written implementations agreeing on thousands of random frames is real
evidence the codec matches the *spec*, not just itself.

Runnable two ways, like the golden-vector test:
    python3 tests/test_codec_oracle.py     # standalone deterministic fuzz, no deps
    pytest tests/test_codec_oracle.py      # adds Hypothesis property tests if installed
"""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wiredaq.protocol.codec import (  # noqa: E402
    CrcError,
    FramingError,
    decode,
    encode_sample_block,
)

# ---------------------------------------------------------------------------
# The independent oracle — deliberately a different mechanism from production.
# ---------------------------------------------------------------------------

# CRC-16/CCITT-FALSE as a lookup table (production uses a per-bit loop). Same
# polynomial 0x1021 — that's the spec — but a different code path, so a bug in the
# bitwise version would not be mirrored here.
_CRC_TABLE = []
for _byte in range(256):
    _c = _byte << 8
    for _ in range(8):
        _c = ((_c << 1) ^ 0x1021) if (_c & 0x8000) else (_c << 1)
        _c &= 0xFFFF
    _CRC_TABLE.append(_c)


def oracle_crc16(data: bytes) -> int:
    crc = 0xFFFF  # init, no reflection, xorout 0x0000
    for byte in data:
        crc = ((crc << 8) & 0xFFFF) ^ _CRC_TABLE[((crc >> 8) ^ byte) & 0xFF]
    return crc


def oracle_encode(node_id, seq, t_node_us, sample_rate_hz,
                  channel_count, samples) -> bytes:
    """Build a frame byte-by-byte, no struct. Mirrors packet_schema.yaml directly."""
    out = bytearray()
    out += b"WD"                              # magic 0x57 0x44
    out.append(1)                             # version
    out.append(1)                             # msg_type = SAMPLE_BLOCK
    out += int(node_id).to_bytes(2, "little")
    out += int(seq).to_bytes(4, "little")
    out += int(t_node_us).to_bytes(8, "little")
    out += int(sample_rate_hz).to_bytes(4, "little")
    out.append(channel_count)
    out.append(len(samples))
    for row in samples:
        for value in row:
            # two's-complement int16, computed explicitly rather than via "<h"
            out += (int(value) & 0xFFFF).to_bytes(2, "little")
    out += oracle_crc16(bytes(out)).to_bytes(2, "little")
    return bytes(out)


def oracle_decode(frame: bytes) -> dict:
    """Parse a frame by hand into the canonical ``input`` dict."""
    assert frame[0:2] == b"WD", "bad magic"
    assert frame[2] == 1, "bad version"
    assert frame[3] == 1, "bad msg_type"
    node_id = int.from_bytes(frame[4:6], "little")
    seq = int.from_bytes(frame[6:10], "little")
    t_node_us = int.from_bytes(frame[10:18], "little")
    sample_rate_hz = int.from_bytes(frame[18:22], "little")
    channel_count = frame[22]
    sample_count = frame[23]
    body = frame[24:-2]
    assert len(body) == sample_count * channel_count * 2, "length mismatch"
    assert oracle_crc16(frame[:-2]) == int.from_bytes(frame[-2:], "little"), "crc"
    samples = []
    pos = 0
    for _ in range(sample_count):
        row = []
        for _ in range(channel_count):
            row.append(int.from_bytes(body[pos:pos + 2], "little", signed=True))
            pos += 2
        samples.append(row)
    return {
        "node_id": node_id, "seq": seq, "t_node_us": t_node_us,
        "sample_rate_hz": sample_rate_hz, "channel_count": channel_count,
        "samples": samples,
    }


# ---------------------------------------------------------------------------
# Bounds and a generator for *valid* SAMPLE_BLOCK inputs.
# ---------------------------------------------------------------------------
MAX_PACKET_BYTES = 256
HEADER_AND_CRC = 24 + 2
U16, U32, U64, U8 = 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF, 0xFF
I16_MIN, I16_MAX = -32768, 32767


def _random_input(rng: random.Random) -> dict:
    channel_count = rng.randint(0, 8)
    if channel_count == 0:
        max_samples = 0  # a row would be empty; keep shapes well-defined
    else:
        room = (MAX_PACKET_BYTES - HEADER_AND_CRC) // (channel_count * 2)
        max_samples = min(U8, room)
    sample_count = rng.randint(0, max_samples) if max_samples > 0 else 0
    samples = [
        [rng.randint(I16_MIN, I16_MAX) for _ in range(channel_count)]
        for _ in range(sample_count)
    ]
    # Bias toward boundary values that catch width/sign bugs.
    pick = rng.choice
    return {
        "node_id": pick([0, 1, U16, rng.randint(0, U16)]),
        "seq": pick([0, 1, U32, rng.randint(0, U32)]),
        "t_node_us": pick([0, 1, U64, rng.randint(0, U64)]),
        "sample_rate_hz": pick([0, 1, U32, rng.randint(0, U32)]),
        "channel_count": channel_count,
        "samples": samples,
    }


def _check_one(inp: dict) -> None:
    """Production and oracle must agree on encode; production must round-trip."""
    prod_frame = encode_sample_block(**inp)
    oracle_frame = oracle_encode(**inp)
    assert prod_frame == oracle_frame, (
        f"encode disagreement\n  prod={prod_frame.hex()}\n  orac={oracle_frame.hex()}"
        f"\n  input={inp}"
    )
    # Production decode reproduces the input...
    assert decode(prod_frame).to_input() == inp
    # ...and the independent decoder agrees on the production frame.
    assert oracle_decode(prod_frame) == inp


# ---------------------------------------------------------------------------
# Deterministic stdlib fuzz — always runs, no third-party deps.
# ---------------------------------------------------------------------------
FUZZ_ITERS = 3000
FUZZ_SEED = 0x5744  # 'WD'; fixed so failures reproduce


def test_oracle_agrees_over_random_inputs():
    rng = random.Random(FUZZ_SEED)
    for _ in range(FUZZ_ITERS):
        _check_one(_random_input(rng))


def test_crc_rejects_single_bit_flips():
    """Every corrupted bit must surface as CrcError, never silently decode."""
    rng = random.Random(FUZZ_SEED + 1)
    for _ in range(300):
        frame = bytearray(encode_sample_block(**_random_input(rng)))
        i = rng.randrange(len(frame))
        bit = 1 << rng.randrange(8)
        frame[i] ^= bit
        try:
            decode(bytes(frame))
        except (CrcError, FramingError):
            pass  # length/CRC field flips may trip framing first — both are rejections
        else:
            raise AssertionError(f"bit flip at byte {i} went undetected: {frame.hex()}")


def test_truncation_is_rejected():
    rng = random.Random(FUZZ_SEED + 2)
    for _ in range(200):
        frame = encode_sample_block(**_random_input(rng))
        cut = rng.randrange(len(frame))  # drop at least one trailing byte
        try:
            decode(frame[:cut])
        except (FramingError, CrcError):
            pass
        else:
            raise AssertionError(f"truncation to {cut} bytes was accepted")


def test_bad_magic_is_rejected():
    frame = bytearray(encode_sample_block(node_id=1, seq=0, t_node_us=0,
                                          sample_rate_hz=1000, channel_count=1,
                                          samples=[[1000]]))
    frame[0] ^= 0xFF
    try:
        decode(bytes(frame))
    except FramingError:
        return
    raise AssertionError("frame with corrupted magic was accepted")


# ---------------------------------------------------------------------------
# Hypothesis property tests — only when the library is installed (see test extras).
# These explore the same invariants with shrinking, so a failure reports a minimal
# counterexample instead of a giant random frame.
# ---------------------------------------------------------------------------
try:
    from hypothesis import given, settings
    from hypothesis import strategies as st

    _HAVE_HYPOTHESIS = True
except ImportError:  # pragma: no cover - exercised only where hypothesis is absent
    _HAVE_HYPOTHESIS = False


if _HAVE_HYPOTHESIS:

    @st.composite
    def _sample_blocks(draw):
        channel_count = draw(st.integers(min_value=0, max_value=8))
        if channel_count == 0:
            sample_count = 0
        else:
            room = (MAX_PACKET_BYTES - HEADER_AND_CRC) // (channel_count * 2)
            sample_count = draw(st.integers(min_value=0, max_value=min(U8, room)))
        i16 = st.integers(min_value=I16_MIN, max_value=I16_MAX)
        samples = [[draw(i16) for _ in range(channel_count)]
                   for _ in range(sample_count)]
        return {
            "node_id": draw(st.integers(0, U16)),
            "seq": draw(st.integers(0, U32)),
            "t_node_us": draw(st.integers(0, U64)),
            "sample_rate_hz": draw(st.integers(0, U32)),
            "channel_count": channel_count,
            "samples": samples,
        }

    @settings(max_examples=400)
    @given(_sample_blocks())
    def test_property_oracle_agrees(inp):
        _check_one(inp)

    @settings(max_examples=200)
    @given(_sample_blocks())
    def test_property_round_trip(inp):
        assert decode(encode_sample_block(**inp)).to_input() == inp


# ---------------------------------------------------------------------------
def _run_standalone():
    tests = [
        test_oracle_agrees_over_random_inputs,
        test_crc_rejects_single_bit_flips,
        test_truncation_is_rejected,
        test_bad_magic_is_rejected,
    ]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    extra = "with Hypothesis" if _HAVE_HYPOTHESIS else "Hypothesis not installed — skipped"
    print(f"All {len(tests)} oracle checks passed "
          f"({FUZZ_ITERS} fuzz iterations; {extra}).")


if __name__ == "__main__":
    _run_standalone()
