"""Ada-vs-C++ differential replay harness for OpenUxAS.

Pure-python modules (scenario, canon, comparators, golden, report) have no
third-party dependency so they can be unit tested without either binary.
Only ``runner`` needs pyzmq and ``pylmcp`` (lazily imported).
"""

__version__ = "0.1.0"
