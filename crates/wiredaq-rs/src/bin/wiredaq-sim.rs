use std::env;
use std::error::Error;

use wiredaq_rs::{load_scenario_file, run_scenario};

fn main() -> Result<(), Box<dyn Error>> {
    let Some(path) = env::args().nth(1) else {
        eprintln!("usage: wiredaq-sim <scenario.lua>");
        std::process::exit(2);
    };

    let scenario = load_scenario_file(&path)?;
    let report = run_scenario(&scenario)?;

    println!("scenario: {}", report.scenario_name);
    println!("duration_s: {:.3}", report.duration_s);
    println!("nodes: {}", report.node_count);
    println!("packets_offered: {}", report.packet_count);
    println!("samples: {}", report.sample_count);
    println!("payload_values: {}", report.payload_sample_values);
    println!("encoded_bytes: {}", report.encoded_bytes);
    println!("max_frame_bytes: {}", report.max_frame_bytes);
    println!("---- simulated link (seeded) ----");
    println!("delivered: {}", report.delivered_packets);
    println!("dropped: {}", report.dropped_packets);
    println!("duplicated: {}", report.duplicate_packets);
    println!("reordered: {}", report.reordered_packets);
    println!("decoded_ok: {}", report.decoded_ok);
    println!(
        "lost (expected {:.2} / receiver-observed {})",
        report.expected_lost_packets, report.observed_lost_packets
    );
    if report.assertion_failures.is_empty() {
        println!("assertions: ok");
    } else {
        println!("assertions: {} FAILED", report.assertion_failures.len());
        for failure in &report.assertion_failures {
            println!("  - {failure}");
        }
    }

    Ok(())
}
