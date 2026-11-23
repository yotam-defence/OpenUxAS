"""Fakes for exercising the harness without binaries or ZeroMQ.

Example::

    ctx = RunContext(binaries={"ada": "x", "cpp": "x"},
                     launcher=FakeLauncher(),
                     bus_factory=lambda side, sc: FakeBus(echo=True),
                     sleep=clock.sleep, clock=clock)
"""
from __future__ import annotations

from typing import Callable, List, Optional

from .bus import Bus
from .process import ManagedProcess


class FakeClock:
    """Virtual time: ``sleep`` advances ``now`` instantly."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.now += s


class FakeProcess(ManagedProcess):
    def __init__(self, argv, die_immediately: bool = False,
                 output: str = "") -> None:
        self.argv = argv
        self.running = not die_immediately
        self.output = output
        self.stopped = False

    def alive(self) -> bool:
        return self.running

    def stop(self, timeout_s: float = 3.0) -> Optional[int]:
        self.running = False
        self.stopped = True
        return 0

    def log_tail(self, lines: int = 20) -> str:
        return self.output


class FakeLauncher:
    def __init__(self, die_immediately: bool = False) -> None:
        self.started: List[FakeProcess] = []
        self.die_immediately = die_immediately

    def start(self, argv, cwd, log_path) -> FakeProcess:
        p = FakeProcess(argv, self.die_immediately,
                        output="fake log for %s" % argv[0])
        self.started.append(p)
        return p


class FakeBus(Bus):
    """In-memory bus.

    ``responder(frame) -> list[bytes]`` produces the 'implementation'
    output for every injected frame; ``echo=True`` additionally echoes the
    injected frame like the C++ PublishPull bridge does.
    """

    def __init__(self, responder: Optional[Callable] = None,
                 echo: bool = False, subscribers: int = 1) -> None:
        self.responder = responder
        self.echo = echo
        self.subscribers = subscribers
        self.queue: List[bytes] = []
        self.injected: List[bytes] = []
        self.opened = self.closed = False

    def open(self) -> None:
        self.opened = True

    def inject(self, frame: bytes) -> None:
        self.injected.append(frame)
        if self.echo:
            self.queue.append(frame)
        if self.responder:
            self.queue.extend(self.responder(frame))

    def poll(self) -> List[bytes]:
        out, self.queue = self.queue, []
        return out

    def subscribers_seen(self) -> int:
        return self.subscribers

    def close(self) -> None:
        self.closed = True
