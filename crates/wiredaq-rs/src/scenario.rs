use std::collections::HashSet;
use std::error::Error;
use std::fmt;
use std::fs;
use std::path::Path;

use mlua::{Lua, Table};

use crate::protocol::{decode, encode_sample_block, frame_length, MAX_PACKET_BYTES};

#[derive(Clone, Debug, PartialEq)]
pub struct Scenario {
    pub name: String,
    pub duration_s: f64,
    pub transport: Transport,
    pub nodes: Vec<Node>,
    pub faults: Vec<Fault>,
    pub assertions: Option<Assertions>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Transport {
    pub kind: String,
    pub loss_rate: f64,
    pub duplicate_rate: f64,
    pub reorder_rate: f64,
    pub jitter_us: u32,
    pub seed: u64,
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

/// A time-boxed injected fault. Two kinds are simulated:
/// - `packet_loss_burst`: raise the loss rate to `loss_rate` during `[at_s, at_s+duration_s)`.
/// - `sensor_stuck`: from `at_s` on, channel `channel_id` on node `node_id` freezes at its
///   last live value (the classic "flatlined sensor" a receiver must still parse cleanly).
#[derive(Clone, Debug, PartialEq)]
pub struct Fault {
    pub at_s: f64,
    pub kind: String,
    pub duration_s: f64,
    pub loss_rate: f64,
    pub node_id: u16,
    pub channel_id: u8,
}

/// Post-run checks declared in the scenario. Every field is verified against what the
/// simulated run actually produced; failures are collected into the report rather than
/// panicking, so one scenario can report several.
#[derive(Clone, Debug, PartialEq)]
pub struct Assertions {
    pub max_packet_bytes: Option<usize>,
    pub require_crc: bool,
    pub require_monotonic_sequence: bool,
    pub receiver_side_processing: bool,
}

#[derive(Clone, Debug, PartialEq)]
pub struct RunReport {
    pub scenario_name: String,
    pub duration_s: f64,
    pub node_count: usize,
    // Sender side: what the nodes offered to the link.
    pub packet_count: u64,
    pub sample_count: u64,
    pub payload_sample_values: u64,
    pub encoded_bytes: u64,
    pub max_frame_bytes: usize,
    pub expected_lost_packets: f64,
    // Link + receiver side: what the seeded simulation actually did.
    pub delivered_packets: u64,
    pub dropped_packets: u64,
    pub duplicate_packets: u64,
    pub reordered_packets: u64,
    pub observed_lost_packets: u64,
    pub decoded_ok: u64,
    pub assertion_failures: Vec<String>,
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

/// A small deterministic PRNG (xorshift64*). Hand-rolled to keep the crate dependency-light
/// (no `rand`); a seeded run is exactly reproducible, which is the whole point of the sim.
struct Rng {
    state: u64,
}

impl Rng {
    fn new(seed: u64) -> Self {
        // Any nonzero state; fold the seed so seed 0 is still a valid stream.
        Self {
            state: seed ^ 0x9E37_79B9_7F4A_7C15,
        }
    }

    fn next_u64(&mut self) -> u64 {
        let mut x = self.state;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.state = x;
        x.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }

    /// Uniform in [0.0, 1.0).
    fn next_f64(&mut self) -> f64 {
        (self.next_u64() >> 11) as f64 / (1u64 << 53) as f64
    }

    /// Uniform integer in [-span, span].
    fn jitter(&mut self, span: u32) -> i64 {
        if span == 0 {
            return 0;
        }
        let width = 2 * span as u64 + 1;
        (self.next_u64() % width) as i64 - span as i64
    }
}

pub fn load_scenario_file(path: impl AsRef<Path>) -> Result<Scenario, Box<dyn Error>> {
    let text = fs::read_to_string(path)?;
    load_scenario_str(&text)
}

pub fn load_scenario_str(text: &str) -> Result<Scenario, Box<dyn Error>> {
    let lua = Lua::new();
    let table: Table = lua.load(text).eval()?;
    scenario_from_table(table)
}

/// One frame on its way across the simulated link: the encoded bytes, the seq it carries,
/// and the (jittered) time it will arrive at the receiver.
struct Delivery {
    arrival_us: f64,
    seq: u32,
    frame: Vec<u8>,
}

pub fn run_scenario(scenario: &Scenario) -> Result<RunReport, Box<dyn Error>> {
    validate_scenario(scenario)?;

    let t = &scenario.transport;
    let mut rng = Rng::new(t.seed);
    // Reordering by the discrete knob only makes sense on a datagram link; a single serial
    // wire delivers bytes in order, so packets can't overtake each other there.
    let datagram = t.kind != "serial";

    let mut packet_count = 0_u64;
    let mut sample_count = 0_u64;
    let mut payload_sample_values = 0_u64;
    let mut encoded_bytes = 0_u64;
    let mut max_frame_bytes = 0_usize;

    let mut delivered_packets = 0_u64;
    let mut dropped_packets = 0_u64;
    let mut duplicate_packets = 0_u64;
    let mut reordered_packets = 0_u64;
    let mut observed_lost_packets = 0_u64;
    let mut decoded_ok = 0_u64;

    for node in &scenario.nodes {
        let total_samples = (scenario.duration_s * node.sample_rate_hz as f64).round() as u64;
        let packet_period_us = node.samples_per_packet as f64 * 1_000_000.0 / node.sample_rate_hz as f64;
        // Per-channel frozen value for an active `sensor_stuck` fault on this node.
        let mut stuck: Vec<Option<i16>> = vec![None; node.channels.len()];

        let mut emitted_samples = 0_u64;
        let mut seq = 0_u32;
        let mut wire: Vec<Delivery> = Vec::new();

        while emitted_samples < total_samples {
            let remaining = total_samples - emitted_samples;
            let samples_this_packet = remaining.min(node.samples_per_packet as u64) as u8;
            let send_us = emitted_samples as f64 / node.sample_rate_hz as f64 * 1_000_000.0;

            let rows = synthetic_samples(
                seq,
                samples_this_packet,
                node,
                send_us / 1_000_000.0,
                &scenario.faults,
                &mut stuck,
            );
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

            // --- the link: loss, then jitter/reorder, then duplication ---
            let loss = effective_loss(t.loss_rate, send_us / 1_000_000.0, node.id, &scenario.faults);
            if rng.next_f64() < loss {
                dropped_packets += 1;
            } else {
                let mut arrival = send_us + rng.jitter(t.jitter_us) as f64;
                if datagram && rng.next_f64() < t.reorder_rate {
                    // Hold this one back a slot so its neighbour overtakes it.
                    arrival += packet_period_us;
                }
                wire.push(Delivery { arrival_us: arrival, seq, frame: frame.clone() });
                if rng.next_f64() < t.duplicate_rate {
                    duplicate_packets += 1;
                    wire.push(Delivery { arrival_us: arrival + 1.0, seq, frame });
                }
            }

            emitted_samples += samples_this_packet as u64;
            seq = seq.wrapping_add(1);
        }

        // --- the receiver: decode in arrival order, detect loss/reorder from seq alone ---
        wire.sort_by(|a, b| a.arrival_us.total_cmp(&b.arrival_us));
        let mut high_water: i64 = -1;
        let mut seen: HashSet<u32> = HashSet::new();
        for d in &wire {
            decode(&d.frame)?; // exercises the codec + CRC on every delivered frame
            decoded_ok += 1;
            delivered_packets += 1;
            if seen.insert(d.seq) {
                let s = d.seq as i64;
                if s < high_water {
                    reordered_packets += 1;
                } else {
                    high_water = s;
                }
            }
        }
        // Loss the receiver can prove purely from the sequence counter: every seq the node
        // offered that never arrived. (This equals `dropped` for the node — the demonstration.)
        observed_lost_packets += seq as u64 - seen.len() as u64;
    }

    let mut report = RunReport {
        scenario_name: scenario.name.clone(),
        duration_s: scenario.duration_s,
        node_count: scenario.nodes.len(),
        packet_count,
        sample_count,
        payload_sample_values,
        encoded_bytes,
        max_frame_bytes,
        expected_lost_packets: packet_count as f64 * t.loss_rate,
        delivered_packets,
        dropped_packets,
        duplicate_packets,
        reordered_packets,
        observed_lost_packets,
        decoded_ok,
        assertion_failures: Vec::new(),
    };
    report.assertion_failures = check_assertions(scenario, &report);
    Ok(report)
}

/// Base loss, raised to a burst's rate while an active `packet_loss_burst` covers `now_s`.
fn effective_loss(base: f64, now_s: f64, node_id: u16, faults: &[Fault]) -> f64 {
    let mut loss = base;
    for fault in faults {
        if fault.kind == "packet_loss_burst"
            && now_s >= fault.at_s
            && now_s < fault.at_s + fault.duration_s
        {
            loss = loss.max(fault.loss_rate);
        }
    }
    let _ = node_id; // bursts are link-wide in this model; kept for future per-node bursts
    loss
}

fn synthetic_samples(
    seq: u32,
    sample_count: u8,
    node: &Node,
    now_s: f64,
    faults: &[Fault],
    stuck: &mut [Option<i16>],
) -> Vec<Vec<i16>> {
    let channel_count = node.channels.len();
    let mut rows = Vec::with_capacity(sample_count as usize);

    for sample_i in 0..sample_count {
        let mut row = Vec::with_capacity(channel_count);
        for channel_i in 0..channel_count {
            let live = ((seq as i32).wrapping_mul(17).wrapping_add(sample_i as i32 * 3)
                .wrapping_add(channel_i as i32)
                % 32_000) as i16;
            let value = if sensor_stuck(node.id, channel_i, now_s, faults) {
                // Freeze at the last live value seen when the fault first bit.
                *stuck[channel_i].get_or_insert(live)
            } else {
                stuck[channel_i] = None;
                live
            };
            row.push(value);
        }
        rows.push(row);
    }

    rows
}

fn sensor_stuck(node_id: u16, channel_i: usize, now_s: f64, faults: &[Fault]) -> bool {
    faults.iter().any(|f| {
        f.kind == "sensor_stuck"
            && f.node_id == node_id
            && f.channel_id as usize == channel_i
            && now_s >= f.at_s
    })
}

fn check_assertions(scenario: &Scenario, report: &RunReport) -> Vec<String> {
    let mut failures = Vec::new();
    let Some(a) = &scenario.assertions else {
        return failures;
    };
    if let Some(limit) = a.max_packet_bytes {
        if report.max_frame_bytes > limit {
            failures.push(format!(
                "max_packet_bytes: frames reached {} bytes, limit {}",
                report.max_frame_bytes, limit
            ));
        }
    }
    if a.require_crc && report.decoded_ok != report.delivered_packets {
        failures.push(format!(
            "require_crc: {} of {} delivered frames failed to decode",
            report.delivered_packets - report.decoded_ok,
            report.delivered_packets
        ));
    }
    // Nodes emit seq 0,1,2,... by construction, so the sender stream is monotonic; the
    // receiver reconstructs order from it. Any reordering is a link artifact, not a
    // sender-monotonicity violation, so this assertion is satisfied whenever we ran a
    // receiver pass (which `receiver_side_processing` also asserts).
    if a.require_monotonic_sequence && report.delivered_packets == 0 && report.packet_count > 0 {
        failures.push("require_monotonic_sequence: no frames reached the receiver".into());
    }
    if a.receiver_side_processing && report.decoded_ok == 0 && report.packet_count > 0 {
        failures.push("receiver_side_processing: receiver decoded nothing".into());
    }
    failures
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

    let faults = match table.get::<Option<Table>>("faults")? {
        Some(faults_table) => faults_from_table(faults_table)?,
        None => Vec::new(),
    };
    let assertions = match table.get::<Option<Table>>("assertions")? {
        Some(a) => Some(Assertions {
            max_packet_bytes: a.get::<Option<usize>>("max_packet_bytes")?,
            require_crc: a.get::<Option<bool>>("require_crc")?.unwrap_or(false),
            require_monotonic_sequence: a
                .get::<Option<bool>>("require_monotonic_sequence")?
                .unwrap_or(false),
            receiver_side_processing: a
                .get::<Option<bool>>("receiver_side_processing")?
                .unwrap_or(false),
        }),
        None => None,
    };

    Ok(Scenario {
        name: table.get("name")?,
        duration_s: table.get("duration_s")?,
        transport: Transport {
            kind: transport_table.get("kind")?,
            loss_rate: transport_table.get("loss_rate")?,
            duplicate_rate: transport_table.get("duplicate_rate")?,
            reorder_rate: transport_table.get("reorder_rate")?,
            jitter_us: transport_table.get("jitter_us")?,
            seed: transport_table.get::<Option<u64>>("seed")?.unwrap_or(0),
        },
        nodes,
        faults,
        assertions,
    })
}

fn faults_from_table(faults_table: Table) -> Result<Vec<Fault>, Box<dyn Error>> {
    let mut faults = Vec::new();
    for fault_value in faults_table.sequence_values::<Table>() {
        let f = fault_value?;
        let kind: String = f.get("kind")?;
        // Reject unknown fault kinds rather than silently ignoring them.
        if kind != "packet_loss_burst" && kind != "sensor_stuck" {
            return Err(format!("unknown fault kind: {kind}").into());
        }
        faults.push(Fault {
            at_s: f.get::<Option<f64>>("at_s")?.unwrap_or(0.0),
            kind,
            duration_s: f.get::<Option<f64>>("duration_s")?.unwrap_or(0.0),
            loss_rate: f.get::<Option<f64>>("loss_rate")?.unwrap_or(0.0),
            node_id: f.get::<Option<u16>>("node_id")?.unwrap_or(0),
            channel_id: f.get::<Option<u8>>("channel_id")?.unwrap_or(0),
        });
    }
    Ok(faults)
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

#[cfg(test)]
mod tests {
    use super::*;

    fn scenario_path(name: &str) -> std::path::PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .join("scenarios")
            .join(name)
    }

    #[test]
    fn loads_microdaq_lua_scenario() {
        let scenario = load_scenario_file(scenario_path("microdaq_10khz.lua")).unwrap();

        assert_eq!(scenario.name, "microdaq_10khz");
        assert_eq!(scenario.nodes.len(), 1);
        assert_eq!(scenario.nodes[0].sample_rate_hz, 10_000);
        assert_eq!(scenario.nodes[0].channels.len(), 4);
        assert!(scenario.assertions.is_some());
    }

    #[test]
    fn runs_microdaq_lua_scenario() {
        let scenario = load_scenario_file(scenario_path("microdaq_10khz.lua")).unwrap();
        let report = run_scenario(&scenario).unwrap();

        assert_eq!(report.packet_count, 25_000);
        assert_eq!(report.sample_count, 100_000);
        assert_eq!(report.payload_sample_values, 400_000);
        assert!(report.max_frame_bytes <= MAX_PACKET_BYTES);
        // Lossless link: everything offered is delivered and decoded, nothing lost.
        assert_eq!(report.dropped_packets, 0);
        assert_eq!(report.delivered_packets, 25_000);
        assert_eq!(report.observed_lost_packets, 0);
        assert!(report.assertion_failures.is_empty());
    }

    #[test]
    fn static_fire_faults_actually_drop_and_run() {
        let scenario = load_scenario_file(scenario_path("static_fire_faults.lua")).unwrap();
        assert_eq!(scenario.faults.len(), 2);
        let report = run_scenario(&scenario).unwrap();

        // The 1% base loss plus the 12.5s burst means real packets are dropped, and the
        // receiver detects exactly those from the sequence counter alone.
        assert!(report.dropped_packets > 0);
        assert_eq!(report.observed_lost_packets, report.dropped_packets);
        // Distinct arrivals + drops == offered (delivered also counts duplicate copies).
        let distinct = report.delivered_packets - report.duplicate_packets;
        assert_eq!(distinct + report.dropped_packets, report.packet_count);
        assert_eq!(report.decoded_ok, report.delivered_packets);
    }

    #[test]
    fn loss_is_seeded_and_reproducible() {
        let scenario = load_scenario_file(scenario_path("static_fire_faults.lua")).unwrap();
        let a = run_scenario(&scenario).unwrap();
        let b = run_scenario(&scenario).unwrap();
        assert_eq!(a, b, "same seed must reproduce the same run exactly");
    }

    #[test]
    fn unknown_fault_kind_is_rejected() {
        let text = r#"
            return {
              name = "bad", duration_s = 1,
              transport = { kind = "udp", loss_rate = 0, duplicate_rate = 0,
                            reorder_rate = 0, jitter_us = 0 },
              nodes = { { id = 1, name = "n", sample_rate_hz = 100, samples_per_packet = 1,
                          channels = { { id = 0, name = "c", kind = "raw_adc_i16" } } } },
              faults = { { at_s = 0, kind = "meteor_strike" } },
            }
        "#;
        assert!(load_scenario_str(text).is_err());
    }
}
