/*
 * Host-native checks for the H753 sample mapping and C-codec encode path.
 * Cross-compilation of the board image is a separate Makefile target.
 */
#include "h753_protocol.h"

#include <stdio.h>
#include <stdlib.h>

static void expect(int cond, const char *msg)
{
    if (!cond) {
        fprintf(stderr, "FAIL: %s\n", msg);
        exit(1);
    }
}

int main(void)
{
    expect(h753_adc_to_sample(0u) == (int16_t)-32768, "adc 0 -> -32768");
    expect(h753_adc_to_sample(32768u) == 0, "adc midscale -> 0");
    expect(h753_adc_to_sample(65535u) == 32767, "adc full-scale -> 32767");
    expect((int32_t)h753_adc_to_sample(0u) + (int32_t)H753_ADC_MIDSCALE == 0,
           "round-trip 0");
    expect((int32_t)h753_adc_to_sample(65535u) + (int32_t)H753_ADC_MIDSCALE == 65535,
           "round-trip full-scale");

    uint8_t frame[WD_MAX_PACKET_BYTES];
    size_t len = 0u;
    expect(h753_encode_adc_sample(32768u, 3u, 12345ull, frame, sizeof frame, &len) == WD_OK,
           "encode midscale");
    expect(len == wd_frame_length(H753_CHANNEL_COUNT, H753_SAMPLE_COUNT), "frame length");
    expect(len == 28u, "1-ch 1-sample frame is 28 bytes");

    wd_packet_t pkt;
    expect(wd_decode_frame(frame, len, &pkt) == WD_OK, "decode with C codec");
    expect(pkt.msg_type == WD_MSG_SAMPLE_BLOCK, "SAMPLE_BLOCK");
    expect(pkt.node_id == H753_NODE_ID, "node_id");
    expect(pkt.seq == 3u, "seq");
    expect(pkt.t_node_us == 12345ull, "t_node_us");
    expect(pkt.sample_rate_hz == H753_SAMPLE_RATE_HZ, "sample_rate_hz");
    expect(pkt.channel_count == H753_CHANNEL_COUNT, "channel_count");
    expect(pkt.sample_count == H753_SAMPLE_COUNT, "sample_count");
    expect(pkt.values[0] == 0, "mapped sample");

    uint8_t frame2[WD_MAX_PACKET_BYTES];
    size_t len2 = 0u;
    expect(h753_encode_adc_sample(0u, 4u, 22345ull, frame2, sizeof frame2, &len2) == WD_OK,
           "encode zero");
    wd_packet_t pkt2;
    expect(wd_decode_frame(frame2, len2, &pkt2) == WD_OK, "decode second frame");
    expect(pkt2.seq == 4u, "sequence advances");
    expect(pkt2.values[0] == (int16_t)-32768, "zero-scale sample");

    uint8_t flipped[WD_MAX_PACKET_BYTES];
    size_t i;
    for (i = 0u; i < len; ++i) {
        flipped[i] = frame[i];
    }
    flipped[24] ^= 0x01u; /* payload bit flip */
    expect(wd_decode_frame(flipped, len, &pkt) == WD_ERR_CRC, "corrupt payload is CRC");

    printf("h753 protocol helper: all checks pass\n");
    return 0;
}
