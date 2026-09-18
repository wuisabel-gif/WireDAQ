# NUCLEO-H753ZI H0 bring-up

This is the first physical WireDAQ node image. It intentionally proves only
board boot, the user LED, and the ST-LINK virtual COM port. ADC, DMA, timers,
packet transmission, and Ethernet belong to later issues.

## Toolchain

- Board: ST NUCLEO-H753ZI
- MCU: STM32H753ZI, Cortex-M7
- Toolchain: `arm-none-eabi-gcc` and binutils
- Vendor device definitions: pinned `cmsis_device_h7` submodule
- Host flashing/debugging: STM32CubeProgrammer, STM32CubeIDE, or OpenOCD

Initialize the CMSIS dependency after a clean checkout:

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
| System clock | `PH0/PH1` internal | reset-selected HSI for H0 |

The UART is configured for **115200 8N1**. The binary image does not send
WireDAQ frames yet; its text startup/heartbeat stream is only a bring-up
interface.

## Flashing

Connect the board's ST-LINK USB connector, then either:

- open `build/wiredaq_h753_bringup.elf` in STM32CubeProgrammer and click
  *Download*, or
- use STM32CubeIDE's Run/Debug action with the project ELF.

After reset, LD1 should toggle approximately once per second. A serial
terminal attached to the ST-LINK virtual COM port at 115200 baud should show:

```text
WireDAQ NUCLEO-H753ZI bring-up
firmware=h0-board-bringup version=0.1.0
led=PB0 uart=USART3_TX/PD8 baud=115200
heartbeat
```

## Acceptance checklist

- [ ] `make` succeeds from a clean checkout with the CMSIS submodule initialized.
- [ ] The ELF loads on a NUCLEO-H753ZI.
- [ ] LD1 heartbeat is visible after reset.
- [ ] Startup identity text is visible on the ST-LINK virtual COM port.
- [ ] No ADC, DMA, transport, or protocol changes are required for this H0 image.

Physical flashing and UART output still require verification on the actual
NUCLEO-H753ZI board.
