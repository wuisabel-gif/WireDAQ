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

## Why this matters for avionics

Avionics is a **distributed data-acquisition problem under hostile constraints**: several
sensor nodes feed a flight computer over noisy, bandwidth-limited links, which downlinks
telemetry to a ground station and logs to an onboard recorder you read back after the
flight. Three things make this harder than ordinary software, and the whole architecture is
a response to them:

- **You get one flight.** There is no pause button and no in-flight debugger; a wrong
  assumption surfaces during a window you don't control. Every code path that matters —
  packet loss, clock skew, framing, CRC rejection — has to be exercised *on the ground,
  before flight*, which is exactly what the honest-fake simulator does.
- **Flight hardware is late, scarce, and expensive.** Wire-ready lets the flight firmware
  and the ground software develop in parallel against one contract instead of blocking on
  boards and integrating in a big bang at the end.
- **The flight environment is hostile.** Vibration, EMI, and lossy links corrupt and drop
  data; distributed nodes run on independent clocks that drift. A simulator that never drops
  a packet gives false confidence about precisely the conditions flight guarantees.

How each piece maps onto a flight concern:

| Avionics concern | What WireDAQ does |
|---|---|
| The packet format is an **interface contract (ICD)** between the flight MCU (C) and the ground software (Python) | One schema, plus **golden vectors** that three codecs — including the **C firmware codec** — must reproduce byte-for-byte. Codec drift is caught by a test, not discovered in recovered flight data you can't parse. (Same idea as CCSDS / MAVLink conformance.) |
| Links **lose, reorder, and corrupt** data under vibration and EMI | `ImpairmentTransport` (loss/dup/reorder), `SerialTransport` line noise + sync-word framing, and a **CRC on every frame** so a single bit flip is rejected, never accepted as data. |
| Telemetry is lossy; the **onboard log is ground truth** | `RawFrameLogger` archives exact wire bytes; `ReplayNode` plays a recovered capture back through the *same* pipeline — post-flight analysis and regression from real data. |
| Flight events must be **time-correlated** across nodes whose clocks drift | [ADR 0002](docs/adr/0002-clock-domain.md): node-local time authoritative on the wire; the ground station reconstructs one timeline per node from a clock model. |
| Validate before flight with **hardware-in-the-loop** | A real sensor board replaces a `SyntheticNode` behind the same port — HIL is a drop-in, and the ground station you flew is the one you tested. |
| Runs on a **flight MCU** | 256-byte packet cap, fixed header, a C codec with **no dynamic allocation**, and **fail-closed** version handling ([ADR 0003](docs/adr/0003-wire-format-specifics.md)). |

**Scope, honestly:** WireDAQ embodies avionics-grade *architecture and verification
practice* (one enforced ICD, honest link modeling, time discipline, record/replay, HIL-ready
seams) and is a development / integration / teaching harness — the cheap place to get the
seams and the wire contract right before boards exist. It is **not** certified flight
software: no DO-178C/DO-254 claim, and the C codec would need the usual qualification and
target testing before it flies.

---

## Core idea

WireDAQ uses a **ports-and-adapters (hexagonal) architecture**. A small set of stable
ports — `SensorNode`, `Transport`, `Receiver`, `Sink` — each has interchangeable adapters
(a synthetic node and a real board are interchangeable behind `SensorNode`; an in-process
queue stands in for a real UDP or serial link behind `Transport`). The `Collector` depends
only on the ports, so it is written once and never rewritten.

Two things make it *wire-ready*:

- `src/wiredaq/protocol/packet_schema.yaml` is the **single source of truth** for the wire format.
- `src/wiredaq/protocol/golden/` holds **golden test vectors** — known samples paired with their exact
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

WireDAQ is a `pip`-installable Python package (`wiredaq`, src-layout) plus a C firmware
codec and supporting docs/tools.

