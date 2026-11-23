from helpers import *  # noqa
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "run_differential.py")


def run_cli(*args):
    return subprocess.run([sys.executable, "-I", CLI] + list(args),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True, timeout=120)


def test_list_comparators():
    r = run_cli("--list-comparators")
    assert r.returncode == 0
    assert "default" in r.stdout and "heartbeat" in r.stdout


def test_usage_errors():
    assert run_cli().returncode == 2
    assert run_cli("/nonexistent.json").returncode == 2
    assert run_cli("--list-comparators", "--plugin", "/nonexistent.py").returncode == 2


def test_missing_binaries_exit_3_without_executing_anything():
    sc = os.path.join(ROOT, "scenarios", "heartbeat.json")
    with tempfile.TemporaryDirectory() as d:
        env_args = ["--cpp-bin", "/nonexistent/uxas",
                    "--ada-bin", "/nonexistent/uxas_ada", "--workdir", d]
        r = run_cli(sc, *env_args)
    assert r.returncode == 3, (r.stdout, r.stderr)
    assert "not found" in r.stderr or "pyzmq" in r.stderr


def test_missing_golden_exit_4():
    sc = os.path.join(ROOT, "scenarios", "heartbeat.json")
    r = run_cli(sc, "--golden", "/nonexistent/g.json")
    assert r.returncode == 4
