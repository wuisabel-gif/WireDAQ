// Minimal WireDAQ C++ usage: build a packet, encode it to wire bytes, decode it back.
//
//   #include <wiredaq/wiredaq.hpp>   // link wiredaq::codec
//
// Build via CMake (WIREDAQ_BUILD_EXAMPLES=ON) → ./build/wiredaq_example

#include <cstdio>

#include <wiredaq/wiredaq.hpp>

int main() {
    wiredaq::Packet pkt;
    pkt.node_id = 7;
    pkt.seq = 42;
    pkt.t_node_us = 1234567890;
    pkt.sample_rate_hz = 3200;
    pkt.channel_count = 3;                       // X / Y / Z
    pkt.samples = {10, -20, 16384,               // sample 0
                   12, -18, 16380};              // sample 1

    std::vector<std::uint8_t> frame = wiredaq::encode(pkt);
    std::printf("encoded %zu samples into a %zu-byte frame: ",
                pkt.sample_count(), frame.size());
    for (std::uint8_t b : frame) std::printf("%02x", b);
    std::printf("\n");

    std::optional<wiredaq::Packet> back = wiredaq::decode(frame);
    if (!back) {
        std::printf("decode failed\n");
        return 1;
    }
    std::printf("decoded node=%u seq=%u rate=%u Hz, %zu samples — round-trip %s\n",
                back->node_id, back->seq, back->sample_rate_hz, back->sample_count(),
                (*back == pkt) ? "OK" : "MISMATCH");
    return (*back == pkt) ? 0 : 1;
}
