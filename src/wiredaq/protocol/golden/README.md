# Golden vectors

These are the **contract enforcement** for the WireDAQ wire format. Each vector is a known
input paired with its exact on-wire bytes. Every codec — the Python simulator codec in
`src/wiredaq/daq_sim` and the C firmware codec — must encode each input to exactly
`frame_hex` and decode `frame_hex` back to the input. CI fails if any codec diverges.

This is what keeps two independently written codecs, in two languages, byte-compatible.
See `docs/adr/0001-wire-ready-architecture.md`.

## Files

- `vectors.json` — the generated vectors (do not hand-edit).
- `reference_encoder.py` — the test oracle and generator. It is the canonical, simple
  implementation of `src/wiredaq/protocol/packet_schema.yaml`. It is **not** the production codec.

## Vector format

```json
{
  "name": "accel_xyz_block",
  "description": "...",
  "input": { "node_id": 7, "seq": 42, "t_node_us": 1234567890,
             "sample_rate_hz": 3200, "channel_count": 3,
             "samples": [[10, -20, 16384], ...] },
  "frame_len": 50,
  "crc16": "0x2723",
  "frame_hex": "5744010107002a00...2327"
}
```

`frame_hex` is the **complete** frame: magic + header + payload + trailing CRC.

## Using them in a test

Python:

```python
import json
from your_codec import encode_sample_block, decode_frame

for v in json.load(open("src/wiredaq/protocol/golden/vectors.json"))["vectors"]:
    expected = bytes.fromhex(v["frame_hex"])
    assert encode_sample_block(**v["input"]) == expected, v["name"]
    assert decode_frame(expected) == v["input"], v["name"]
```

C firmware: load each `frame_hex`, run your encoder over the decoded `input`, and
`memcmp` against the bytes. Same vectors, same bytes.

## The CRC contract

`CRC-16/CCITT-FALSE` — poly `0x1021`, init `0xFFFF`, no input/output reflection,
xor-out `0x0000`. It covers every byte **before** the CRC field, including the magic:
`crc = crc16(frame[0 : len-2])`. Any correct implementation gives `0x29B1` for the
ASCII string `123456789` — assert that first.

## Current vectors

| name | covers |
|---|---|
| `minimal_single_sample` | smallest valid block (1 channel, 1 sample) |
| `accel_xyz_block` | typical 3-axis block, 4 samples, negatives |
| `empty_sample_block` | zero samples — header-only payload |
| `int16_extremes` | two's-complement boundaries and max field values |

## Regenerating

Only after an intentional, ADR-backed change to `packet_schema.yaml`:

```bash
python3 src/wiredaq/protocol/golden/reference_encoder.py
```

A diff to `vectors.json` in review means the wire format changed — it should never move
by accident.