```text
WireDAQ/
  pyproject.toml                        package metadata + console scripts [present]
  README.md                             this file
  conftest.py                           puts src/ on sys.path for tests    [present]
  src/wiredaq/                          the importable package
    protocol/                           the wire format
      packet_schema.yaml                the wire-format source of truth    [present]
      packets.md                        prose spec of the format           [planned]
      codec/wiredaq_codec.py            production encode/decode           [present]
      golden/
        vectors.json                    golden test vectors                [present]
        reference_encoder.py            test oracle / vector generator     [present]
        README.md                       how the vectors are used           [present]
    daq_sim/                            the simulator
      core/interfaces.py                the ports                          [present]
      transports/
        in_process.py                   loss-free in-process link          [present]
        impairment_transport.py         datagram "honest fake" decorator   [present]
        serial_transport.py             byte-stream link + line noise      [present]
        udp_transport.py                real loopback UDP sockets          [present]
      nodes/
        synthetic_node.py               synthetic accelerometer node       [present]
        replay_node.py                  replays a raw capture log          [present]
      collector/collector.py            the collector                      [present]
      sinks/{csv_logger,metrics}.py     CSV + throughput sinks             [present]
    ground_station/                     the (shared) ground-station tooling
      receiver/frame_receiver.py        datagram receiver                  [present]
      receiver/stream_receiver.py       serial sync-word framing receiver  [present]
      logger/raw_logger.py              archival raw-frame logger          [present]
      dashboard/console_dashboard.py    live terminal dashboard sink       [present]
    cli/{slice,serial}.py               wiredaq-slice / wiredaq-serial     [present]
  firmware/                             on-device C codec
    codec/wiredaq_codec.{h,c}           the C codec                        [present]
    test/test_golden_vectors.c          C-side golden-vector trip-wire     [present]
    test/gen_golden_header.py           vectors.json → C header bridge     [present]
    Makefile                            build + run the C conformance test
  CMakeLists.txt                        C/C++ library build + install      [present]
  include/wiredaq/wiredaq.hpp           idiomatic C++17 wrapper            [present]
  cpp/test/test_codec.cpp               C++ golden-vector trip-wire        [present]
  examples/encode_decode.cpp            minimal C++ usage example          [present]
  cmake/WireDAQConfig.cmake.in          find_package(WireDAQ) template     [present]
  tools/dashboard/index.html            capacity / what-if console (HTML)  [present]
  docs/
    adr/0001-wire-ready-architecture.md the architecture decision          [accepted]
    adr/0002-clock-domain.md            clock-domain decision              [proposed]
    adr/0003-wire-format-specifics.md   endianness/CRC/version policy      [proposed]
    diagrams/phase-pipeline.html        interactive 5-phase roadmap        [present]
  tests/                                pytest suite (18 checks)           [present]
```

## What's here now

- **`docs/adr/0001-wire-ready-architecture.md`** — the foundational decision: ports and
  adapters, schema as source of truth, golden vectors as required tests, plus the build
  order and the first vertical slice.
- **`src/wiredaq/protocol/packet_schema.yaml`** — the wire format: a packed 24-byte little-endian
  header (magic, version, msg type, node id, sequence, node-local timestamp, sample rate,
  channel/sample counts), `int16` samples, and a `CRC-16/CCITT-FALSE` trailer, capped at
  256 bytes. A reserved control-plane message family keeps configuration out of the
  high-rate sample stream.
- **`src/wiredaq/protocol/golden/`** — four golden vectors generated by the reference encoder,
  including two's-complement extremes and an empty block, each verified against the
  `0x29B1` CRC check value.
- **`src/wiredaq/protocol/codec/wiredaq_codec.py`** — the production codec (encode + validating
  decode) the simulator runs on. It reproduces every golden vector byte-for-byte;
  `tests/test_golden_vectors.py` is the trip-wire that fails if it ever drifts.
