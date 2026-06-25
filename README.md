# WireDAQ

[![PyPI version](https://img.shields.io/pypi/v/wiredaq.svg)](https://pypi.org/project/wiredaq/)
[![Python versions](https://img.shields.io/pypi/pyversions/wiredaq.svg)](https://pypi.org/project/wiredaq/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**A wire-ready data-acquisition (DAQ) architecture simulator — design the architecture before you wire the hardware.**

WireDAQ is a pre-hardware DAQ simulator and integration companion. It starts as pure
software and progressively connects to real hardware and firmware as they mature, so the
software architecture and the firmware co-develop against one shared contract instead of
colliding at bring-up. The core package is Python, the firmware-facing codec is C/C++,
and the experimental high-rate backend is Rust with Lua scenario files. Its companion
diagnostic tool, [WireDAQ Health](https://github.com/wuisabel-gif/Wiredaq-health), is a
small Nim CLI for checking captured or live WireDAQ telemetry streams.

---

## Quickstart — three ways to use it

**1. Just look (no install).** Open the **[live demo](https://wuisabel-gif.github.io/WireDAQ/)**
and click the two interactive tools — a capacity console and a phase roadmap. Nothing to install.

**2. Run the simulator (one command).** It simulates sensors sending data over a lossy link
and shows you what survives:

```bash
pip install wiredaq     # from PyPI (or: pip install -e . from a checkout)
wiredaq-slice --nodes 2 --packets 80 --loss 0.05
```

You'll see how many packets the link dropped/corrupted, how many the receiver recovered, and
the loss the collector detected **purely from the packet counter** — then it writes every
sample to `out/slice_samples.csv` (open it in Excel/pandas). Variants:
`wiredaq-serial` (noisy serial link), add `--dashboard` for a live view, `--help` for all options.

**3. Use the codec in your own code (the library).** Turn sensor readings into wire bytes and
back — identical bytes in Python, C, and C++:

```python
from wiredaq.protocol.codec import encode_sample_block, decode

frame = encode_sample_block(node_id=7, seq=42, t_node_us=1_000_000, sample_rate_hz=3200,
                            channel_count=3, samples=[[10, -20, 16384], [12, -18, 16380]])
pkt = decode(frame)          # -> a Packet; pkt.samples == the original readings
```

New here? Start with #1 or #2. The rest of this README is the *why* and the architecture.

**4. Try the Rust/Lua experimental backend.** The Rust crate mirrors the same packet
contract, checks itself against committed golden frames, and can run Lua-defined DAQ
scenarios such as a MicroDAQ 10 kHz raw stream:

```bash
cargo test -p wiredaq-rs
cargo run -p wiredaq-rs --bin wiredaq-sim -- scenarios/microdaq_10khz.lua
```

**5. Check a captured stream with WireDAQ Health.** The companion
[WireDAQ Health](https://github.com/wuisabel-gif/Wiredaq-health) repo provides a Nim CLI
that validates frames, CRCs, sequence gaps, reordering, timestamps, and per-node stream
health:

```bash
wiredaq_health --raw-log out/capture.wdlog
```

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

Three things make it *wire-ready*:

- `src/wiredaq/protocol/packet_schema.yaml` is the **single source of truth** for the wire format.
- `src/wiredaq/protocol/golden/` holds **golden test vectors** — known samples paired with their exact
  bytes — that every codec, in every language, must reproduce.
- `scenarios/*.lua` describes high-rate DAQ experiments that the Rust backend can run without
  changing the packet contract.

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
- **Independent diagnostics.** The companion
  [WireDAQ Health](https://github.com/wuisabel-gif/Wiredaq-health) CLI can inspect raw
  captures or streams without running the full simulator, which makes quick telemetry
  triage easier during bring-up.

The approach is the deliberate intersection of three established ideas — a
sim-swappable ground station (as in OpenC3 COSMOS), a DAQ device abstraction (as in
openDAQ), and a schema-driven codec (as in Kaitai Struct) — combined into a single
software-first system with a progressive path to hardware.

---

## Repository layout

WireDAQ is a `pip`-installable Python package (`wiredaq`, src-layout) plus a C firmware
codec, C++ wrapper, Rust/Lua experimental backend, and supporting docs/tools.

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
  crates/
    wiredaq-rs/                         Rust/Lua experimental backend      [present]
      src/bin/wiredaq-sim.rs            Lua scenario runner                [present]
  scenarios/
    microdaq_10khz.lua                  Lua scenario for raw MicroDAQ      [present]
    static_fire_faults.lua              Lua fault-injection scenario       [present]
  CMakeLists.txt                        C/C++ library build + install      [present]
  Cargo.toml                            Rust workspace                     [present]
  include/wiredaq/wiredaq.hpp           idiomatic C++17 wrapper            [present]
  cpp/test/test_codec.cpp               C++ golden-vector trip-wire        [present]
  examples/encode_decode.cpp            minimal C++ usage example          [present]
  cmake/WireDAQConfig.cmake.in          find_package(WireDAQ) template     [present]
  tools/dashboard/index.html            capacity / what-if console (HTML)  [present]
  docs/
    adr/0001-wire-ready-architecture.md the architecture decision          [accepted]
    adr/0002-clock-domain.md            clock-domain decision              [proposed]
    adr/0003-wire-format-specifics.md   endianness/CRC/version policy      [proposed]
    adr/0004-rust-lua-backend.md        Rust/Lua backend decision          [proposed]
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
- **`src/wiredaq/protocol/golden/`** — golden vectors generated by the reference encoder,
  covering both message types (SAMPLE_BLOCK and HEARTBEAT), two's-complement extremes,
  and an empty block, each verified against the `0x29B1` CRC check value.
- **`src/wiredaq/protocol/codec/wiredaq_codec.py`** — the production codec (encode + validating
  decode) the simulator runs on. It reproduces every golden vector byte-for-byte;
  `tests/test_golden_vectors.py` is the trip-wire that fails if it ever drifts.
- **`firmware/codec/wiredaq_codec.{h,c}`** — the on-device **C codec**, the third
  implementation of the format. It reproduces the same golden vectors byte-for-byte
  (`cd firmware && make test`), which is the cross-language byte-compatibility proof the
  whole architecture rests on: Python and C agree because the same committed vectors gate
  both. Its golden header is generated from `vectors.json`, so nothing is hand-transcribed.
- **`crates/wiredaq-rs/`** — the Rust experimental backend. It mirrors the same frame
  format, validates CRC behavior, reproduces representative golden frames, and includes
  `wiredaq-sim`, a small runner that loads Lua scenario files and reports packet count,
  sample count, encoded bytes, frame size, and expected loss.
- **`scenarios/*.lua`** — editable high-rate DAQ scenarios. The first two model a MicroDAQ
  10 kHz raw stream and a static-fire fault-injection case, giving the Rust backend a
  concrete way to test packet sizing and receiver-side raw streaming assumptions.
- **[WireDAQ Health](https://github.com/wuisabel-gif/Wiredaq-health)** — a separate Nim
  companion repo for stream diagnostics. It consumes this repo's wire format and reports
  CRC failures, framing errors, dropped/reordered packets, timestamp issues, packet size,
  and per-node sample counts.
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

---

## Compatibility

**Speaks the wire contract in three languages.** The format is the interop surface, and
three codecs reproduce it byte-for-byte — pinned by the golden vectors, so a fourth-language
codec only has to pass the same `vectors.json`:

| | Standard | Notes |
|---|---|---|
| Python | 3.10+ | the `wiredaq` package; **zero runtime dependencies** (standard library only) |
| C | C11 | firmware codec — no dynamic allocation, explicit little-endian |
| C++ | C++17 | `wiredaq::codec` wrapper over the C core |

**Installs / builds with the usual ecosystems.**

- **pip / PyPI** — `pip install wiredaq` (per release), or `pip install -e .` from a checkout.
- **CMake** — `find_package(WireDAQ)` → `wiredaq::codec`, or `FetchContent` / `add_subdirectory`.
- **Make** — the firmware codec builds with a plain `Makefile`.

**Runs on host and target.** macOS / Linux / Windows for the Python and C/C++ parts
(standard library + BSD sockets). The C codec is freestanding-friendly and built to
cross-compile for **ARM Cortex-M, RISC-V, AVR** (static buffers, endianness handled in
code, so it's correct even on a big-endian target).

**Link-agnostic.** The 256-byte cap fits small serial / UDP / RF MTUs. Working transports:
in-process, **real UDP sockets** (any IP network), and a **serial byte-stream** model. New
links (CAN, real UART, RF) drop in behind the `Transport` / `ByteStreamTransport` ports.

**Standard data formats.** CSV sample logs (spreadsheet / pandas / MATLAB), a length-prefixed
**raw binary capture** that replays bit-for-bit, a YAML schema, and JSON golden vectors.

**Aligned with — but not wire-compatible with — existing systems.** The design borrows
*ideas* from CCSDS space packets, MAVLink (conformance vectors), Kaitai Struct
(schema-driven codecs), OpenC3 COSMOS (sim-swappable ground station), and openDAQ (device
abstraction). It defines its **own** wire format (magic `WD`, CRC-16/CCITT-FALSE) and is
**not** a drop-in for, nor on-the-wire compatible with, MAVLink / CCSDS / LoRaWAN / MQTT.

**Out of scope / not compatible.** Not certified flight software (no DO-178C/DO-254); the
C++ library is a separate CMake package (not in the Python wheel); the demo HTML tools are
static front-ends (not wired to the live simulator); Python ≤ 3.9 is unsupported.

---

## License

[MIT](LICENSE) © 2026 Isabel Wu. SPDX-License-Identifier: `MIT`.
