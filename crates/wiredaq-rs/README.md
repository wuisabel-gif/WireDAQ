# wiredaq-rs

Experimental Rust backend for WireDAQ.

This crate mirrors the existing WireDAQ wire contract instead of defining a new
protocol. It is held to the same committed golden vectors as the Python, C, and
C++ codecs: its test reads `src/wiredaq/protocol/golden/vectors.json` directly
(the single source of truth) and decodes + re-encodes every vector byte-for-byte,
so cross-language drift fails the Rust build too — no frames are transcribed.

## Current scope

- Encode `SAMPLE_BLOCK` frames.
- Encode `HEARTBEAT` frames.
- Decode validated frames.
- Validate CRC-16/CCITT-FALSE.
- Load Lua scenario files through `mlua`.
- Run a **seeded link simulation** over those scenarios: per-packet loss,
  duplication, jitter, and reorder are applied with a hand-rolled deterministic
  PRNG (no `rand` dependency), each delivered frame is decoded and CRC-checked by
  a receiver pass, and loss is re-derived from the sequence counter alone. The
  `faults` table (`packet_loss_burst`, `sensor_stuck`) and the `assertions` table
  are executed and checked, not ignored; unknown fault kinds are rejected.

## Why it exists

The Python implementation is the friendly simulator and integration harness. The
Rust backend is for high-rate experiments where we want stronger type checking,
cheap concurrency later, and a clearer path to stress-testing MicroDAQ-style raw
streaming at 10 kHz and above.

Lua scenarios live at the repository root under `scenarios/`. They describe
nodes, rates, channels, and fault-injection cases that the runner executes.

## Try it

```bash
cd crates/wiredaq-rs
cargo test
cargo run -p wiredaq-rs --bin wiredaq-sim -- scenarios/microdaq_10khz.lua
```
