"""Shared ground-station receivers.

* :class:`FrameReceiver` — for datagram transports (UDP, in-process), where each read is
  already one whole frame.
* :class:`StreamReceiver` — for byte-stream transports (serial / RS-485), where frame
  boundaries must be found via the magic sync word.

Both satisfy the :class:`Receiver` port and yield the same :class:`~protocol.codec.Packet`
objects, so the Collector is identical regardless of link type.
"""

from wiredaq.ground_station.receiver.frame_receiver import FrameReceiver, ReceiverStats  # noqa: F401
from wiredaq.ground_station.receiver.stream_receiver import (  # noqa: F401
    StreamReceiver,
    StreamReceiverStats,
)

__all__ = ["FrameReceiver", "ReceiverStats", "StreamReceiver", "StreamReceiverStats"]
