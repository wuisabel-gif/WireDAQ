# WireDAQ

**A wire-ready data-acquisition (DAQ) architecture simulator — design the architecture before you wire the hardware.**

WireDAQ is a pre-hardware DAQ simulator and integration companion. It starts as pure
software and progressively connects to real hardware and firmware as they mature, so the
software architecture and the firmware co-develop against one shared contract instead of
colliding at bring-up.

---

## Motivation

Building a distributed DAQ system means firmware, the transport link, and the
ground-station software all have to agree on a wire format and integrate cleanly. The
usual order of events is firmware-first: the software can't really start until boards and
firmware exist, so integration becomes a big-bang event at the end — and that's exactly
when every wrong assumption surfaces at once.

WireDAQ inverts that. The guiding principle is **wire-ready, not firmware-first**: the
value of the system is in its *seams*, not its components. You build the integration
architecture and a faithful simulator first, in pure software, with interfaces that match
exactly where real hardware will eventually plug in. The same packet format, the same
receiver, the same logger run whether the bytes come from a synthetic node or a real
sensor board. When hardware arrives, it drops into a system that already works and is
already tested.

Concretely, this design defends against three failure modes that otherwise ambush DAQ
projects:

- **Codec drift.** Two implementations of the wire format — Python in the simulator, C in
  firmware — quietly stop producing identical bytes. WireDAQ pins the format in one schema
  and enforces byte-compatibility with committed golden vectors.
- **Dishonest simulation.** A simulator that never drops a packet hides the things real
  links do to data: dropped packets, jitter, clocks that slowly drift apart. None of that
  surfaces until first hardware contact. WireDAQ's *honest fakes* impose the same
  constraints real hardware will, from day one.
- **Rewrite-per-phase.** If moving closer to hardware means rewriting the collector, the
  seams were in the wrong place. Here, advancing a phase is a wiring change, not a rewrite.

---

## Core idea

WireDAQ uses a **ports-and-adapters (hexagonal) architecture**. A small set of stable
ports — `SensorNode`, `Transport`, `Receiver`, `Sink` — each has interchangeable adapters
(a synthetic node and a real board are interchangeable behind `SensorNode`; an in-process
queue stands in for a real UDP or serial link behind `Transport`). The `Collector` depends
only on the ports, so it is written once and never rewritten.

Two things make it *wire-ready*:

- `protocol/packet_schema.yaml` is the **single source of truth** for the wire format.
- `protocol/golden/` holds **golden test vectors** — known samples paired with their exact
  bytes — that every codec, in every language, must reproduce.

## The five phases

Each phase is a change in which adapters are wired together, not a rewrite:

| Phase | Becomes real | Stays simulated |
|---|---|---|
| 1 — Pure simulator | nothing | everything (in-process) |
| 2 — Protocol mirror | codec → `packet_schema.yaml` | nodes, transport, sinks |
| 3 — Ground-station bridge | real link, receiver, collector, logger | nodes |
| 4 — Hardware-in-the-loop | one node → real sensor board (serial) | remaining nodes |
| 5 — Integration companion | _(same topology)_ | candidate layouts, as a design harness |

---

## Impact

- **Parallel development.** Firmware and software teams work against one contract instead
  of blocking on each other.
- **The simulator is permanent infrastructure, not scaffolding.** The same tool serves as
  a regression oracle, an integration test harness, the hardware-in-the-loop rig, and a
  capacity-planning console — it stays in the tree for the life of the project.
- **Lower-risk, cheaper bring-up.** A real board drops into a system that already runs and
  is already tested, so the first hardware integration is a swap rather than a leap.
- **Design before commit.** New DAQ layouts can be validated in software before any
  firmware change, which is the cheapest possible place to find out a design won't fit a
  link budget or a buffer.
- **Compatibility by construction.** Cross-language byte-compatibility is guaranteed by
  tests rather than by discipline.

The approach is the deliberate intersection of three established ideas — a
sim-swappable ground station (as in OpenC3 COSMOS), a DAQ device abstraction (as in
openDAQ), and a schema-driven codec (as in Kaitai Struct) — combined into a single
software-first system with a progressive path to hardware.

---

## Repository layout

