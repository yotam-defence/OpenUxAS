"""uxas_diff: Ada-vs-C++ differential replay harness for OpenUxAS.

Importing this package never imports zmq or pylmcp; those are loaded lazily
by the capture layer so the canonicaliser, comparators and diff engine are
usable (and unit-testable) with no binaries and no ZeroMQ.
"""

__version__ = "1.0"
