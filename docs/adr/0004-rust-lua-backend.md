# ADR 0004: Rust/Lua experimental backend

Status: Proposed

## Context

WireDAQ already has the important integration contract: one packet schema, golden
vectors, Python simulator tooling, and C/C++ firmware-facing codecs. The MicroDAQ
DMA work adds a new pressure: evaluate high-rate raw streaming, receiver-side
processing, and buffering behavior before firmware and hardware are ready.

Python remains the easiest place to explain and extend the architecture. Rust is
a good fit for a second backend because it can exercise the same wire format with
strong types and predictable performance. Lua is useful as the scenario layer:
sensor layouts, rates, fault injection, and static-fire profiles should be
editable without recompiling the backend.

## Decision

Add a Rust crate under `crates/wiredaq-rs` and Lua scenario files under
`scenarios/`.

The Rust crate must not define a new protocol. It mirrors the existing WireDAQ
wire format and must reproduce the same golden frames as the Python, C, and C++
codecs.

The Lua files are scenario definitions, not a second packet schema. The Rust
runner loads them through `mlua`, generates synthetic sample blocks using the
existing WireDAQ packet contract, and reports packet count, sample count, frame
size, encoded bytes, and expected loss.

## Consequences

- WireDAQ keeps one identity and one protocol.
- Rust can become the high-rate benchmark and async networking backend later.
- Lua gives the project editable DAQ scenarios without hardcoding experiments.
- Golden-vector compatibility remains the guardrail for cross-language drift.
- The first Rust runner has one runtime dependency, `mlua`, so scenario loading
  exercises real Lua rather than a custom parser.

## Follow-up work

- Extend the Rust runner from capacity reports to real UDP/serial transport tests.
- Add a Rust golden-vector test that reads `src/wiredaq/protocol/golden/vectors.json`
  once JSON support is introduced.
- Add MicroDAQ-specific capacity reports for packet size, sample rate, and drop
  detection.
- Compare Python simulator output and Rust simulator output for the same scenario.