```text
WireDAQ/
  README.md                          this file
  run_slice.py                          datagram first vertical slice    [present]
  run_serial.py                         serial byte-stream slice         [present]
  conftest.py                           import anchor for tests          [present]
  docs/
    adr/
      0001-wire-ready-architecture.md   the architecture decision        [accepted]
      0002-clock-domain.md              clock-domain decision            [proposed]
      0003-wire-format-specifics.md     endianness/CRC/version policy    [proposed]
    diagrams/
      phase-pipeline.html               interactive 5-phase roadmap      [present]
  protocol/
    packet_schema.yaml                  the wire-format source of truth  [present]
    packets.md                          prose spec of the format         [planned]
    golden/
      vectors.json                      golden test vectors              [present]
      reference_encoder.py              test oracle / vector generator   [present]
      README.md                         how the vectors are used         [present]
    codec/
      wiredaq_codec.py                  production encode/decode          [present]
  tools/
    daq_sim/
      dashboard/
        index.html                      capacity / what-if console       [present]
        README.md                       maps the console to the model    [present]
      core/interfaces.py                the ports                        [present]
      transports/
        in_process.py                   loss-free in-process link        [present]
        impairment_transport.py         datagram "honest fake" decorator [present]
        serial_transport.py             byte-stream link + line noise    [present]
        udp_transport.py                real loopback UDP sockets        [present]
      nodes/
        synthetic_node.py               synthetic accelerometer node     [present]
        replay_node.py                  replays a raw capture log        [present]
      collector/collector.py            the collector                    [present]
      sinks/
        csv_logger.py                   CSV sample logger                [present]
        metrics.py                      throughput metrics sink          [present]
  ground_station/
    receiver/frame_receiver.py          datagram receiver                [present]
    receiver/stream_receiver.py         serial sync-word framing receiver[present]
    logger/raw_logger.py                archival raw-frame logger        [present]
    dashboard/console_dashboard.py      live terminal dashboard sink     [present]
  firmware/
    codec/wiredaq_codec.{h,c}           on-device C codec                [present]
    test/test_golden_vectors.c          C-side golden-vector trip-wire   [present]
    test/gen_golden_header.py           vectors.json → C header bridge   [present]
    Makefile                            build + run the C conformance test
  tests/
    test_golden_vectors.py              codec ↔ golden-vector trip-wire  [present]
    test_pipeline.py                    datagram end-to-end seam tests   [present]
    test_stream_receiver.py             serial framing / resync tests    [present]
    test_udp_transport.py               real-socket transport tests      [present]
    test_logger_replay.py               record/replay fidelity tests     [present]
```

## What's here now

- **`docs/adr/0001-wire-ready-architecture.md`** — the foundational decision: ports and
  adapters, schema as source of truth, golden vectors as required tests, plus the build
  order and the first vertical slice.
- **`protocol/packet_schema.yaml`** — the wire format: a packed 24-byte little-endian
  header (magic, version, msg type, node id, sequence, node-local timestamp, sample rate,
  channel/sample counts), `int16` samples, and a `CRC-16/CCITT-FALSE` trailer, capped at
  256 bytes. A reserved control-plane message family keeps configuration out of the
  high-rate sample stream.
- **`protocol/golden/`** — four golden vectors generated by the reference encoder,
  including two's-complement extremes and an empty block, each verified against the
  `0x29B1` CRC check value.
- **`protocol/codec/wiredaq_codec.py`** — the production codec (encode + validating
  decode) the simulator runs on. It reproduces every golden vector byte-for-byte;
  `tests/test_golden_vectors.py` is the trip-wire that fails if it ever drifts.
- **`firmware/codec/wiredaq_codec.{h,c}`** — the on-device **C codec**, the third
  implementation of the format. It reproduces the same golden vectors byte-for-byte
  (`cd firmware && make test`), which is the cross-language byte-compatibility proof the
  whole architecture rests on: Python and C agree because the same committed vectors gate
  both. Its golden header is generated from `vectors.json`, so nothing is hand-transcribed.
- **The runtime** — the ports (`tools/daq_sim/core/interfaces.py`) and their adapters:
  `InProcessTransport` + the `ImpairmentTransport` honest fake and a real-socket
  `UdpTransport` (datagram), the `SerialTransport` byte-stream link with line noise; a
  `SyntheticNode` and a `ReplayNode`; the shared `FrameReceiver` and `StreamReceiver`; the
  `Collector`; and the sinks — `CsvLogger`, `MetricsSink`, the archival `RawFrameLogger`,
  and the live `ConsoleDashboardSink`. All standard library, no dependencies.
