"""
ReplayNode — replays a recorded capture as a live source (ADR 0001 SensorNode adapter).

The mirror image of :class:`~ground_station.logger.raw_logger.RawFrameLogger`: it reads a
length-prefixed raw log back and emits the frames exactly as captured, behind the same
:class:`SensorNode` port a synthetic node or a real board sits behind. That makes a
recorded session a drop-in stand-in for live hardware — replay a real capture through the
exact same receiver / collector / sinks to reproduce a bug, regression-test a decoder
change, or drive the dashboard from field data.

Because a capture may contain frames from several nodes, ``node_id`` here is just a label
for the source; each frame carries its own node id, which is what the collector keys on.
"""

from __future__ import annotations

from typing import List, Optional

from wiredaq.ground_station.logger.raw_logger import read_raw_log
from wiredaq.daq_sim.core.interfaces import SensorNode


class ReplayNode(SensorNode):
    """Replays frames from a raw capture log, in order."""

    def __init__(self, path: str, node_id: int = 0) -> None:
        self.node_id = node_id
        self.path = path
        self._frames: List[bytes] = list(read_raw_log(path))
        self._index = 0

    def __len__(self) -> int:
        return len(self._frames)

    def next_frame(self) -> Optional[bytes]:
        if self._index >= len(self._frames):
            return None
        frame = self._frames[self._index]
        self._index += 1
        return frame
