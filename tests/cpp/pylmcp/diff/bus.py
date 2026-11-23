"""ZeroMQ transports (imported lazily; zmq is only needed for live runs).

``ClientBus`` -- C++ ``uxas`` owns the PublishPull bridge sockets, the
harness connects SUB + PUSH to it (what ``pylmcp.server.Server`` does).

``HubBus`` -- ``uxas_ada`` *connects* to the bridge addresses, so the harness
binds XPUB + PULL and relays PULL -> PUB exactly as the C++ bridge does, so
that Ada services can see each other's messages.

Both expose the same tiny interface (``Bus``) used by the runner.
"""
from __future__ import annotations

from typing import List


class Bus:
    def open(self) -> None: ...
    def inject(self, frame: bytes) -> None: ...
    def poll(self) -> List[bytes]:
        """Non-blocking: frames observed since the previous call."""
        raise NotImplementedError
    def subscribers_seen(self) -> int:
        """Number of subscription events seen (hub only); -1 if unknown."""
        return -1
    def close(self) -> None: ...


class ClientBus(Bus):
    def __init__(self, sub_url: str, push_url: str) -> None:
        self.sub_url, self.push_url = sub_url, push_url
        self.ctx = self.sub = self.push = None

    def open(self) -> None:
        import zmq
        self.ctx = zmq.Context()
        self.sub = self.ctx.socket(zmq.SUB)
        self.sub.connect(self.sub_url)
        self.sub.setsockopt(zmq.SUBSCRIBE, b"")
        self.push = self.ctx.socket(zmq.PUSH)
        self.push.connect(self.push_url)

    def inject(self, frame: bytes) -> None:
        self.push.send(frame)

    def poll(self) -> List[bytes]:
        import zmq
        out = []
        if self.sub is None:       # not opened yet (startup wait)
            return out
        while True:
            try:
                out.append(self.sub.recv(zmq.NOBLOCK))
            except zmq.Again:
                return out

    def close(self) -> None:
        for s in (self.sub, self.push):
            if s is not None:
                s.close(linger=0)
        if self.ctx is not None:
            self.ctx.term()


class HubBus(Bus):
    def __init__(self, pub_url: str, pull_url: str) -> None:
        self.pub_url, self.pull_url = pub_url, pull_url
        self.ctx = self.pub = self.pull = None
        self._subs = 0

    def open(self) -> None:
        import zmq
        self.ctx = zmq.Context()
        self.pub = self.ctx.socket(zmq.XPUB)
        self.pub.bind(self.pub_url)
        self.pull = self.ctx.socket(zmq.PULL)
        self.pull.bind(self.pull_url)

    def inject(self, frame: bytes) -> None:
        self.pub.send(frame)

    def _drain_subscriptions(self) -> None:
        import zmq
        while True:
            try:
                ev = self.pub.recv(zmq.NOBLOCK)
            except zmq.Again:
                return
            if ev[:1] == b"\x01":
                self._subs += 1

    def subscribers_seen(self) -> int:
        self._drain_subscriptions()
        return self._subs

    def poll(self) -> List[bytes]:
        import zmq
        out = []
        if self.pub is None:
            return out
        self._drain_subscriptions()
        while True:
            try:
                f = self.pull.recv(zmq.NOBLOCK)
            except zmq.Again:
                return out
            self.pub.send(f)          # relay like the C++ bridge does
            out.append(f)

    def close(self) -> None:
        for s in (self.pub, self.pull):
            if s is not None:
                s.close(linger=0)
        if self.ctx is not None:
            self.ctx.term()
