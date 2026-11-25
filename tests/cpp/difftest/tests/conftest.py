import os
import sys

# Make the ``difftest`` package importable (it lives in tests/cpp) even when
# pytest runs in isolated mode.  pylmcp/zmq/e3 are NOT needed by these tests.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                "..", "..")))
