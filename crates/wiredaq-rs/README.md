# wiredaq-rs

Experimental Rust backend for WireDAQ.

This crate mirrors the existing WireDAQ wire contract instead of defining a new
protocol. The first milestone is byte compatibility with the committed golden
vectors already used by the Python, C, and C++ codecs.

## Current scope

- Encode `SAMPLE_BLOCK` frames.
- Encode `HEARTBEAT` frames.
- Decode validated frames.
- Validate CRC-16/CCITT-FALSE.
- Load Lua scenario files through `mlua`.
- Run a first capacity-style simulation over those scenarios.

## Why it exists

The Python implementation is the friendly simulator and integration harness. The
Rust backend is for high-rate experiments where we want stronger type checking,
cheap concurrency later, and a clearer path to stress-testing MicroDAQ-style raw
streaming at 10 kHz and above.

Lua scenarios live at the repository root under `scenarios/`. They describe
nodes, rates, channels, and fault injection cases that a future Rust runner can
execute.

## Try it

```bash
cd crates/wiredaq-rs
cargo test
cargo run -p wiredaq-rs --bin wiredaq-sim -- scenarios/microdaq_10khz.lua
```
