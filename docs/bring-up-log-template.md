# WireDAQ hardware bring-up log — TEMPLATE

Fill this in the day a real board is first attached. Its whole value is the last section:
**what the software-first simulator predicted vs. what the real hardware did.** That
comparison is the payoff of the wire-ready bet — if the numbers line up, the seams were in
the right place; if they don't, this log is where the surprise gets recorded and understood.

> Status: **template / not yet run** — no board has been attached. Everything below is the
> procedure and the predictions; the "observed" columns are blank until bring-up.

---

## 1. Hardware under test

| Item | Choice | Notes |
|---|---|---|
| MCU | _e.g. Raspberry Pi Pico (RP2040, Cortex-M0+)_ | The C codec (`firmware/codec/`) is freestanding — no malloc, endianness in code — and targets ARM Cortex-M / RISC-V / AVR. A Pico (~$4, native USB CDC) is the cheapest complete loop; an Arduino Uno/Nano (AVR) or STM32 works too. |
| Link | _USB CDC serial @ 115200 8N1_ | Pico/Arduino expose USB-serial directly; a bare chip needs a USB-UART adapter (CP2102/FTDI). |
| Sensor | _none (synthetic samples) → later an ADXL345 / MPU-6050_ | **Not required for first bring-up.** The board can emit synthetic samples through the real C codec over the real link, which already exercises the wire path, on-target codec, and real timing. Add a real accelerometer once the loop is proven. |
| Host | _macOS/Linux, `pip install "wiredaq[hardware]"`_ | pyserial is the only extra; the core package stays standard-library-only. |

**Minimum to close the loop:** one MCU + one USB cable + ~30 lines of firmware calling
`wd_encode_sample_block` and writing each frame to USB serial. ≈ $4.

## 2. Firmware

- [ ] Cross-compile `firmware/codec/wiredaq_codec.c` for the target.
- [ ] Run the on-target golden-vector test (or capture frames and diff against
      `src/wiredaq/protocol/golden/vectors.json`) — **the codec must reproduce the golden
      frames byte-for-byte on the real MCU**, not just on the host.
- [ ] Loop: read sensor (or synthesize) → `wd_encode_sample_block(...)` → write frame to UART.

## 3. Host wiring (the drop-in)

The real board replaces the simulated serial link behind the `ByteStreamTransport` port;
nothing downstream changes.

```python
from wiredaq.daq_sim.transports.serial_port import SerialPortTransport, open_serial_port
from wiredaq.ground_station.receiver import StreamReceiver
from wiredaq.daq_sim.collector.collector import Collector
from wiredaq.daq_sim.core.clock import WallClock
from wiredaq.daq_sim.sinks.metrics import MetricsSink

port = open_serial_port("/dev/tty.usbmodemXXXX", baudrate=115200)
collector = Collector(StreamReceiver(SerialPortTransport(port)), [MetricsSink()], clock=WallClock())
while True:
    collector.run()   # same StreamReceiver + Collector the sim was built and tested on
```

## 4. Procedure

1. [ ] Power the board; confirm the OS enumerates the serial device.
2. [ ] Run the host snippet; confirm packets are accepted (non-zero `collector.stats`).
3. [ ] Let it run long enough for the per-node `ClockModel` to converge (ADR 0002).
4. [ ] Capture a raw log (`RawFrameLogger`) for offline replay and regression.

## 5. Predicted vs. observed  ← the point of this log

| Question | Simulator predicted | Hardware observed | Match? |
|---|---|---|---|
| On-target C codec reproduces golden frames byte-for-byte | yes (host C/C++/Rust all do) | _____ | _____ |
| Recovered `drift_ppm` (ClockModel) vs. the MCU oscillator spec | crystal spec ± tolerance | _____ ppm | _____ |
| Frame loss under the real link | ~0 on a clean USB link | _____ % | _____ |
| Inter-frame jitter vs. the honest-fake model | modeled ± jitter_us | _____ µs | _____ |
| Resync-past-noise behaves as tested | yes (StreamReceiver) | _____ | _____ |
| Buffer sizing holds at the real sample rate | fits 256-byte cap | _____ | _____ |

## 6. Findings / surprises

_What the sim got right, what it got wrong, and what the model should change. This is the
most valuable paragraph in the repo — write it honestly._
