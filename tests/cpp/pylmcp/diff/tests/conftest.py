import os
import sys

# tests/cpp must be importable so that ``pylmcp.diff`` resolves.
sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")))
