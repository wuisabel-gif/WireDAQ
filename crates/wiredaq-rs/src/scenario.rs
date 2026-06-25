use std::error::Error;
use std::fmt;
use std::fs;
use std::path::Path;

use mlua::{Lua, Table};

use crate::protocol::{encode_sample_block, frame_length, MAX_PACKET_BYTES};

#[derive(Clone, Debug, PartialEq)]
pub struct Scenario {
    pub name: String,
    pub duration_s: f64,
    pub transport: Transport,
    pub nodes: Vec<Node>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Transport {
    pub kind: String,
    pub loss_rate: f64,
    pub duplicate_rate: f64,
    pub reorder_rate: f64,
    pub jitter_us: u32,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Node {
    pub id: u16,
    pub name: String,
    pub sample_rate_hz: u32,
    pub samples_per_packet: u8,
    pub channels: Vec<Channel>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Channel {
    pub id: u8,
    pub name: String,
    pub kind: String,
}

#[derive(Clone, Debug, PartialEq)]
pub struct RunReport {
    pub scenario_name: String,
    pub duration_s: f64,
    pub node_count: usize,
    pub packet_count: u64,
    pub sample_count: u64,
    pub payload_sample_values: u64,
    pub encoded_bytes: u64,
    pub max_frame_bytes: usize,
    pub expected_lost_packets: f64,
}

#[derive(Debug)]
pub enum ScenarioError {
    EmptyNodes,
    EmptyChannels { node: String },
    InvalidSamplesPerPacket { node: String },
    PacketTooLarge { node: String, frame_len: usize },
}

impl fmt::Display for ScenarioError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::EmptyNodes => write!(f, "scenario must contain at least one node"),
            Self::EmptyChannels { node } => write!(f, "node {node} must contain at least one channel"),
            Self::InvalidSamplesPerPacket { node } => {
                write!(f, "node {node} must use samples_per_packet greater than zero")
            }
            Self::PacketTooLarge { node, frame_len } => write!(
                f,
                "node {node} produces {frame_len}-byte frames, above the {MAX_PACKET_BYTES}-byte limit"
            ),
        }
    }
}

impl Error for ScenarioError {}

pub fn load_scenario_file(path: impl AsRef<Path>) -> Result<Scenario, Box<dyn Error>> {
    let text = fs::read_to_string(path)?;
    load_scenario_str(&text)
}

pub fn load_scenario_str(text: &str) -> Result<Scenario, Box<dyn Error>> {
    let lua = Lua::new();
    let table: Table = lua.load(text).eval()?;
    scenario_from_table(table)
}

pub fn run_scenario(scenario: &Scenario) -> Result<RunReport, Box<dyn Error>> {
    validate_scenario(scenario)?;

    let mut packet_count = 0_u64;
    let mut sample_count = 0_u64;
    let mut payload_sample_values = 0_u64;
    let mut encoded_bytes = 0_u64;
    let mut max_frame_bytes = 0_usize;

    for node in &scenario.nodes {
        let total_samples = (scenario.duration_s * node.sample_rate_hz as f64).round() as u64;
        let mut emitted_samples = 0_u64;
        let mut seq = 0_u32;

        while emitted_samples < total_samples {
            let remaining = total_samples - emitted_samples;
            let samples_this_packet = remaining.min(node.samples_per_packet as u64) as u8;
            let rows = synthetic_samples(seq, samples_this_packet, node.channels.len());
            let frame = encode_sample_block(
                node.id,
                seq,
                timestamp_for_sample(emitted_samples, node.sample_rate_hz),
                node.sample_rate_hz,
                node.channels.len() as u8,
                &rows,
            )?;

            max_frame_bytes = max_frame_bytes.max(frame.len());
            encoded_bytes += frame.len() as u64;
            packet_count += 1;
            sample_count += samples_this_packet as u64;
            payload_sample_values += samples_this_packet as u64 * node.channels.len() as u64;
            emitted_samples += samples_this_packet as u64;
            seq = seq.wrapping_add(1);
        }
    }

    Ok(RunReport {
        scenario_name: scenario.name.clone(),
        duration_s: scenario.duration_s,
        node_count: scenario.nodes.len(),
        packet_count,
        sample_count,
        payload_sample_values,
        encoded_bytes,
        max_frame_bytes,
        expected_lost_packets: packet_count as f64 * scenario.transport.loss_rate,
    })
}

