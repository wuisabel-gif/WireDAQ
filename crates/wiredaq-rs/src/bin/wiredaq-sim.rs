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
    println!("packets: {}", report.packet_count);
    println!("samples: {}", report.sample_count);
    println!("payload_values: {}", report.payload_sample_values);
    println!("encoded_bytes: {}", report.encoded_bytes);
    println!("max_frame_bytes: {}", report.max_frame_bytes);
    println!("expected_lost_packets: {:.2}", report.expected_lost_packets);

    Ok(())
}
