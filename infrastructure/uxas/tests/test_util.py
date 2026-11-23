"""Unit tests for uxas.anod.util.check_gcc_version (no e3 install needed)."""
import importlib.util
import logging
import os
import sys
import types

import pytest

UTIL_PATH = os.path.join(
    os.path.dirname(__file__), "..", "src", "uxas", "anod", "util.py"
)


def _load_util():
    """Import util.py with the e3 modules it needs stubbed out."""
    for name, attr in (
        ("e3.anod.loader", "AnodSpecRepository"),
        ("e3.anod.context", "AnodContext"),
        ("e3.anod.sandbox", "SandBox"),
        ("e3.os.process", "Run"),
    ):
        mod = types.ModuleType(name)
        setattr(mod, attr, object)
        sys.modules.setdefault(name, mod)
    spec = importlib.util.spec_from_file_location("uxas_anod_util", UTIL_PATH)
    util = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(util)
    return util


util = _load_util()


@pytest.mark.parametrize(
    "line",
    [
        "gcc (Ubuntu 11.4.0-1ubuntu1~22.04) 11.4.0",
        "gcc (Ubuntu 13.2.0-23ubuntu4) 13.2.0",
        "gcc (Debian 12.2.0-14) 12.2.0",
        "gcc (GCC) 11.2.1 20220127 (Red Hat 11.2.1-9)",
    ],
)
def test_accepts_supported_gcc(line):
    util.check_gcc_version(line)


@pytest.mark.parametrize(
    "line",
    [
        "gcc (Ubuntu 9.4.0-1ubuntu1~20.04.2) 9.4.0",
        "gcc (GCC) 4.8.5 20150623 (Red Hat 4.8.5-44)",
    ],
)
def test_rejects_old_gcc(line, caplog):
    with caplog.at_level(logging.CRITICAL):
        with pytest.raises(SystemExit) as exc:
            util.check_gcc_version(line)
    assert exc.value.code == 1
    assert "required" in caplog.text


def test_custom_minimum():
    util.check_gcc_version("gcc (GCC) 12.1.0", minimum=12)
    with pytest.raises(SystemExit):
        util.check_gcc_version("gcc (GCC) 12.1.0", minimum=13)


def test_clang_is_accepted():
    util.check_gcc_version("Apple clang version 14.0.3 (clang-1403.0.22.14.1)")


def test_unparseable_version_warns(caplog):
    with caplog.at_level(logging.WARNING):
        util.check_gcc_version("something unexpected")
    assert "cannot parse" in caplog.text
