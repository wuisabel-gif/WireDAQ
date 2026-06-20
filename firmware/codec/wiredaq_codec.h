/*
 * WireDAQ firmware codec — the C implementation of the wire format.
 *
 * This is the on-device counterpart to the Python production codec
 * (protocol/codec/wiredaq_codec.py). Both are built against
 * protocol/packet_schema.yaml and MUST reproduce protocol/golden/vectors.json
 * byte-for-byte. That equivalence is the whole point: two independently written
 * codecs, in two languages, stay wire-compatible because the same committed
 * vectors gate both. See docs/adr/0001-wire-ready-architecture.md.
 *
 * Design notes for firmware:
 *   - Endianness is handled explicitly (manual little-endian byte stores), so the
 *     code is correct on a big-endian or odd-alignment MCU, not just on an x86 host.
 *   - No dynamic allocation. The caller supplies the output buffer; samples live in
 *     a fixed-size array sized to the schema's 256-byte packet cap.
 *   - Decode validates magic, version, msg_type, length, and CRC before touching
 *     the payload, and reports the failure reason so a receiver can count
 *     corruption (CRC) separately from garbage (framing).
 */
#ifndef WIREDAQ_CODEC_H
#define WIREDAQ_CODEC_H

#include <stddef.h>
#include <stdint.h>

/* Constants mirrored from protocol/packet_schema.yaml. */
#define WD_MAGIC0 0x57u           /* 'W' */
#define WD_MAGIC1 0x44u           /* 'D' */
#define WD_VERSION 1u
#define WD_MSG_SAMPLE_BLOCK 1u
#define WD_HEADER_SIZE 24u
#define WD_CRC_SIZE 2u
#define WD_MAX_PACKET_BYTES 256u

/* Max int16 sample values that fit under the 256-byte packet cap:
 * (256 - 24 header - 2 crc) / 2 = 115. */
#define WD_MAX_SAMPLE_VALUES \
    ((WD_MAX_PACKET_BYTES - WD_HEADER_SIZE - WD_CRC_SIZE) / 2u)

/* Return / error codes. Negative = failure. */
typedef enum {
    WD_OK = 0,
    WD_ERR_FRAMING = -1,   /* bad magic / version / msg_type / length / shape   */
    WD_ERR_CRC = -2,       /* CRC mismatch: the bytes were corrupted            */
    WD_ERR_TOO_BIG = -3,   /* would exceed WD_MAX_PACKET_BYTES / buffer too small */
    WD_ERR_ARG = -4        /* NULL pointer or impossible field value            */
} wd_status_t;

/* A decoded SAMPLE_BLOCK, with samples stored flat in row-major order:
 * values[s * channel_count + c]. */
typedef struct {
    uint16_t node_id;
    uint32_t seq;
    uint64_t t_node_us;
    uint32_t sample_rate_hz;
    uint8_t  channel_count;
    uint8_t  sample_count;
    int16_t  values[WD_MAX_SAMPLE_VALUES];
} wd_packet_t;

/* CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, no reflection, xorout 0x0000.
 * crc16(b"123456789") == 0x29B1. */
uint16_t wd_crc16_ccitt_false(const uint8_t *data, size_t len);

/* Total on-wire length for a block of the given shape. */
size_t wd_frame_length(uint8_t channel_count, uint8_t sample_count);

/* Encode `pkt` into `out` (capacity `out_cap`). On success writes the full frame
 * (magic + header + payload + CRC) and sets *out_len. */
wd_status_t wd_encode_sample_block(const wd_packet_t *pkt,
                                   uint8_t *out, size_t out_cap, size_t *out_len);

/* Decode and fully validate `frame` (`len` bytes) into `pkt`. */
wd_status_t wd_decode_frame(const uint8_t *frame, size_t len, wd_packet_t *pkt);

#endif /* WIREDAQ_CODEC_H */
