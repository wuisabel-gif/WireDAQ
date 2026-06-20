"""Put `src/` on sys.path so `import wiredaq` resolves when running the tests from a
checkout that hasn't been `pip install`-ed (editable install also works and takes
precedence). Lets `pytest` and plain `python3 tests/test_*.py` both find the package."""

import sys
from pathlib import Path

_SRC = str(Path(__file__).resolve().parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