- **`firmware/codec/wiredaq_codec.{h,c}`** — the on-device **C codec**, the third
  implementation of the format. It reproduces the same golden vectors byte-for-byte
  (`cd firmware && make test`), which is the cross-language byte-compatibility proof the
  whole architecture rests on: Python and C agree because the same committed vectors gate
  both. Its golden header is generated from `vectors.json`, so nothing is hand-transcribed.
- **The runtime** — the ports (`src/wiredaq/daq_sim/core/interfaces.py`) and their adapters:
  `InProcessTransport` + the `ImpairmentTransport` honest fake and a real-socket
  `UdpTransport` (datagram), the `SerialTransport` byte-stream link with line noise; a
  `SyntheticNode` and a `ReplayNode`; the shared `FrameReceiver` and `StreamReceiver`; the
  `Collector`; and the sinks — `CsvLogger`, `MetricsSink`, the archival `RawFrameLogger`,
  and the live `ConsoleDashboardSink`. All standard library, no dependencies.
- **Record / replay** — `RawFrameLogger` archives the exact wire bytes of a session;
  `ReplayNode` plays a capture back through the same pipeline, so a recorded run reproduces
  bit-for-bit (a regression oracle, and a way to drive the tools from field data).
- **Two interactive tools** (see below).

## Install & run

Pure standard library — Python 3.10+, no runtime dependencies.

```bash
pip install wiredaq       # from PyPI (per tagged release)

pip install -e .          # from a checkout; editable, adds wiredaq-slice / wiredaq-serial
# (dev extras incl. pytest:  pip install -e ".[test]")
```

Releases are published to [PyPI](https://pypi.org/project/wiredaq/) automatically when a
GitHub Release is tagged (`.github/workflows/publish.yml`, via Trusted Publishing).

```bash
# the datagram slice: synthetic nodes → impairment transport → receiver
#   → collector → CSV log + metrics summary
wiredaq-slice --nodes 3 --packets 150 --loss 0.05 --reorder 0.03 --seed 7

# the serial byte-stream slice: same collector/sinks, but the link is a raw byte
#   stream with line noise; the StreamReceiver finds frames via the magic sync word
wiredaq-serial --nodes 2 --packets 200 --garbage 0.4 --corrupt 0.01 --seed 9

# over a real loopback UDP link, with the live dashboard and a raw capture for replay
wiredaq-slice --transport udp --raw-log out/capture.wdlog --dashboard

# (without installing, the same entry points run as modules:)
#   python -m wiredaq.cli.slice ... / python -m wiredaq.cli.serial ...
```

```bash
# the test suite (18 checks) — the golden-vector trip-wire + the end-to-end seam tests
pytest

# the C firmware codec, held to the same golden vectors (cross-language proof)
cd firmware && make test
```

The slice prints what the honest-fake link did (dropped / duplicated / reordered /
corrupted) next to what the receiver and collector independently observed — loss and
reordering detected purely from the per-node sequence field, corruption caught by the
CRC. Because the impairment RNG is seeded, every run is reproducible.

### C / C++ library (CMake)

The codec also ships as a `find_package`-able CMake library — the same C core as the
firmware, with an idiomatic C++17 wrapper (`<wiredaq/wiredaq.hpp>`). See
[`cpp/README.md`](cpp/README.md).

```bash
cmake -S . -B build && cmake --build build
ctest --test-dir build --output-on-failure   # C++ golden-vector conformance
cmake --install build --prefix /usr/local     # headers + lib + CMake package config
```

```cmake
# in a consuming project
find_package(WireDAQ CONFIG REQUIRED)
target_link_libraries(my_app PRIVATE wiredaq::codec)   # then #include <wiredaq/wiredaq.hpp>
```

## Interactive tools

Both are self-contained HTML — open them in any browser, no build step.

- **`docs/diagrams/phase-pipeline.html`** — the *why*: step through the five phases and
  watch real hardware grow inward from both ends while the wire contract holds still.
- **`tools/dashboard/index.html`** — the *how much*: a live console for capacity
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
  resyncs past garbage. Both satisfy one `Receiver` port (`wiredaq-serial` proves it).
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
