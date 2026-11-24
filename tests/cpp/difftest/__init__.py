"""Differential replay harness: Ada ``uxas_ada`` vs C++ ``uxas``.

Pure-python modules (scenario, normalise, comparators, golden, report) have no
third party dependency. ``pyzmq`` and ``pylmcp`` are imported lazily, only when
a scenario is actually replayed or LMCP objects are encoded/decoded.
"""

__version__ = "0.1.0"

# Exit codes of ``python3 -m difftest``
EXIT_MATCH = 0
EXIT_DIFF = 1
EXIT_USAGE = 2
EXIT_INFRA = 3
