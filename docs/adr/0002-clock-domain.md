# 2. Clock domain: node-local time authoritative, corrected at the ground station

- **Status:** Accepted
- **Date:** 2026-06-20 (accepted 2026-07-02, on implementation)
- **Deciders:** Isabel Wu
- **Tags:** architecture, daq, timing, clock-sync, ground-station
- **Supersedes / relates to:** deferred from [ADR 0001](0001-wire-ready-architecture.md)

## Summary

Each node's own clock (`t_node_us`) is **authoritative on the wire and for intra-node
sample timing**, and is transmitted uncorrected. A **single global timeline is
reconstructed at the ground station**, per node, by fitting an online clock model
(offset + skew) that maps each node's clock onto a chosen reference clock. The wire format
does not change; correction is a ground-station-side concern. This is the "hybrid" option
below.

## Context

The schema (`src/wiredaq/protocol/packet_schema.yaml`) carries timing as:

- `t_node_us` — uint64, node-local microseconds at the **first sample** of the block, on
  the node's own free-running clock, explicitly *not* corrected to any global reference;
- `sample_rate_hz` — the declared rate, from which the receiver derives every other
  sample's timestamp: `t(sample_i) = t_node_us + round(i * 1e6 / sample_rate_hz)`
  (implemented in `Packet.sample_time_us`).

Two facts force a decision:

1. **Nodes have independent clocks that drift.** There is no shared clock line. Two nodes
   started together diverge over time — the simulator already models this honestly via
   `SyntheticNode(drift_ppm=...)`, which advances each node's `t_node_us` by the block
   duration scaled by `(1 + drift_ppm/1e6)`. Real crystals drift tens to hundreds of ppm.
2. **Time serves two different jobs.** *Intra-node*: the relative spacing of samples from
   one node (cadence, frequency content) — only that node's clock knows this accurately.
   *Inter-node*: aligning samples from different nodes onto one timeline, for any
   cross-node analysis. These have different best answers.

If we do not pin this, two failure modes appear at Phase 3 (when the real receiver enters
the loop): cross-node data cannot be aligned, and any code that reached for
packet-arrival time as a timestamp silently bakes in transport jitter and buffering delay.

## Decision

### Node-local time is authoritative; the wire is unchanged

`t_node_us` stays exactly as specified: the node's own clock, uncorrected, microseconds,
first-sample-of-block. Nodes never see a global clock and never rewrite their timestamps.
This keeps firmware trivial (read a local timer), preserves true sample cadence, and keeps
the high-rate data plane free of any sync handshake.

### A global timeline is reconstructed at the ground station, per node

The ground station maintains, **per node**, a small `ClockModel` that fits the node's
clock against the reference clock — regressing node time *on* reference time so the slope
is sign-correct against the injected drift:

```
t_node_us ≈ skew * t_ref_us + offset
```

`skew` is the node's tick rate relative to the reference, so `(skew - 1) * 1e6` recovers
the node's drift in ppm — exactly the `drift_ppm` the synthetic node injects, which gives
us a built-in test oracle. `offset` places the node's epoch against the reference epoch.

- **Reference clock:** the ground station's own monotonic clock, sampled at packet
  arrival. (Disciplining that reference to absolute UTC/GPS is explicitly out of scope
  here — see Non-goals.)
- **Fit:** an online least-squares fit (Welford streaming covariance, O(1) per packet)
  over matched `(t_node_us, arrival_ref_us)` pairs, one pair per received packet. Arrival
  time is a *noisy anchor*, not a timestamp: least squares averages transport jitter and
  buffering out, so the slope stays unbiased; jitter only widens the estimate's confidence
  interval. Packet loss does not bias it because we regress on the pairs we actually have,
  never on counts or gaps. (A robust fit — Theil–Sen / IRLS — is a drop-in upgrade if
  asymmetric outliers ever need rejecting; OLS suffices for the symmetric jitter here.)
- **Use:** a sample's global time is `ClockModel.to_ref(packet.sample_time_us(i))`, the
  inverse of the fit. The node's own `t_node_us` is preserved alongside it; the global
  time is a derived column, never an overwrite.

### Why not the two extremes

| Option | Why not |
|---|---|
| **Node time, raw, as the only timeline** | True per-node cadence, but cross-node data can never be aligned and there is no absolute reference — punts the inter-node job entirely. |
| **Ground-station arrival time authoritative** | One clock, trivially comparable, but arrival time *is* corrupted by jitter, buffering, and reorder; it destroys real sample cadence and a single late/dropped packet skews it. Arrival time is a poor proxy for sample time. |
| **Hybrid (this ADR)** | Keeps node time for what only the node knows (cadence), and derives a common timeline at the one place with a stable reference and the full cross-node view. |

## Non-goals (deferred)

- **Absolute time (UTC/GPS/PTP discipline).** The reference is a free-running
  ground-station clock for now. A future GPS/PTP discipline, or a `HEARTBEAT` sync beacon
  on the reserved control plane, can pin it to absolute time without changing this ADR.
- **On-node correction / clock steering.** Nodes stay dumb; all correction is downstream.
- **Sub-microsecond alignment.** `t_node_us` resolution is 1 µs; that bounds achievable
  alignment and is sufficient for the accelerometer rates in scope.

## Consequences

**Positive**

- No wire-format or firmware change; the data plane carries no sync traffic.
- Cross-node alignment becomes possible the moment the model converges, and the recovered
  ppm is directly checkable against the simulator's injected `drift_ppm`.
- Jitter and loss degrade the *estimate's* accuracy gracefully, never corrupt the stored
  node timestamps.

**Costs**

- The ground station gains per-node clock state and a convergence period before alignment
  is trustworthy.
- "Global time" is an estimate with a confidence interval, not an exact value — downstream
  consumers must treat it as such.

## Outcome (implemented 2026-07-02)

- `ClockModel` (skew + offset, online least-squares fit) lives at
  `src/wiredaq/ground_station/timing/clock_model.py`, held per node by the `Collector`
  (`NodeStats.clock`), updated once per received frame from `(t_node_us, arrival_ref_us)`.
- **Oracle passes** (`tests/test_clock_model.py`): two `SyntheticNode`s with distinct
  injected `drift_ppm` are recovered within **< 0.5 ppm**; `±300 µs` arrival jitter widens
  the ppm standard error ~250× (≈0.004 → ≈0.95 ppm) while the estimate stays within a few
  ppm — unbiased, wider interval, exactly as decided; dropping ~1/3 of packets leaves the
  estimate unbiased.
- `wiredaq-clocksync` (`src/wiredaq/cli/clocksync.py`) demos it: nodes whose raw clocks
  differ by ~1200 µs are reconstructed onto one reference timeline within 0 µs (clean) /
  tens of µs (jittered), with recovered-vs-injected ppm printed per node.

## Still deferred

- Surfacing the derived `t_ref_us` per sample in the CSV/other sinks (the model is computed
  and available on `NodeStats.clock`; the sink columns are not wired yet).
- Robust (outlier-rejecting) fit, and absolute-time discipline — see Non-goals above.
