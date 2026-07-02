"""
CsvLogger reconstructed-timeline column (ADR 0002).

With a clock_lookup the logger adds a `t_ref_us` column mapping each sample's node-local
time onto the reference timeline; without one it stays exactly as before (no column).

    python3 tests/test_csv_timeline.py
    pytest tests/test_csv_timeline.py
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wiredaq.daq_sim.sinks.csv_logger import CsvLogger  # noqa: E402
from wiredaq.ground_station.timing import ClockModel  # noqa: E402
from wiredaq.protocol.codec import decode, encode_sample_block  # noqa: E402


def _packet(node_id, t_node_us, rate, samples):
    frame = encode_sample_block(
        node_id=node_id, seq=0, t_node_us=t_node_us, sample_rate_hz=rate,
        channel_count=len(samples[0]), samples=samples,
    )
    return decode(frame)


def test_csv_writes_reconstructed_reference_time(tmp_path):
    # A converged model where the node clock runs at exactly 2x the reference (skew 2),
    # so to_ref halves the node time — an unmistakable, checkable mapping.
    cm = ClockModel(1)
    for k in range(1, 20):
        cm.update(t_node_us=2000 * k, t_ref_us=1000 * k)
    assert cm.ready and abs(cm.skew - 2.0) < 1e-6

    path = tmp_path / "s.csv"
    logger = CsvLogger(str(path), max_channels=2, clock_lookup=lambda nid: cm if nid == 1 else None)
    logger.consume(_packet(1, t_node_us=2000, rate=1000, samples=[[5], [6]]))
    logger.close()

    rows = list(csv.reader(path.open()))
    assert rows[0] == ["node_id", "seq", "sample_index", "t_sample_us", "t_ref_us", "ch0", "ch1"]
    # sample 0: t_node 2000 -> to_ref 1000; sample 1: +1000us cadence -> 3000 -> to_ref 1500
    assert rows[1][3] == "2000" and rows[1][4] == "1000"
    assert rows[2][3] == "3000" and rows[2][4] == "1500"


def test_csv_blank_ref_before_model_ready(tmp_path):
    cm = ClockModel(1)  # no updates -> not ready
    path = tmp_path / "s.csv"
    logger = CsvLogger(str(path), max_channels=1, clock_lookup=lambda nid: cm)
    logger.consume(_packet(1, t_node_us=500, rate=1000, samples=[[7]]))
    logger.close()
    rows = list(csv.reader(path.open()))
    assert "t_ref_us" in rows[0]
    assert rows[1][4] == ""  # blank until the fit converges


def test_csv_without_lookup_is_unchanged(tmp_path):
    path = tmp_path / "s.csv"
    logger = CsvLogger(str(path), max_channels=2)  # no clock_lookup
    logger.consume(_packet(1, t_node_us=0, rate=1000, samples=[[1, 2]]))
    logger.close()
    rows = list(csv.reader(path.open()))
    assert rows[0] == ["node_id", "seq", "sample_index", "t_sample_us", "ch0", "ch1"]


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        test_csv_writes_reconstructed_reference_time(Path(d))
    with tempfile.TemporaryDirectory() as d:
        test_csv_blank_ref_before_model_ready(Path(d))
    with tempfile.TemporaryDirectory() as d:
        test_csv_without_lookup_is_unchanged(Path(d))
    print("csv timeline column: all checks pass")