- **Record / replay** — `RawFrameLogger` archives the exact wire bytes of a session;
  `ReplayNode` plays a capture back through the same pipeline, so a recorded run reproduces
  bit-for-bit (a regression oracle, and a way to drive the tools from field data).
- **Two interactive tools** (see below).

## Run it

No build step, no dependencies — Python 3.10+ standard library only.

```bash
# the datagram slice: synthetic nodes → impairment transport → receiver
#   → collector → CSV log + metrics summary
python3 run_slice.py --nodes 3 --packets 150 --loss 0.05 --reorder 0.03 --seed 7

# the serial byte-stream slice: same collector/sinks, but the link is a raw byte
#   stream with line noise; the StreamReceiver finds frames via the magic sync word
python3 run_serial.py --nodes 2 --packets 200 --garbage 0.4 --corrupt 0.01 --seed 9

# over a real loopback UDP link, with the live dashboard and a raw capture for replay
python3 run_slice.py --transport udp --raw-log out/capture.wdlog --dashboard

# the contract trip-wire and the end-to-end seam tests (18 checks)
python3 tests/test_golden_vectors.py
python3 tests/test_pipeline.py
# (or: pytest)

# the C firmware codec, held to the same golden vectors (cross-language proof)
cd firmware && make test
```

The slice prints what the honest-fake link did (dropped / duplicated / reordered /
corrupted) next to what the receiver and collector independently observed — loss and
reordering detected purely from the per-node sequence field, corruption caught by the
CRC. Because the impairment RNG is seeded, every run is reproducible.

## Interactive tools

Both are self-contained HTML — open them in any browser, no build step.

- **`docs/diagrams/phase-pipeline.html`** — the *why*: step through the five phases and
  watch real hardware grow inward from both ends while the wire contract holds still.
- **`tools/daq_sim/dashboard/index.html`** — the *how much*: a live console for capacity
  planning and what-if analysis, with finite buffers, modeled loss and jitter, independent
  per-node clocks, A/B comparison, and report export. Its packet-overhead math is wired to
  `packet_schema.yaml`, and it links back to the schema and vectors as the authority.

## Status & roadmap

The contract, the exploration tools, **and the full runtime now all exist**. The build
order from ADR 0001 is complete through the proof-of-seam and well past it: every port has
working adapters, the production codec is pinned to the golden vectors by a test, and the
pipeline runs end-to-end over three different links. This is **Phase 1–3** working in
software, with the Phase-4 pieces (serial framing, the C codec) already in place.

What exists across the hardware path, all in software, all behind the same ports:

- **Three transports.** The in-process queue + `ImpairmentTransport` honest fake, a real
  loopback **`UdpTransport`** (actual OS sockets), and a **`SerialTransport`** byte stream
  with chunked reads and line noise. The Collector is identical across all three.
- **Two receivers.** The datagram `FrameReceiver` and the `StreamReceiver`, which finds
  frame boundaries in a raw byte stream via the magic sync word, validates CRC, and
  resyncs past garbage. Both satisfy one `Receiver` port (`run_serial.py` proves it).
- **The C firmware codec** (`firmware/`), held to the same golden vectors as the Python
  codec — the cross-language byte-compatibility proof, before any board is built.
- **Record / replay.** `RawFrameLogger` + `ReplayNode` make any session reproducible.

Still ahead:

- **ADR 0002 — Clock domain** _(drafted, [proposed](docs/adr/0002-clock-domain.md),
  pending sign-off)_. Node-local time stays authoritative on the wire; a per-node clock
  model at the ground station reconstructs one global timeline. The `SyntheticNode`'s
  `drift_ppm` is the built-in test oracle for it.
- **ADR 0003 — Wire format specifics** _(drafted,
  [proposed](docs/adr/0003-wire-format-specifics.md), pending sign-off)_. Locks
  little-endian / CRC-16-CCITT-FALSE / 256-byte sizing (what the codecs already do) and
  decides version negotiation: fail closed on unknown versions, grow by `msg_type`, freeze
  the `magic|version` header prefix forever.
- **The control plane.** The reserved `HEARTBEAT` / `DEVICE_INFO` / `CONFIG_ACK` message
  types (the first exercise of ADR 0003's "grow by msg_type" path), the per-node
  `ClockModel` from ADR 0002, and `protocol/packets.md` as the prose companion to the
  schema.
