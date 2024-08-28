"""Provide class to manage status callbacks."""
from typing import Callable


def NOP():
    """Do nothing."""
    return None


class StatusCB:
    """Callbacks for displaying a status line during long operations."""

    def __init__(self,
                 start: Callable[[], None] = NOP,
                 stop: Callable[[], None] = NOP
                 ):
        """Specify the start and stop callables."""
        self._start = staticmethod(start)
        self._stop = staticmethod(stop)

    def start(self):
        """Call start function."""
        self._start()

    def stop(self):
        """Call stop function."""
        self._stop()
