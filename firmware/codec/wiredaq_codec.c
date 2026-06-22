/*
 * WireDAQ firmware codec — implementation. See wiredaq_codec.h.
 *
 * All multi-byte fields are written/read little-endian by hand so the codec is
 * endianness-independent. The frame is packed with no padding, exactly as the
 * Python codec and the golden vectors define it.
 */
#include "wiredaq_codec.h"

uint16_t wd_crc16_ccitt_false(const uint8_t *data, size_t len)
{
    uint16_t crc = 0xFFFFu;
    for (size_t i = 0; i < len; ++i) {
        crc ^= (uint16_t)((uint16_t)data[i] << 8);
        for (int b = 0; b < 8; ++b) {
            if (crc & 0x8000u) {
                crc = (uint16_t)((crc << 1) ^ 0x1021u);
            } else {
                crc = (uint16_t)(crc << 1);
            }
        }
    }
    return crc;
}

size_t wd_frame_length(uint8_t channel_count, uint8_t sample_count)
{
    return WD_HEADER_SIZE + (size_t)sample_count * channel_count * 2u + WD_CRC_SIZE;
}

/* --- little-endian byte stores -------------------------------------------- */
static void put_u8(uint8_t *p, uint8_t v)   { p[0] = v; }
static void put_u16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
static void put_u32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v;         p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}
static void put_u64(uint8_t *p, uint64_t v)
{
    for (int i = 0; i < 8; ++i) p[i] = (uint8_t)(v >> (8 * i));
}

/* --- little-endian byte loads --------------------------------------------- */
static uint16_t get_u16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static uint32_t get_u32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8)
         | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static uint64_t get_u64(const uint8_t *p)
{
    uint64_t v = 0;
    for (int i = 0; i < 8; ++i) v |= (uint64_t)p[i] << (8 * i);
    return v;
}

wd_status_t wd_encode_sample_block(const wd_packet_t *pkt,
                                   uint8_t *out, size_t out_cap, size_t *out_len)
{
    if (!pkt || !out || !out_len) return WD_ERR_ARG;

    size_t n_values = (size_t)pkt->sample_count * pkt->channel_count;
    if (n_values > WD_MAX_SAMPLE_VALUES) return WD_ERR_TOO_BIG;

    size_t total = wd_frame_length(pkt->channel_count, pkt->sample_count);
    if (total > WD_MAX_PACKET_BYTES) return WD_ERR_TOO_BIG;
    if (total > out_cap) return WD_ERR_TOO_BIG;

    uint8_t *p = out;
    put_u8(p + 0, WD_MAGIC0);
    put_u8(p + 1, WD_MAGIC1);
    put_u8(p + 2, WD_VERSION);
    put_u8(p + 3, WD_MSG_SAMPLE_BLOCK);
    put_u16(p + 4, pkt->node_id);
    put_u32(p + 6, pkt->seq);
    put_u64(p + 10, pkt->t_node_us);
    put_u32(p + 18, pkt->sample_rate_hz);
    put_u8(p + 22, pkt->channel_count);
    put_u8(p + 23, pkt->sample_count);

    uint8_t *payload = p + WD_HEADER_SIZE;
    for (size_t i = 0; i < n_values; ++i) {
        put_u16(payload + i * 2, (uint16_t)pkt->values[i]); /* int16 two's complement */
    }

    uint16_t crc = wd_crc16_ccitt_false(out, total - WD_CRC_SIZE);
    put_u16(out + total - WD_CRC_SIZE, crc);

    *out_len = total;
    return WD_OK;
}

wd_status_t wd_encode_heartbeat(uint16_t node_id, uint32_t seq, uint64_t t_node_us,
                                uint32_t sample_rate_hz,
                                uint8_t *out, size_t out_cap, size_t *out_len)
{
    if (!out || !out_len) return WD_ERR_ARG;

    size_t total = WD_HEADER_SIZE + WD_CRC_SIZE;  /* header-only payload */
    if (total > out_cap) return WD_ERR_TOO_BIG;

    uint8_t *p = out;
    put_u8(p + 0, WD_MAGIC0);
    put_u8(p + 1, WD_MAGIC1);
    put_u8(p + 2, WD_VERSION);
    put_u8(p + 3, WD_MSG_HEARTBEAT);
    put_u16(p + 4, node_id);
    put_u32(p + 6, seq);
    put_u64(p + 10, t_node_us);
    put_u32(p + 18, sample_rate_hz);
    put_u8(p + 22, 0);  /* channel_count */
    put_u8(p + 23, 0);  /* sample_count  */

    uint16_t crc = wd_crc16_ccitt_false(out, total - WD_CRC_SIZE);
    put_u16(out + total - WD_CRC_SIZE, crc);

    *out_len = total;
    return WD_OK;
}

wd_status_t wd_decode_frame(const uint8_t *frame, size_t len, wd_packet_t *pkt)
{
    if (!frame || !pkt) return WD_ERR_ARG;
    if (len < WD_HEADER_SIZE + WD_CRC_SIZE) return WD_ERR_FRAMING;
    if (len > WD_MAX_PACKET_BYTES) return WD_ERR_FRAMING;

    if (frame[0] != WD_MAGIC0 || frame[1] != WD_MAGIC1) return WD_ERR_FRAMING;
    if (frame[2] != WD_VERSION) return WD_ERR_FRAMING;
    if (frame[3] != WD_MSG_SAMPLE_BLOCK && frame[3] != WD_MSG_HEARTBEAT)
        return WD_ERR_FRAMING;

    uint8_t channel_count = frame[22];
    uint8_t sample_count  = frame[23];
    size_t expected = wd_frame_length(channel_count, sample_count);
    if (len != expected) return WD_ERR_FRAMING;

    uint16_t found = get_u16(frame + len - WD_CRC_SIZE);
    uint16_t computed = wd_crc16_ccitt_false(frame, len - WD_CRC_SIZE);
    if (found != computed) return WD_ERR_CRC;

    pkt->msg_type       = frame[3];
    pkt->node_id        = get_u16(frame + 4);
    pkt->seq            = get_u32(frame + 6);
    pkt->t_node_us      = get_u64(frame + 10);
    pkt->sample_rate_hz = get_u32(frame + 18);
    pkt->channel_count  = channel_count;
    pkt->sample_count   = sample_count;

    const uint8_t *payload = frame + WD_HEADER_SIZE;
    size_t n_values = (size_t)sample_count * channel_count;
    for (size_t i = 0; i < n_values; ++i) {
        pkt->values[i] = (int16_t)get_u16(payload + i * 2);
    }
    return WD_OK;
}
