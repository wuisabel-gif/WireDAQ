// C++ contract trip-wire: the C++ wrapper must reproduce every golden vector exactly,
// through the same C codec the firmware uses. Same vectors, same bytes as the Python
// (tests/test_golden_vectors.py) and C (firmware/test/test_golden_vectors.c) sides.
//
// golden_vectors.h is generated from src/wiredaq/protocol/golden/vectors.json by
// gen_golden_header.py (the CMake build runs it first).

#include <cstdio>
#include <vector>

#include <wiredaq/wiredaq.hpp>

#include "golden_vectors.h"

static int g_failures = 0;

static void check_vector(const golden_vector_t& v) {
    // --- encode: fields -> bytes, must equal the golden frame exactly ---
    wiredaq::Packet pkt;
    pkt.node_id = v.node_id;
    pkt.seq = v.seq;
    pkt.t_node_us = v.t_node_us;
    pkt.sample_rate_hz = v.sample_rate_hz;
    pkt.channel_count = v.channel_count;
    pkt.samples.assign(v.values, v.values + v.n_values);

    bool ok = true;
    try {
        std::vector<std::uint8_t> out = wiredaq::encode(pkt);
        std::vector<std::uint8_t> want(v.frame, v.frame + v.frame_len);
        if (out != want) {
            std::printf("  FAIL %-24s encode bytes differ\n", v.name);
            ok = false;
        }
    } catch (const wiredaq::EncodeError&) {
        std::printf("  FAIL %-24s encode threw\n", v.name);
        ok = false;
    }

    // --- decode: golden bytes -> fields, must match the input ---
    std::optional<wiredaq::Packet> back = wiredaq::decode(v.frame, v.frame_len);
    if (!back) {
        std::printf("  FAIL %-24s decode returned nullopt\n", v.name);
        ok = false;
    } else if (*back != pkt) {
        std::printf("  FAIL %-24s decode fields differ\n", v.name);
        ok = false;
    }

    if (ok) std::printf("  ok   %-24s len=%zu\n", v.name, v.frame_len);
    else    ++g_failures;
}

static bool crc_self_test() {
    const auto* s = reinterpret_cast<const std::uint8_t*>("123456789");
    std::uint16_t crc = wiredaq::crc16_ccitt_false(s, 9);
    if (crc != 0x29B1u) {
        std::printf("  FAIL crc self-test: expected 0x29B1, got 0x%04X\n", crc);
        return false;
    }
    std::printf("  ok   crc self-test (0x29B1)\n");
    return true;
}

static bool crc_rejects_corruption() {
    // Flip one payload bit in the first vector with a payload; decode must reject it.
    for (std::size_t i = 0; i < GOLDEN_VECTOR_COUNT; ++i) {
        const golden_vector_t& v = GOLDEN_VECTORS[i];
        if (v.frame_len <= wiredaq::header_size + 2) continue;  // no payload
        std::vector<std::uint8_t> buf(v.frame, v.frame + v.frame_len);
        buf[wiredaq::header_size] ^= 0x01;
        wiredaq::Packet out;
        wiredaq::Status st = wiredaq::decode(buf.data(), buf.size(), out);
        if (st != wiredaq::Status::crc) {
            std::printf("  FAIL corruption check on %s: expected Status::crc\n", v.name);
            return false;
        }
        std::printf("  ok   crc rejects corruption (via %s)\n", v.name);
        return true;
    }
    return true;
}

int main() {
    std::printf("WireDAQ C++ codec — golden-vector conformance\n");
    bool selftests = crc_self_test();
    for (std::size_t i = 0; i < GOLDEN_VECTOR_COUNT; ++i) check_vector(GOLDEN_VECTORS[i]);
    selftests = crc_rejects_corruption() && selftests;

    if (g_failures || !selftests) {
        std::printf("FAILED: %d vector failure(s)%s\n", g_failures,
                    selftests ? "" : " + a self-test failure");
        return 1;
    }
    std::printf("All %u golden vectors reproduced byte-for-byte (C++). PASS\n",
                GOLDEN_VECTOR_COUNT);
    return 0;
}
