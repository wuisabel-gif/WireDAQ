"""Anchor the repo root on sys.path so `protocol`, `tools`, and `ground_station` import
as namespace packages under both pytest and plain `python3` invocations."""

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
