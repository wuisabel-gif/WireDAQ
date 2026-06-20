# 2. Clock domain: node-local time authoritative, corrected at the ground station

- **Status:** Proposed
- **Date:** 2026-06-20
- **Deciders:** _(awaiting sign-off)_
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

The ground station maintains, **per node**, a small `ClockModel` estimating an offset `b`
and a rate ratio `m` such that

```
t_ref ≈ m * t_node_us + b
```

`m` is the node's drift relative to the reference (so `m - 1` recovers the node's ppm —
exactly the `drift_ppm` the synthetic node injects, which gives us a built-in test
oracle), and `b` is the offset between the node's epoch and the reference epoch.

- **Reference clock:** the ground station's own monotonic clock, sampled at packet
  arrival. (Disciplining that reference to absolute UTC/GPS is explicitly out of scope
  here — see Non-goals.)
- **Fit:** online robust linear regression over matched `(t_node_us, arrival_ref_us)`
  pairs, one pair per received packet. Arrival time is a *noisy anchor*, not a timestamp:
  the regression smooths transport jitter and buffering, and packet loss does not bias it
  because we regress on the pairs we actually have, never on counts or gaps.
- **Use:** a sample's global time is `ClockModel.to_ref(packet.sample_time_us(i))`. The
  node's own `t_node_us` is preserved alongside it; the global time is a derived column,
  never an overwrite.

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

## Implementation notes (follow-on, not part of this decision)

- Add a `ClockModel` (offset + skew, online robust fit) under `src/wiredaq/ground_station/`, held
  per node by the `Collector` or a dedicated timing component.
- Test oracle: drive two `SyntheticNode`s with known, distinct `drift_ppm`; assert the
  fitted `m - 1` recovers each ppm within tolerance, and that loss/jitter widen the
  interval without biasing the estimate.
- Surface, per node, both `t_node_us` and the derived `t_ref_us` (with a quality metric)
  on the `Packet` / in the sinks.
