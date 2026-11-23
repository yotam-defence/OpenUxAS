from __future__ import annotations

from e3.anod.loader import AnodSpecRepository
from e3.anod.context import AnodContext
from e3.anod.sandbox import SandBox
from e3.os.process import Run

import logging
import os
import sys


def check_tool(tool: str) -> str:
    """Check tool version and return its version.

    The function will force exit if the tool is not found.

    :param tool: tool name
    :type tool: str
    :return: the tool version
    :rtype: str
    """
    try:
        p = Run([tool, "--version"])
        version = p.out.splitlines()[0]
        logging.info("%s version: %s", tool, version)
        return version
    except Exception:
        logging.critical("cannot find %s", tool)
        sys.exit(1)


MIN_GCC_MAJOR = 11  # OpenUxAS C++ is built with -std=c++17


def check_gcc_min_version() -> None:
    """Ensure gcc is recent enough for the C++17 build (GCC 11+)."""
    try:
        p = Run(["gcc", "-dumpversion"])
        major = int(p.out.strip().split(".")[0])
    except Exception:
        logging.warning("cannot determine gcc major version")
        return
    if major < MIN_GCC_MAJOR:
        logging.critical(
            "gcc %d found, but gcc >= %d is required (C++17)",
            major, MIN_GCC_MAJOR)
        sys.exit(1)


def check_common_tools() -> None:
    # The following variables are used to force recompilation
    # in case of some tool change.
    gcc_version = check_tool("gcc")
    check_gcc_min_version()
    os.environ["OPENUXAS_COMPILER_VERSION"] = gcc_version
    cmake_version = check_tool("cmake")
    os.environ["OPENUXAS_CMAKE_VERSION"] = cmake_version
    check_tool("pkg-config")


def create_anod_context(spec_dir: str) -> AnodContext:
    return AnodContext(AnodSpecRepository(spec_dir))


def create_anod_sandbox(sbx_dir: str, spec_dir: str) -> SandBox:
    sbx = SandBox(sbx_dir)
    sbx.specs_dir = spec_dir

    return sbx
