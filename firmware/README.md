# WireDAQ firmware codec (C)

The on-device implementation of the wire format — the third codec, alongside the Python
production codec (`src/wiredaq/protocol/codec/`) and the reference oracle (`src/wiredaq/protocol/golden/`). All
three are built against `src/wiredaq/protocol/packet_schema.yaml` and **must reproduce
`src/wiredaq/protocol/golden/vectors.json` byte-for-byte.** That shared constraint is what keeps two
independently written codecs, in two languages, wire-compatible — by test, not by
discipline. See `docs/adr/0001-wire-ready-architecture.md`.

## Files

- `codec/wiredaq_codec.h` / `.c` — the codec. No dynamic allocation; explicit
  little-endian byte packing (correct on any MCU, not just a little-endian host); decode
  validates magic, version, msg_type, length, and CRC before touching the payload, and
  reports CRC failures distinctly from framing failures.
- `test/test_golden_vectors.c` — the conformance test: encode each vector's fields and
  `memcmp` against the golden bytes, decode the golden bytes back and compare fields,
  and confirm a flipped payload bit is rejected as a CRC error.
- `test/gen_golden_header.py` — projects `vectors.json` into `golden_vectors.h` so the
  test is held to the exact same vectors as the Python side, with nothing hand-typed.
- `boards/nucleo_h753zi/` — the first physical-node H0 bring-up image for the
  STM32H753ZI. It is intentionally separate from the generic codec and does not yet
  acquire ADC samples or transmit WireDAQ frames.

## Build & test

```bash
cd firmware
make test     # regenerates the golden header, builds, runs the conformance test
make clean
```

Requires a C11 compiler (`cc`/`clang`/`gcc`) and `python3` for the header generator.
The build is host-native for testing; the codec itself is freestanding-friendly C
(only `<stdint.h>`/`<stddef.h>`/`<string.h>`) ready to cross-compile for a target MCU.

## STM32H753ZI H0 bring-up

Initialize the board's CMSIS dependencies and build the first hardware image:

```bash
git submodule update --init --recursive
cd firmware/boards/nucleo_h753zi
make
```

The board project documents the NUCLEO-H753ZI pin map, flashing procedure, LED
heartbeat, and ST-LINK virtual COM startup message in
[`boards/nucleo_h753zi/README.md`](boards/nucleo_h753zi/README.md).

This milestone deliberately does not change the WireDAQ protocol or add ADC,
DMA, timer-triggered sampling, or a host-side special case. Those will be
implemented as separate follow-on changes.

## What "in sync" means

`make test` regenerates `golden_vectors.h` from `vectors.json` every build, so the C
test always reflects the current vectors. If `vectors.json` changes (only ever via an
intentional, ADR-backed schema change) and the C codec wasn't updated to match, the test
fails — the same trip-wire as `tests/test_golden_vectors.py` on the Python side.
