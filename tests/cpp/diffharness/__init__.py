"""Ada-vs-C++ differential replay harness for OpenUxAS.

See README.md in this directory.  Heavy dependencies (pyzmq, pylmcp which
needs e3, PyYAML) are imported lazily so that the normaliser, comparators,
diff and scenario loader can be used and unit-tested without them.
"""

__version__ = "1.0"
