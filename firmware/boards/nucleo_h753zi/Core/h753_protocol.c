#include "h753_protocol.h"

int16_t h753_adc_to_sample(uint16_t adc_raw)
{
    return (int16_t)((int32_t)adc_raw - (int32_t)H753_ADC_MIDSCALE);
}

wd_status_t h753_encode_adc_sample(uint16_t adc_raw,
                                   uint32_t seq,
                                   uint64_t t_node_us,
                                   uint8_t *out,
                                   size_t out_cap,
                                   size_t *out_len)
{
    wd_packet_t pkt;

    pkt.msg_type = WD_MSG_SAMPLE_BLOCK;
    pkt.node_id = H753_NODE_ID;
    pkt.seq = seq;
    pkt.t_node_us = t_node_us;
    pkt.sample_rate_hz = H753_SAMPLE_RATE_HZ;
    pkt.channel_count = H753_CHANNEL_COUNT;
    pkt.sample_count = H753_SAMPLE_COUNT;
    pkt.values[0] = h753_adc_to_sample(adc_raw);

    return wd_encode_sample_block(&pkt, out, out_cap, out_len);
}
