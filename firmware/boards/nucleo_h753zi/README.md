# NUCLEO-H753ZI H0/H1 bring-up

This is the first physical WireDAQ node image. H0 proves board boot, the user
LED, and the ST-LINK virtual COM port. H1 adds one safe, polling-only ADC
channel. Timer triggering, DMA, packet transmission, and Ethernet belong to
later issues.

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

The ELF, BIN, HEX, and map files are written to `build/`.

## Pin mapping

| Function | MCU pin | Board function |
|---|---|---|
| Heartbeat LED | `PB0` | `LD1` user LED |
| Debug UART TX | `PD8` | `USART3_TX`, ST-LINK virtual COM |
| Debug UART RX | not used | reserved for later configuration |
| ADC input | `PA3` | Arduino header `A0`, `ADC12_INP15` |
| System clock | internal HSI | reset-selected 64 MHz HSI for H0/H1 |

The UART is configured for **115200 8N1**. The ADC is configured as a
single-ended, 16-bit, software-triggered `ADC1` conversion on `ADC12_INP15`.
The voltage estimate assumes a 3.300 V ADC reference/supply:

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

## Flashing and observation

Connect the board's ST-LINK USB connector, then either:

- open `build/wiredaq_h753_bringup.elf` in STM32CubeProgrammer and click
  *Download*, or
- use STM32CubeIDE's Run/Debug action with the project ELF.

After reset, LD1 should toggle approximately once per second. A serial
terminal attached to the ST-LINK virtual COM port at 115200 baud should show:

```text
WireDAQ NUCLEO-H753ZI bring-up
firmware=h1-adc-polling version=0.2.0
adc=ADC1_INP15 pin=PA3 resolution=16 reference_mv=3300
adc_raw=32768 adc_mv=1650
```

The raw count and millivolt estimate should move as the potentiometer wiper
moves. The current loop uses polling and intentionally does not use DMA or a
hardware timer.

## Acceptance checklist

- [x] `make` succeeds from a clean checkout with CMSIS submodules initialized.
- [ ] The ELF loads on a NUCLEO-H753ZI.
- [ ] LD1 heartbeat is visible after reset.
- [ ] Startup identity text is visible on the ST-LINK virtual COM port.
- [ ] PA3/ADC12_INP15 raw counts respond to a potentiometer.
- [ ] ADC resolution, reference assumption, and wiring are documented.
- [x] No DMA, timer-triggered sampling, transport, or protocol changes are included.

Physical flashing, UART output, and ADC response still require verification on
the actual NUCLEO-H753ZI board.
