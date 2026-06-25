use std::error::Error;
use std::fmt;

pub const MAGIC: [u8; 2] = [0x57, 0x44];
pub const VERSION: u8 = 1;
pub const MAX_PACKET_BYTES: usize = 256;

const HEADER_SIZE: usize = 24;
const CRC_SIZE: usize = 2;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MsgType {
    SampleBlock = 1,
    Heartbeat = 2,
}

impl MsgType {
    fn from_u8(value: u8) -> Result<Self, CodecError> {
        match value {
            1 => Ok(Self::SampleBlock),
            2 => Ok(Self::Heartbeat),
            other => Err(CodecError::UnsupportedMsgType(other)),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Packet {
    pub msg_type: MsgType,
    pub node_id: u16,
    pub seq: u32,
    pub t_node_us: u64,
    pub sample_rate_hz: u32,
    pub channel_count: u8,
    pub samples: Vec<Vec<i16>>,
}

impl Packet {
    pub fn sample_count(&self) -> usize {
        self.samples.len()
    }

    pub fn is_heartbeat(&self) -> bool {
        self.msg_type == MsgType::Heartbeat
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CodecError {
    BadMagic([u8; 2]),
    BadVersion(u8),
    CrcMismatch { expected: u16, found: u16 },
    FrameTooLong(usize),
    FrameTooShort(usize),
    LengthMismatch { expected: usize, found: usize },
    SampleShapeMismatch,
    UnsupportedMsgType(u8),
}

impl fmt::Display for CodecError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::BadMagic(magic) => write!(f, "bad magic: {:02X?}", magic),
            Self::BadVersion(version) => write!(f, "unsupported version: {version}"),
            Self::CrcMismatch { expected, found } => {
                write!(f, "CRC mismatch: expected 0x{expected:04X}, found 0x{found:04X}")
            }
            Self::FrameTooLong(len) => write!(f, "frame exceeds maximum length: {len} bytes"),
            Self::FrameTooShort(len) => write!(f, "frame too short: {len} bytes"),
            Self::LengthMismatch { expected, found } => {
                write!(f, "length mismatch: expected {expected} bytes, got {found}")
            }
            Self::SampleShapeMismatch => write!(f, "sample rows must match channel_count"),
            Self::UnsupportedMsgType(msg_type) => write!(f, "unsupported msg_type: {msg_type}"),
        }
    }
}

impl Error for CodecError {}

pub fn crc16_ccitt_false(data: &[u8]) -> u16 {
    let mut crc: u16 = 0xFFFF;

    for byte in data {
        crc ^= (*byte as u16) << 8;
        for _ in 0..8 {
            if crc & 0x8000 != 0 {
                crc = (crc << 1) ^ 0x1021;
            } else {
                crc <<= 1;
            }
        }
    }

    crc
}

pub fn frame_length(channel_count: u8, sample_count: u8) -> usize {
    HEADER_SIZE + channel_count as usize * sample_count as usize * 2 + CRC_SIZE
}

pub fn encode_sample_block(
    node_id: u16,
    seq: u32,
    t_node_us: u64,
    sample_rate_hz: u32,
    channel_count: u8,
    samples: &[Vec<i16>],
) -> Result<Vec<u8>, CodecError> {
    let sample_count = samples.len();
    if sample_count > u8::MAX as usize {
        return Err(CodecError::FrameTooLong(
            HEADER_SIZE + sample_count * channel_count as usize * 2 + CRC_SIZE,
        ));
    }

    let mut frame = header(
        MsgType::SampleBlock,
        node_id,
        seq,
        t_node_us,
        sample_rate_hz,
        channel_count,
        sample_count as u8,
    );

    for row in samples {
        if row.len() != channel_count as usize {
            return Err(CodecError::SampleShapeMismatch);
        }
        for value in row {
            frame.extend_from_slice(&value.to_le_bytes());
        }
    }

    finish_frame(frame)
}

pub fn encode_heartbeat(
    node_id: u16,
    seq: u32,
    t_node_us: u64,
    sample_rate_hz: u32,
) -> Result<Vec<u8>, CodecError> {
    finish_frame(header(
        MsgType::Heartbeat,
        node_id,
        seq,
        t_node_us,
        sample_rate_hz,
        0,
        0,
    ))
}

pub fn decode(frame: &[u8]) -> Result<Packet, CodecError> {
    if frame.len() < HEADER_SIZE + CRC_SIZE {
        return Err(CodecError::FrameTooShort(frame.len()));
    }
    if frame.len() > MAX_PACKET_BYTES {
        return Err(CodecError::FrameTooLong(frame.len()));
    }

    let magic = [frame[0], frame[1]];
    if magic != MAGIC {
        return Err(CodecError::BadMagic(magic));
    }

    let version = frame[2];
    if version != VERSION {
        return Err(CodecError::BadVersion(version));
    }

    let msg_type = MsgType::from_u8(frame[3])?;
    let node_id = u16::from_le_bytes([frame[4], frame[5]]);
    let seq = u32::from_le_bytes([frame[6], frame[7], frame[8], frame[9]]);
    let t_node_us = u64::from_le_bytes([
        frame[10], frame[11], frame[12], frame[13], frame[14], frame[15], frame[16], frame[17],
    ]);
    let sample_rate_hz = u32::from_le_bytes([frame[18], frame[19], frame[20], frame[21]]);
    let channel_count = frame[22];
    let sample_count = frame[23];

    let expected_len = frame_length(channel_count, sample_count);
    if frame.len() != expected_len {
        return Err(CodecError::LengthMismatch {
            expected: expected_len,
            found: frame.len(),
        });
    }

    let found = u16::from_le_bytes([frame[frame.len() - 2], frame[frame.len() - 1]]);
    let expected = crc16_ccitt_false(&frame[..frame.len() - CRC_SIZE]);
    if found != expected {
        return Err(CodecError::CrcMismatch { expected, found });
    }

    let mut samples = Vec::with_capacity(sample_count as usize);
    let mut offset = HEADER_SIZE;
    for _ in 0..sample_count {
        let mut row = Vec::with_capacity(channel_count as usize);
        for _ in 0..channel_count {
            row.push(i16::from_le_bytes([frame[offset], frame[offset + 1]]));
            offset += 2;
        }
        samples.push(row);
    }

    Ok(Packet {
        msg_type,
        node_id,
        seq,
        t_node_us,
        sample_rate_hz,
        channel_count,
        samples,
    })
}

fn header(
    msg_type: MsgType,
    node_id: u16,
    seq: u32,
    t_node_us: u64,
    sample_rate_hz: u32,
    channel_count: u8,
    sample_count: u8,
) -> Vec<u8> {
    let mut frame = Vec::with_capacity(HEADER_SIZE);
    frame.extend_from_slice(&MAGIC);
    frame.push(VERSION);
    frame.push(msg_type as u8);
    frame.extend_from_slice(&node_id.to_le_bytes());
    frame.extend_from_slice(&seq.to_le_bytes());
    frame.extend_from_slice(&t_node_us.to_le_bytes());
    frame.extend_from_slice(&sample_rate_hz.to_le_bytes());
    frame.push(channel_count);
    frame.push(sample_count);
    frame
}

fn finish_frame(mut frame: Vec<u8>) -> Result<Vec<u8>, CodecError> {
    let frame_len = frame.len() + CRC_SIZE;
    if frame_len > MAX_PACKET_BYTES {
        return Err(CodecError::FrameTooLong(frame_len));
    }

    let crc = crc16_ccitt_false(&frame);
    frame.extend_from_slice(&crc.to_le_bytes());
    Ok(frame)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hex_to_bytes(hex: &str) -> Vec<u8> {
        assert!(hex.len() % 2 == 0);
        (0..hex.len())
            .step_by(2)
            .map(|i| u8::from_str_radix(&hex[i..i + 2], 16).unwrap())
            .collect()
    }

    #[test]
    fn crc_check_value_matches_schema() {
        assert_eq!(crc16_ccitt_false(b"123456789"), 0x29B1);
    }

    #[test]
    fn encodes_minimal_golden_vector() {
        let expected =
            hex_to_bytes("574401010100000000000000000000000000e80300000101e803b5a7");

        let frame = encode_sample_block(1, 0, 0, 1000, 1, &[vec![1000]]).unwrap();

        assert_eq!(frame, expected);
    }

    #[test]
    fn encodes_accel_golden_vector() {
        let expected = hex_to_bytes(
            "5744010107002a000000d202964900000000800c000003040a00ecff00400c00eefffc3ffbff000006406400c800803e2327",
        );

        let frame = encode_sample_block(
            7,
            42,
            1_234_567_890,
            3200,
            3,
            &[
                vec![10, -20, 16_384],
                vec![12, -18, 16_380],
                vec![-5, 0, 16_390],
                vec![100, 200, 16_000],
            ],
        )
        .unwrap();

        assert_eq!(frame, expected);
    }

    #[test]
    fn encodes_heartbeat_golden_vector() {
        let expected =
            hex_to_bytes("5744010207002a000000d202964900000000800c0000000073e5");

        let frame = encode_heartbeat(7, 42, 1_234_567_890, 3200).unwrap();

        assert_eq!(frame, expected);
    }

    #[test]
    fn decodes_int16_boundaries() {
        let frame =
            hex_to_bytes("57440101ff00ffffffffffffffffffffffff80bb000002020080ff7f0000ffff2d4d");

        let packet = decode(&frame).unwrap();

        assert_eq!(packet.node_id, 255);
        assert_eq!(packet.seq, u32::MAX);
        assert_eq!(packet.t_node_us, u64::MAX);
        assert_eq!(packet.sample_rate_hz, 48_000);
        assert_eq!(packet.samples, vec![vec![-32_768, 32_767], vec![0, -1]]);
    }
}
