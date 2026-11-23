"""Differential replay harness: Ada reference ``uxas_ada`` versus C++ ``uxas``.

The package is deliberately importable without ZeroMQ, e3 or the UxAS
binaries: only the live runner (``bus.py``/``process.py``) needs them, and it
imports them lazily.  See README.md in this directory for the user guide.
"""

SCENARIO_FORMAT_VERSION = 1
SIDES = ("ada", "cpp")
