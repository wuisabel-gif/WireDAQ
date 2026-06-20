"""
InProcessTransport — a perfect, zero-impairment in-process link (Phase 1).

A FIFO queue of frames. This is the *baseline* transport: it never loses, reorders, or
corrupts anything. To make the simulator honest, wrap it in
:class:`~tools.daq_sim.transports.impairment_transport.ImpairmentTransport`.
"""

from __future__ import annotations

from collections import deque
from typing import Optional

from wiredaq.daq_sim.core.interfaces import Transport


class InProcessTransport(Transport):
    """A loss-free FIFO link between a sender and a receiver in the same process."""

    def __init__(self) -> None:
        self._queue: "deque[bytes]" = deque()

    def send(self, frame: bytes) -> None:
        self._queue.append(bytes(frame))

    def recv(self) -> Optional[bytes]:
        if not self._queue:
            return None
        return self._queue.popleft()

    def __len__(self) -> int:
        return len(self._queue)
