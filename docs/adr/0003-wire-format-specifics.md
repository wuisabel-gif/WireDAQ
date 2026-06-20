# 3. Wire-format specifics: endianness, CRC, sizing, and version negotiation

- **Status:** Proposed
- **Date:** 2026-06-20
- **Deciders:** _(awaiting sign-off)_
- **Tags:** architecture, daq, wire-format, protocol, versioning
- **Supersedes / relates to:** deferred from [ADR 0001](0001-wire-ready-architecture.md)

## Summary

Pins the choices the codecs already implement — **little-endian**, **CRC-16/CCITT-FALSE**,
**256-byte** maximum packet — and records *why*, so they stop being defaults and become
commitments. The one genuinely open question, **version negotiation**, is decided: the
version byte signals breaking changes and receivers **fail closed** on versions they don't
implement; backward-compatible growth happens through new `msg_type` values, not version
bumps; and the first three header bytes are **frozen for all time** so any receiver can
always identify a frame's version before parsing it.

## Context

`protocol/packet_schema.yaml` already specifies a concrete format, and three codecs
implement it identically (`protocol/codec/`, `protocol/golden/reference_encoder.py`,
`firmware/codec/`), pinned by the golden vectors. What was missing is the *rationale* and
the *evolution policy* — without them, each choice is an accident waiting to be
relitigated, and there is no agreed rule for what happens when the format must change. ADR
0001 deferred exactly this and required it settled before Phase 3.

## Decision

### Endianness — little-endian

All multi-byte fields are little-endian. The target MCUs (ARM Cortex-M, RISC-V, AVR) and
the x86/ARM hosts running the ground station are all little-endian, so this is zero-cost
byte-copy on both ends. The reference encoder uses `struct` `<` packing and the firmware
codec stores bytes explicitly little-endian (so it is correct even on a big-endian target,
should one ever appear). **Locked: little-endian.**

### Integrity — CRC-16/CCITT-FALSE

Poly `0x1021`, init `0xFFFF`, no input/output reflection, xor-out `0x0000`; check value
`0x29B1` for ASCII `123456789`; covers **every byte before the CRC field, including the
magic**: `crc = crc16(frame[0:len-2])`.

- **16-bit is the right width** for frames capped at 256 bytes: enough Hamming distance to
  catch the bit-error and burst patterns a noisy serial/RF link produces, while costing
  only 2 bytes — material when the MTU is small. CRC-32 doubles the trailer for no useful
  gain at this size; CRC-8 / additive checksums are too weak.
- **The exact parameters are pinned, not just "CRC-16,"** because "CRC-16" names a dozen
  mutually incompatible variants. The check value `0x29B1` is the cross-language anchor —
  every codec asserts it on startup (Python and C both do), so a wrong implementation
  fails immediately rather than at first hardware contact.
- **Covering the magic** means a single bit flip in the sync word is caught as a CRC error
  rather than silently dropping a frame. The `StreamReceiver` relies on this when it
  resyncs a noisy byte stream.

**Locked: CRC-16/CCITT-FALSE, covering all bytes before the CRC.**

### Sizing — 256-byte maximum packet

- `max_packet_bytes = 256` is the smallest-common-denominator MTU across the serial/UDP
  links in scope and keeps receiver buffers small and **statically sized** (the firmware
  codec allocates `WD_MAX_SAMPLE_VALUES = (256 - 24 - 2)/2 = 115` int16 slots, no malloc).
- `channel_count` and `sample_count` are each `uint8`, so a block holds at most
  `channel_count * sample_count` values bounded by the 230-byte payload (≤ 115 int16).
- The 24-byte header and 2-byte CRC are fixed overhead; payload is therefore ≤ 230 bytes.

**Locked: 256-byte max packet; `uint8` counts; 24-byte header; 2-byte CRC trailer.**

### Version negotiation — fail closed, grow by msg_type, freeze the prefix

This is the open decision. Policy:

1. **The version byte means a breaking change** to header layout, framing, or CRC. The
   current format is **version 1**.
2. **Receivers MUST fail closed on unknown versions.** A frame whose version a receiver
   does not implement is rejected and counted, never best-effort parsed. Both codecs
   already do this (`FramingError` / `WD_ERR_FRAMING` on `version != 1`). Misparsing a
   future format is worse than dropping it.
3. **Backward-compatible growth does NOT bump the version.** New message kinds are added as
   new `msg_type` values on the **reserved control plane** (`HEARTBEAT`, `DEVICE_INFO`,
   `CONFIG_ACK`, …). Because every msg_type shares the 24-byte header, a receiver can
   frame, CRC-check, and route by `msg_type` *before* it knows the payload shape, and an
   **unknown `msg_type` is skipped and counted, not fatal**. This is the normal extension
   path; the version byte is the escape hatch of last resort.
4. **The header prefix is frozen for all time.** Bytes `[0,1] = magic`, byte `[2] =
   version` have **immutable position and meaning across every future version**. This is
   the one invariant the whole policy rests on: any receiver, of any version, can always
   read the magic and version byte to decide whether it can parse the rest — so a v1
   receiver cleanly rejects a v2 frame instead of choking on it.
5. **Negotiation procedure.** On link bring-up a node SHOULD emit `DEVICE_INFO` advertising
   its protocol version, channel map, and capabilities. The ground station records it and,
   on a version it cannot handle, logs and refuses that node — **no silent downgrade**.

**Locked: the policy above; header prefix `magic|magic|version` frozen across all
versions.**

## Consequences

**Positive**

- Every choice is now a documented commitment with a rationale and a check value, not a
  default someone might "improve" into an incompatibility.
- The format can grow safely: additive changes ride new `msg_type`s with zero version
  churn; the rare breaking change is unambiguous and fail-closed.
- The frozen prefix guarantees forward/backward identifiability — the property that makes
  mixed-version links safe.

**Costs**

- The golden vectors are **version-scoped**: a future v2 needs its own parallel vector set,
  and both codecs must carry both versions during any migration window.
- The frozen-prefix invariant constrains all future header designs (a constraint we accept
  deliberately).

**Commitments**

- Any change to endianness, CRC, sizing, or the header prefix requires a new ADR and a new
  protocol version — it cannot be a quiet schema edit.
- The schema's `crc.check` (`0x29B1`) and the magic/version offsets are normative and must
  never move.

## Follow-on

- Add a short version-policy note to `protocol/packet_schema.yaml` pointing here.
- Define the reserved control-plane payloads (`HEARTBEAT` / `DEVICE_INFO` / `CONFIG_ACK`)
  and add golden vectors for them, in a later ADR — they are the first exercise of the
  "grow by msg_type" path decided here.