fn scenario_from_table(table: Table) -> Result<Scenario, Box<dyn Error>> {
    let transport_table: Table = table.get("transport")?;
    let nodes_table: Table = table.get("nodes")?;
    let mut nodes = Vec::new();

    for node_table in nodes_table.sequence_values::<Table>() {
        let node_table = node_table?;
        let channels_table: Table = node_table.get("channels")?;
        let mut channels = Vec::new();

        for channel_table in channels_table.sequence_values::<Table>() {
            let channel_table = channel_table?;
            channels.push(Channel {
                id: channel_table.get("id")?,
                name: channel_table.get("name")?,
                kind: channel_table.get("kind")?,
            });
        }

        nodes.push(Node {
            id: node_table.get("id")?,
            name: node_table.get("name")?,
            sample_rate_hz: node_table.get("sample_rate_hz")?,
            samples_per_packet: node_table.get("samples_per_packet")?,
            channels,
        });
    }

    Ok(Scenario {
        name: table.get("name")?,
        duration_s: table.get("duration_s")?,
        transport: Transport {
            kind: transport_table.get("kind")?,
            loss_rate: transport_table.get("loss_rate")?,
            duplicate_rate: transport_table.get("duplicate_rate")?,
            reorder_rate: transport_table.get("reorder_rate")?,
            jitter_us: transport_table.get("jitter_us")?,
        },
        nodes,
    })
}

fn validate_scenario(scenario: &Scenario) -> Result<(), ScenarioError> {
    if scenario.nodes.is_empty() {
        return Err(ScenarioError::EmptyNodes);
    }

    for node in &scenario.nodes {
        if node.samples_per_packet == 0 {
            return Err(ScenarioError::InvalidSamplesPerPacket {
                node: node.name.clone(),
            });
        }
        if node.channels.is_empty() {
            return Err(ScenarioError::EmptyChannels {
                node: node.name.clone(),
            });
        }

        let frame_len = frame_length(node.channels.len() as u8, node.samples_per_packet);
        if frame_len > MAX_PACKET_BYTES {
            return Err(ScenarioError::PacketTooLarge {
                node: node.name.clone(),
                frame_len,
            });
        }
    }

    Ok(())
}

fn timestamp_for_sample(sample_index: u64, sample_rate_hz: u32) -> u64 {
    if sample_rate_hz == 0 {
        return 0;
    }
    ((sample_index as u128 * 1_000_000_u128) / sample_rate_hz as u128) as u64
}

fn synthetic_samples(seq: u32, sample_count: u8, channel_count: usize) -> Vec<Vec<i16>> {
    let mut rows = Vec::with_capacity(sample_count as usize);

    for sample_i in 0..sample_count {
        let mut row = Vec::with_capacity(channel_count);
        for channel_i in 0..channel_count {
            let value = seq as i32 * 17 + sample_i as i32 * 3 + channel_i as i32;
            row.push((value % 32_000) as i16);
        }
        rows.push(row);
    }

    rows
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn loads_microdaq_lua_scenario() {
        let path = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .join("scenarios/microdaq_10khz.lua");

        let scenario = load_scenario_file(path).unwrap();

        assert_eq!(scenario.name, "microdaq_10khz");
        assert_eq!(scenario.nodes.len(), 1);
        assert_eq!(scenario.nodes[0].sample_rate_hz, 10_000);
        assert_eq!(scenario.nodes[0].channels.len(), 4);
    }

    #[test]
    fn runs_microdaq_lua_scenario() {
        let path = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .join("scenarios/microdaq_10khz.lua");

        let scenario = load_scenario_file(path).unwrap();
        let report = run_scenario(&scenario).unwrap();

        assert_eq!(report.packet_count, 25_000);
        assert_eq!(report.sample_count, 100_000);
        assert_eq!(report.payload_sample_values, 400_000);
        assert!(report.max_frame_bytes <= MAX_PACKET_BYTES);
    }
}
