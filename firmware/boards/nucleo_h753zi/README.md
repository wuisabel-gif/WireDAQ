# NUCLEO-H753ZI H0–H2 bring-up

This is the first physical WireDAQ node image.

- H0: board boot, user LED, ST-LINK virtual COM port
- H1: one safe, polling-only ADC channel
- H2: encode ADC readings with the existing WireDAQ C codec and stream `SAMPLE_BLOCK` frames on USART3

Timer-triggered ADC, DMA, and Ethernet belong to later issues. This image does not invent a board-specific packet format.

## Toolchain

- Board: ST NUCLEO-H753ZI
- MCU: STM32H753ZI, Cortex-M7
- Toolchain: `arm-none-eabi-gcc` and binutils
- Vendor device definitions: pinned `cmsis_device_h7` and `CMSIS_5` submodules
- Host flashing/debugging: STM32CubeProgrammer, STM32CubeIDE, or OpenOCD

Initialize the CMSIS dependencies after a clean checkout:

```sh
git submodule update --init --recursive
```

Build the image:

```sh
cd firmware/boards/nucleo_h753zi
make
```

Host-native mapping/encode checks (no ARM toolchain required):

```sh
make test
```

The ELF, BIN, HEX, and map files are written to `build/`.

## Pin mapping

| Function | MCU pin | Board function |
|---|---|---|
| Heartbeat LED | `PB0` | `LD1` user LED |
| UART TX | `PD8` | `USART3_TX`, ST-LINK virtual COM |
| UART RX | not used | reserved for later configuration |
| ADC input | `PA3` | Arduino header `A0`, `ADC12_INP15` |
| System clock | internal HSI | reset-selected 64 MHz HSI |
| Sample pacing | SysTick 1 kHz | polling interval, not ADC triggering |

The UART is configured for **115200 8N1**. The ADC is configured as a
single-ended, 16-bit, software-triggered `ADC1` conversion on `ADC12_INP15`.
Frames are emitted at **10 Hz** (`sample_rate_hz=10`, `node_id=1`, 1 channel, 1 sample).

## Sample mapping

WireDAQ samples are signed `int16`. The H753 ADC result is unsigned 16-bit, so firmware stores:

```text
wire_sample = raw_adc - 32768
```

The host reconstructs the original count as `raw_adc = wire_sample + 32768`.

| ADC input | raw count | wire sample |
|---|---|---|
| 0 V | 0 | -32768 |
| ~1.65 V | 32768 | 0 |
| ~3.3 V | 65535 | 32767 |

The millivolt estimate still assumes a 3.300 V ADC reference/supply:

```text
voltage_mV = raw_count * 3300 / 65535
```

That estimate is an engineering approximation; measure the actual board supply
if voltage accuracy matters.

## ADC wiring and safety

Use a 10 kOhm potentiometer for the first test:

```text
potentiometer end 1  -> 3V3
potentiometer wiper  -> Arduino A0 / PA3
potentiometer end 2  -> GND
```

Before connecting any source, verify that its voltage stays between 0 V and the
board's ADC supply and that the source shares the board ground. Never connect an
unknown or higher-voltage signal directly to PA3.

## Flashing and capture

Connect the board's ST-LINK USB connector, then either:

- open `build/wiredaq_h753_bringup.elf` in STM32CubeProgrammer and click
  *Download*, or
- use STM32CubeIDE's Run/Debug action with the project ELF.

After reset, LD1 should toggle at about 5 Hz (once per emitted frame). A short
ASCII identity banner is sent once; after that the virtual COM port is a binary
WireDAQ stream. Do not use a line-oriented serial terminal to inspect samples.

On the host, with the existing StreamReceiver path:

```sh
pip install -e ".[hardware]"
wiredaq-hil --port /dev/ttyACM0 --packets 30 --csv out/h753.csv
```

macOS typically enumerates the ST-LINK VCP as `/dev/cu.usbmodem*` or
`/dev/tty.usbmodem*`. Windows uses `COMn`. The capture command prints reconstructed
`adc_raw` / `adc_mv` values; they should move as the potentiometer wiper moves.

Startup banner bytes are skipped as `resync_bytes`. CRC errors should stay at 0,
and `seq` should increase by 1 each frame.

## Acceptance checklist

- [x] `make` succeeds from a clean checkout with CMSIS submodules initialized.
- [x] Firmware links the existing `firmware/codec` implementation.
- [x] Host-native `make test` encodes/decodes SAMPLE_BLOCK frames with CRC.
- [x] Host StreamReceiver/Collector path decodes H753-shaped frames without a board-specific decoder.
- [ ] The ELF loads on a NUCLEO-H753ZI.
- [ ] LD1 heartbeat is visible after reset.
- [ ] Host decode of hardware-generated frames succeeds (`wiredaq-hil`).
- [ ] CRC validation passes on the real UART stream.
- [ ] Sequence numbers advance correctly.
- [ ] Decoded samples track the potentiometer (`adc_raw = sample + 32768`).
- [x] No DMA, timer-triggered ADC, or protocol-format changes are included.

Physical flashing and live decode still require verification on the actual
NUCLEO-H753ZI board.
