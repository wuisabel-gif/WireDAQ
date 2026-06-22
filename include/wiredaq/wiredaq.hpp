// WireDAQ — idiomatic C++ wrapper over the C codec.
//
// Header-only C++17. It does not reimplement the wire format: it forwards to the C
// codec (wiredaq_codec.h / .c), so the bytes are identical to the C and Python codecs
// and to the golden vectors. Link against `wiredaq::codec`.
//
//   #include <wiredaq/wiredaq.hpp>
//
//   wiredaq::Packet pkt;
//   pkt.node_id = 7; pkt.seq = 42; pkt.t_node_us = 1234;
//   pkt.sample_rate_hz = 3200; pkt.channel_count = 3;
//   pkt.samples = { 10, -20, 16384,  12, -18, 16380 };   // flat, row-major
//
//   std::vector<std::uint8_t> frame = wiredaq::encode(pkt);     // throws on bad input
//   std::optional<wiredaq::Packet> back = wiredaq::decode(frame); // nullopt on CRC/framing
//
#ifndef WIREDAQ_WIREDAQ_HPP
#define WIREDAQ_WIREDAQ_HPP

#include <cstddef>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <vector>

#include <wiredaq_codec.h>

namespace wiredaq {

inline constexpr unsigned version = WD_VERSION;
inline constexpr std::size_t max_packet_bytes = WD_MAX_PACKET_BYTES;
inline constexpr std::size_t header_size = WD_HEADER_SIZE;

/// Result of a decode attempt — mirrors the C `wd_status_t`.
enum class Status {
    ok = WD_OK,
    framing = WD_ERR_FRAMING,  ///< bad magic/version/msg_type/length/shape
    crc = WD_ERR_CRC,          ///< CRC mismatch: the bytes were corrupted
    too_big = WD_ERR_TOO_BIG,  ///< would exceed the 256-byte packet cap
    arg = WD_ERR_ARG,          ///< invalid argument / impossible field value
};

/// Thrown by `encode` when a packet can't be serialized (e.g. too large).
class EncodeError : public std::runtime_error {
public:
    explicit EncodeError(Status s)
        : std::runtime_error("wiredaq::encode failed"), status(s) {}
    Status status;
};

/// A decoded SAMPLE_BLOCK. `samples` is flat, row-major: size == channel_count *
/// sample_count, laid out [s0c0, s0c1, ..., s1c0, ...].
struct Packet {
    std::uint8_t msg_type = WD_MSG_SAMPLE_BLOCK;  ///< SAMPLE_BLOCK or HEARTBEAT
    std::uint16_t node_id = 0;
    std::uint32_t seq = 0;
    std::uint64_t t_node_us = 0;
    std::uint32_t sample_rate_hz = 0;
    std::uint8_t channel_count = 0;
    std::vector<std::int16_t> samples;

    std::size_t sample_count() const {
        return channel_count ? samples.size() / channel_count : 0;
    }

    bool is_heartbeat() const { return msg_type == WD_MSG_HEARTBEAT; }

    friend bool operator==(const Packet& a, const Packet& b) {
        return a.msg_type == b.msg_type && a.node_id == b.node_id && a.seq == b.seq
            && a.t_node_us == b.t_node_us && a.sample_rate_hz == b.sample_rate_hz
            && a.channel_count == b.channel_count && a.samples == b.samples;
    }
    friend bool operator!=(const Packet& a, const Packet& b) { return !(a == b); }
};

namespace detail {

inline void to_c(const Packet& p, wd_packet_t& c) {
    c.node_id = p.node_id;
    c.seq = p.seq;
    c.t_node_us = p.t_node_us;
    c.sample_rate_hz = p.sample_rate_hz;
    c.channel_count = p.channel_count;
    // sample_count is derived from the flat sample vector and the channel count.
    const std::size_t n = p.samples.size();
    c.sample_count = p.channel_count
        ? static_cast<std::uint8_t>(n / p.channel_count) : 0;
    for (std::size_t i = 0; i < n && i < WD_MAX_SAMPLE_VALUES; ++i) {
        c.values[i] = p.samples[i];
    }
}

inline Packet from_c(const wd_packet_t& c) {
    Packet p;
    p.msg_type = c.msg_type;
    p.node_id = c.node_id;
    p.seq = c.seq;
    p.t_node_us = c.t_node_us;
    p.sample_rate_hz = c.sample_rate_hz;
    p.channel_count = c.channel_count;
    const std::size_t n =
        static_cast<std::size_t>(c.sample_count) * c.channel_count;
    p.samples.assign(c.values, c.values + n);
    return p;
}

}  // namespace detail

/// CRC-16/CCITT-FALSE over `data`. crc16("123456789") == 0x29B1.
inline std::uint16_t crc16_ccitt_false(const std::uint8_t* data, std::size_t len) {
    return wd_crc16_ccitt_false(data, len);
}

/// Encode a packet to its complete on-wire frame (magic + header + payload + CRC).
/// Throws `EncodeError` if the packet can't be serialized.
inline std::vector<std::uint8_t> encode(const Packet& pkt) {
    if (pkt.channel_count != 0 && pkt.samples.size() % pkt.channel_count != 0) {
        throw EncodeError(Status::arg);  // ragged: not a whole number of samples
    }
    wd_packet_t c{};
    detail::to_c(pkt, c);
    std::uint8_t buf[WD_MAX_PACKET_BYTES];
    std::size_t out_len = 0;
    const wd_status_t st = wd_encode_sample_block(&c, buf, sizeof buf, &out_len);
    if (st != WD_OK) throw EncodeError(static_cast<Status>(st));
    return std::vector<std::uint8_t>(buf, buf + out_len);
}

/// Encode a HEARTBEAT (liveness / clock beacon): header-only frame, no payload.
/// Throws `EncodeError` if the frame can't be serialized.
inline std::vector<std::uint8_t> encode_heartbeat(
    std::uint16_t node_id, std::uint32_t seq, std::uint64_t t_node_us,
    std::uint32_t sample_rate_hz = 0) {
    std::uint8_t buf[WD_MAX_PACKET_BYTES];
    std::size_t out_len = 0;
    const wd_status_t st = wd_encode_heartbeat(
        node_id, seq, t_node_us, sample_rate_hz, buf, sizeof buf, &out_len);
    if (st != WD_OK) throw EncodeError(static_cast<Status>(st));
    return std::vector<std::uint8_t>(buf, buf + out_len);
}

/// Decode a frame, reporting the reason on failure. Returns `Status::ok` and fills
/// `out` on success; otherwise `out` is untouched.
inline Status decode(const std::uint8_t* frame, std::size_t len, Packet& out) {
    wd_packet_t c{};
    const wd_status_t st = wd_decode_frame(frame, len, &c);
    if (st != WD_OK) return static_cast<Status>(st);
    out = detail::from_c(c);
    return Status::ok;
}

/// Decode a frame, returning the packet or `std::nullopt` (corruption / framing).
inline std::optional<Packet> decode(const std::uint8_t* frame, std::size_t len) {
    Packet p;
    return decode(frame, len, p) == Status::ok ? std::optional<Packet>(std::move(p))
                                               : std::nullopt;
}

/// Convenience overload taking a byte vector.
inline std::optional<Packet> decode(const std::vector<std::uint8_t>& frame) {
    return decode(frame.data(), frame.size());
}

}  // namespace wiredaq

#endif  // WIREDAQ_WIREDAQ_HPP
