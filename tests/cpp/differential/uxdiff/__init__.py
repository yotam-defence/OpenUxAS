"""Ada-vs-C++ UxAS differential replay harness.

Public API (stable, consumed by later milestones):

* :func:`uxdiff.comparators.register_comparator` -- plug-in registration
* :class:`uxdiff.comparators.Comparator` -- comparator base class
* :func:`uxdiff.scenario.load_scenario`
* :func:`uxdiff.runner.run_differential`
"""

__version__ = "1.0.0"
