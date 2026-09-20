/*
 * NUCLEO-H753ZI sample-block helper.
 *
 * MCU-independent so the same mapping and encode path can be unit-tested on
 * the host. Frames are produced exclusively by the existing WireDAQ C codec;
 * this file does not define a board-specific wire format.
 */
#ifndef H753_PROTOCOL_H
#define H753_PROTOCOL_H

#include "wiredaq_codec.h"

#define H753_NODE_ID 1u
#define H753_CHANNEL_COUNT 1u
#define H753_SAMPLE_COUNT 1u
#define H753_SAMPLE_RATE_HZ 10u
#define H753_PERIOD_MS (1000u / H753_SAMPLE_RATE_HZ)
#define H753_ADC_MIDSCALE 32768

/* Unipolar 16-bit ADC -> signed int16: wire = raw - 32768.
 * Host reconstruction: raw = wire + 32768. */
int16_t h753_adc_to_sample(uint16_t adc_raw);

wd_status_t h753_encode_adc_sample(uint16_t adc_raw,
                                   uint32_t seq,
                                   uint64_t t_node_us,
                                   uint8_t *out,
                                   size_t out_cap,
                                   size_t *out_len);

#endif /* H753_PROTOCOL_H */
