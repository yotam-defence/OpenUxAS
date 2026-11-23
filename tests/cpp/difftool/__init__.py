"""Ada-vs-C++ differential replay harness for OpenUxAS.

Core modules use the standard library only.  ``pylmcp`` and ``zmq`` are
imported lazily by :mod:`difftool.live` when a live replay is requested.
"""

__version__ = "1.0"

# Process exit codes (see README.md)
EXIT_MATCH = 0
EXIT_DIFF = 1
EXIT_USAGE = 2
EXIT_INFRA = 3
EXIT_GOLDEN = 4
