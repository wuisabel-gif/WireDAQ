# Changelog

All notable changes to WireDAQ. Versions follow [SemVer](https://semver.org/); the wire
format is versioned separately in the packet header (see ADR 0003).

## [0.3.0] — unreleased

Version numbers are bumped and reconciled across `pyproject.toml`, `Cargo.toml`, and
`CMakeLists.txt`; tag `v0.3.0` to publish to PyPI.

### Added
- **Per-node clock reconstruction (ADR 0002).** The ground station fits a per-node
  `ClockModel` (online least squares) against its reference clock, recovering each node's
  drift and mapping node timestamps onto one timeline. Recovered drift matches the injected
  `drift_ppm` within < 0.5 ppm; jitter widens the confidence interval without biasing it.
- `wiredaq-clocksync` CLI — demos drift recovery and cross-node timeline alignment.
- `CsvLogger` writes a reconstructed `t_ref_us` column so drifted nodes align in the export.
- **Rust/Lua backend now runs a seeded link simulation** — per-packet loss / duplication /
  jitter / reorder with a decode-side receiver, plus executed `faults` and `assertions`
  tables; unknown fault kinds are rejected. Its golden vectors are read from the shared
  `vectors.json` (decode + re-encode) and `cargo test` runs in CI.

### Fixed
- `RawFrameLogger` and `StreamReceiver` handle HEARTBEAT frames correctly (were re-encoded
  as / rejected as data, causing byte-mismatched archives and phantom loss).
- Clock drift is no longer quantized to zero at the CLI-default ppm (float accumulation).
- C++ wrapper rejects sample counts that overflow the `uint8` wire field instead of
  silently truncating.
- Impairment corruption is always classified as CRC, not framing.
- Decoders (Python / C / Rust) fail closed on control-plane shape: a HEARTBEAT with nonzero
  channel/sample counts is rejected.
- C++ `encode()` dispatches on `msg_type`, so `encode(decode(heartbeat))` round-trips.
- Collector distinguishes a stale duplicate from a genuine reorder (bounded seen-set), so a
  late duplicate no longer decrements real loss; reorder is counted only on an actual overtake.

### Docs
- Fixed stale test counts, softened overclaims ("avionics-grade", "HIL is a drop-in",
  "wired to the schema"), named ADR deciders, and repaired the two broken demo-site links.

## [0.2.0]

### Added
- Controllable clock (`SimClock` / `WallClock`) for deterministic, reproducible timing.
- Link latency + jitter in the honest-fake transport (jitter alone produces reordering).
- HEARTBEAT liveness/clock beacons across all three codecs, with node-stale detection.
- Continuous integration: tests on Python 3.10–3.12 plus cross-language codec conformance.
