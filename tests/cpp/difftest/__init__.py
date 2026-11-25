"""Differential replay harness: Ada reference ``uxas_ada`` vs C++ ``uxas``.

The harness replays a recorded LMCP message sequence (a *scenario*) against
each implementation over ZeroMQ, captures what each one publishes, normalises
the decoded messages and diffs the result.  See README.md.
"""

__version__ = "1.0"

# Process exit codes of ``python -m difftest``
EXIT_OK = 0          # all windows match
EXIT_MISMATCH = 1    # at least one difference found
EXIT_ERROR = 2       # usage / configuration / infrastructure problem

# Implementation names
ADA = "ada"
CPP = "cpp"
