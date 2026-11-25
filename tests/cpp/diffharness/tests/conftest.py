import os
import sys

# make `diffharness` importable when pytest is run from anywhere
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
