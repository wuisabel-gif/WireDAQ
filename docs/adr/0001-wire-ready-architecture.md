# 1. Wire-ready architecture for WireDAQ

- **Status:** Accepted
- **Date:** 2026-06-19
- **Deciders:** _(fill in)_
- **Tags:** architecture, daq, simulation, hardware-in-the-loop

## Summary

WireDAQ adopts a **ports-and-adapters (hexagonal) architecture** so that a synthetic
node or a real board, an in-process queue or a real link, a stand-in receiver or the
real ground station can each be swapped without rewriting the collector. The wire
format defined in `protocol/packet_schema.yaml` is the single source of truth, and
`protocol/golden/` holds the test vectors that keep the simulator and firmware
byte-compatible.

## Context

WireDAQ is a pre-hardware DAQ architecture simulator and integration companion for the
target hardware and firmware. It must begin as pure software and progressively connect
to real hardware and firmware as they mature, across five phases:

1. **Pure simulator** — synthetic nodes → in-process transport → collector/dashboard.
2. **Protocol mirror** — the simulator emits the real planned packet format.
3. **Ground-station bridge** — simulated packets feed the real receiver/logger.
4. **Hardware-in-the-loop** — one simulated node becomes a real sensor board.
5. **Integration companion** — the simulator tests new DAQ layouts before firmware changes.

The design driver is **wire-ready, not firmware-first**: the value of the system is in
its *seams*. At every phase a different mix of components is simulated versus real:

- sensor data may come from a synthetic generator or a real sensor board;
- transport may be an in-process queue, a UDP socket, or a serial link;
- the receiver, collector, logger may all be sim stand-ins or the real ground-station tooling.

The collector and downstream sinks must not know or care which. If advancing a phase
requires editing the collector, the seam was in the wrong place.

If we do not constrain this now, three failure modes are likely:

- the two codec implementations (Python in the simulator, C in firmware) drift apart
  and silently stop being byte-compatible;
- a too-perfect simulator hides packet loss, jitter, clock skew, none of which appears
  until the first hardware integration;
- phase transitions become rewrites instead of re-wiring.

## Decision

WireDAQ uses a ports-and-adapters architecture. We define a small set of stable
**ports** (interfaces); each port has multiple interchangeable **adapters**. A "phase"
is a *composition of adapters chosen at wiring time*, not a change to the core pipeline.

### Ports

- **`SensorNode`** — produces timestamped samples.
  Adapters: `SyntheticNode`, `ReplayNode`, `HardwareNode` (serial/USB to a real board).
- **`Transport`** — moves opaque framed bytes from sender to receiver.
  Adapters: `InProcessTransport`, `UdpTransport`, `SerialTransport`, and
  `ImpairmentTransport` (a decorator that wraps any transport and injects loss,
  reordering, delay, duplication).
- **`Receiver`** — reads bytes off a transport, finds frame boundaries, validates them,
  then yields decoded packets. One implementation, shared with the real ground station.
- **`Sink`** — consumes decoded packets.
  Adapters: `CsvLogger`, `BinaryLogger`, `DashboardSink`, `MetricsSink`.

The **`Collector`** orchestrates: it pulls from a `Receiver` and fans out to one or more
`Sink`s, tracking each node's sequence numbers and watching for loss and jitter along the
way. It depends only on ports, never on a concrete adapter.

### Source of truth

`protocol/packet_schema.yaml` is the single source of truth for the wire format:
header layout and field types, endianness, the sequence and timestamp fields, the CRC, a
protocol **version byte**. Both the Python simulator codec and the C firmware codec are
built against it. No component hand-rolls a competing definition.

### Required tests

`protocol/golden/` holds **golden test vectors**: committed pairs of known samples →
known serialized bytes. Both codec implementations must reproduce them exactly. These
vectors are the enforcement mechanism — they are the reason two independently written
codecs in two languages stay wire-compatible. CI fails if either codec diverges from
the vectors.

### Honest fakes

Simulated adapters must impose the constraints real hardware will: a finite sample rate,
a capped packet size, realistic impairment. `ImpairmentTransport` exists so that the
collector's loss-and-jitter handling is exercised from Phase 1, not discovered at
Phase 4. A simulator that never drops a packet is a liability.

## Phase model

Each phase is a change in *which adapters are wired together*, plus configuration — not
a rewrite of the `Collector` or `Sink`s.

| Phase | Swapped to real | Stays simulated |
|---|---|---|
| 1 — Pure simulator | nothing | everything (in-process) |
| 2 — Protocol mirror | codec → `packet_schema.yaml` | nodes, transport, sinks |
| 3 — Ground-station bridge | transport (real link), receiver, collector, logger | nodes |
| 4 — Hardware-in-the-loop | one `SensorNode` → real board (serial) | remaining nodes |
| 5 — Integration companion | _(same topology)_ | candidate-layout nodes used as a design harness |

## Consequences

**Positive**

- Phase transitions are wiring/config changes; the `Collector` is written once.
- A real sensor board replaces a `SyntheticNode` behind the same port — HIL is a drop-in.
- The simulator exercises the real ground-station receiver and logger before any
  hardware exists.
- Byte compatibility between simulator and firmware is enforced by tests, not by
  discipline.

**Costs**

- Ports add a layer of indirection; a naive direct script would be shorter in Phase 1.
- Maintaining golden vectors and two codecs is ongoing work.
- The schema must be versioned and evolved carefully (hence the version byte).

**Commitments**

- The wire format is pinned early (endianness, CRC, header) and all changes go through
  the schema plus updated golden vectors.
- Clock domain and exact serialization details are deferred to follow-on ADRs but must
  be decided **before Phase 3**, when the real receiver enters the loop.

## Open decisions (follow-on ADRs)

- **ADR 0002 — Clock domain.** Node-local timestamp versus ground-station arrival time
  as authoritative; how skew is represented and corrected.
- **ADR 0003 — Wire format specifics.** Endianness, CRC algorithm, maximum packet size,
  and version negotiation.

Both should be accepted before Phase 3.

## Implementation order

1. `protocol/packet_schema.yaml` — define the header and one sample payload type.
2. `protocol/golden/` — first known sample → bytes vectors for that type.
3. `tools/daq_sim/core/interfaces.py` — the `SensorNode`, `Transport`, `Receiver`, `Sink` ports.
4. `tools/daq_sim/transports/impairment_transport.py` — the honest-fake decorator over an in-process transport.
5. `tools/daq_sim/nodes/synthetic_node.py` — a synthetic accelerometer node.
6. `ground_station/receiver/` — the shared receiver, validated against the golden vectors.

## First vertical slice (proof of seam)

The first runnable build is deliberately tiny:

```text
synthetic accel node
  → impairment transport
  → collector
  → CSV logger
  → metrics summary
```

It proves the pipeline end-to-end and exercises loss handling from day one. Because
every stage sits behind a port, a real sensor board can later replace the synthetic node
with no change to anything downstream of it — transport, collector, logger, metrics — which is the whole
point of the architecture.
