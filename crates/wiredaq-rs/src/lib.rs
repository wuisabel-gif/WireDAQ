//! Rust experimental backend for WireDAQ.
//!
//! This crate starts with the same wire contract used by the Python, C, and C++
//! codecs: fixed header, little-endian fields, signed 16-bit samples, and
//! CRC-16/CCITT-FALSE. Keeping this dependency-light makes the backend easy to
//! build in restricted environments and keeps the first milestone focused on
//! byte compatibility.

pub mod protocol;
pub mod scenario;

pub use protocol::{
    crc16_ccitt_false, decode, encode_heartbeat, encode_sample_block, frame_length, CodecError,
    MsgType, Packet, MAGIC, MAX_PACKET_BYTES, VERSION,
};
pub use scenario::{load_scenario_file, run_scenario, Channel, Node, RunReport, Scenario, Transport};
