# WireDAQ simulator dashboard

`index.html` is the interactive front-end of the WireDAQ simulator: a self-contained,
design-time **capacity-planning and what-if tool**. Open it in any browser — no build,
no server. It models the full pipeline (nodes → transport → collector → sinks) with
finite buffers, modeled loss and jitter, and independent per-node clocks, and lets you
A/B compare two configurations and export a report.

It is a *design* tool, not the live ground-station dashboard. The eventual real-time
dashboard lives under `ground_station/`.

## How the model maps to the architecture

Every control in the panel corresponds to a concept defined elsewhere in the repo, so
the simulator and the real system describe the same thing:

| Panel concept | Architecture concept (see ADR 0001) |
|---|---|
| Sensor nodes (rate, channels, packet, drift) | `SensorNode` adapters |
| Transport: Local / UART / RS-485 / UDP | `Transport` adapters: `InProcessTransport` / `SerialTransport` / `UdpTransport` |
| Loss / jitter sliders, fault injection | `ImpairmentTransport` (the "honest fake") |
| Central collector (buffer, processing rate) | `Collector` |
| Collector RX + LOG, dashboard | `ground_station` receiver + logger + dashboard (the `Sink`s) |
| Clock drift → "sync error" | node-local `t_node_us` clock domain (ADR 0002) |

The transport choices also line up with the phase model: **Local** ≈ Phase 1
(in-process), **UDP / UART / RS-485** ≈ Phase 3+ (real link). The five-phase roadmap
itself is the companion diagram at `docs/diagrams/phase-pipeline.html`.

## Authoritative vs illustrative

The physics in this tool is a useful approximation for sizing and intuition. It is
**not** the contract. The authoritative wire definition is:

- `protocol/packet_schema.yaml` — the wire format (24-byte header, sequencing, timestamps, CRC).
- `protocol/golden/` — the golden vectors every codec must reproduce.

The simulator's packet-overhead math is wired to that schema: a 24-byte header plus a
2-byte CRC trailer, with `int16` samples. If the schema's header size changes, update
the `HEADER` / `CRC` constants near the top of the script so the bandwidth and
samples-per-packet figures stay honest.

## Companion tools

- `docs/diagrams/phase-pipeline.html` — the **why / roadmap**: the five integration phases.
- `tools/daq_sim/dashboard/index.html` — the **how much / what-if**: this quantitative explorer.

Together they tell one story; keep their stage vocabulary aligned
(nodes → codec → transport → ground-station core → sinks) when either changes.
