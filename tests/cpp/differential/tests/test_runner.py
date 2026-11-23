from helpers import *  # noqa
import json
import os
import tempfile
from uxdiff import runner
from uxdiff.backends import FakeBackend, RunError


def factory(**per_side):
    def f(side):
        return per_side.get(side) or FakeBackend(side)
    return f


def test_fake_run_schedule_and_capture():
    sc = make_scenario(3)
    be = FakeBackend("cpp")
    res = runner.finish(sc, runner.run_side(sc, be))
    assert res.ok and be.stopped and len(be.sent) == 3
    assert len(res.records) == 3
    assert [c.step for c in res.captured] == [1, 2, 3]
    assert be.now == 3 * 5 + 10  # virtual clock: delays + settle


def test_identical_sides_match_even_with_reordering():
    sc = make_scenario(4)
    rep = runner.run_differential(sc, factory(
        cpp=FakeBackend("cpp", jitter_reverse=True)))
    assert rep.exit_code == runner.EXIT_MATCH and rep.report.equal


def test_difference_detected_and_reported_as_json():
    sc = make_scenario(2)

    def extra(env, t):
        return [kvp_raw("heartbeat", "extra")]
    rep = runner.run_differential(sc, factory(
        cpp=FakeBackend("cpp", behaviour=extra)))
    assert rep.exit_code == runner.EXIT_DIFF
    d = rep.as_dict()
    assert d["report"]["differences"][0]["kind"] == "extra"
    json.dumps(d)


def test_crash_and_missing_binary_and_timeout_kinds():
    sc = make_scenario(3)
    rep = runner.run_differential(sc, factory(
        cpp=FakeBackend("cpp", crash_at_ms=7)))
    assert rep.exit_code == runner.EXIT_RUN_FAILURE
    assert rep.sides["cpp"].error.kind == "crash"
    rep = runner.run_differential(sc, factory(
        ada=FakeBackend("ada", fail_start="no uxas_ada")))
    assert rep.exit_code == runner.EXIT_RUN_FAILURE
    assert rep.sides["ada"].error.kind == "missing"

    class Slow(FakeBackend):
        def wait(self, ms):
            raise RunError("scenario timeout", "timeout")
    rep = runner.run_differential(sc, factory(cpp=Slow("cpp")))
    assert rep.sides["cpp"].error.kind == "timeout"
    assert rep.sides["cpp"].return_codes  # backend still stopped


def test_unclean_exit_is_failure():
    class Unclean(FakeBackend):
        def stop(self):
            return {"uxas": {"rc": 139, "was_running": True, "clean": False}}
    sc = make_scenario(1)
    res = runner.run_side(sc, Unclean("cpp"))
    assert res.error is not None and res.error.kind == "crash"


def test_golden_record_and_use():
    sc = make_scenario(3)
    with tempfile.TemporaryDirectory() as d:
        g = os.path.join(d, "g.json")
        rep = runner.run_differential(sc, factory(), record_golden=g,
                                      record_only=True)
        assert rep.exit_code == 0 and rep.report is None
        # Ada unavailable now: only the candidate runs.
        rep = runner.run_differential(sc, factory(
            ada=FakeBackend("ada", fail_start="no ada")), golden=g)
        assert rep.exit_code == runner.EXIT_MATCH
        assert rep.sides["ada"].from_golden
        # candidate regression is caught against golden
        rep = runner.run_differential(sc, factory(
            cpp=FakeBackend("cpp", echo=False)), golden=g)
        assert rep.exit_code == runner.EXIT_DIFF


def test_golden_record_then_compare_in_one_run():
    sc = make_scenario(2)
    with tempfile.TemporaryDirectory() as d:
        g = os.path.join(d, "g.json")
        rep = runner.run_differential(sc, factory(), record_golden=g)
        assert rep.exit_code == 0 and rep.report.equal and os.path.exists(g)


def test_golden_errors_stale_wrong_scenario_corrupt():
    sc = make_scenario(2)
    with tempfile.TemporaryDirectory() as d:
        g = os.path.join(d, "g.json")
        runner.run_differential(sc, factory(), record_golden=g, record_only=True)
        stale = make_scenario(3)
        rep = runner.run_differential(stale, factory(), golden=g)
        assert rep.exit_code == runner.EXIT_GOLDEN
        rep = runner.run_differential(stale, factory(), golden=g,
                                      ignore_golden_digest=True)
        assert rep.exit_code in (0, 1)
        other = make_scenario(2, name="other")
        assert runner.run_differential(other, factory(),
                                       golden=g).exit_code == runner.EXIT_GOLDEN
        with open(g, "w") as fd:
            fd.write("garbage")
        assert runner.run_differential(sc, factory(),
                                       golden=g).exit_code == runner.EXIT_GOLDEN
        assert runner.run_differential(
            sc, factory(), golden=os.path.join(d, "none")).exit_code == \
            runner.EXIT_GOLDEN


def test_record_golden_failure_does_not_write_file():
    sc = make_scenario(1)
    with tempfile.TemporaryDirectory() as d:
        g = os.path.join(d, "g.json")
        rep = runner.run_differential(sc, factory(
            ada=FakeBackend("ada", fail_start="x")), record_golden=g)
        assert rep.exit_code == runner.EXIT_RUN_FAILURE
        assert not os.path.exists(g)


def test_exclude_echo_option():
    sc = make_scenario(2, capture={"exclude_echo": True})
    res = runner.finish(sc, runner.run_side(sc, FakeBackend("cpp")))
    assert res.records == []


def test_cpp_only_passes_and_never_claims_parity():
    sc = make_scenario(3)
    out = runner.run_cpp_only(sc, factory())
    assert out.exit_code == runner.EXIT_MATCH
    assert out.parity_checked is False
    assert out.as_dict()["parity_checked"] is False
    assert len(out.sides) == 2


def test_cpp_only_detects_nondeterminism():
    sc = make_scenario(2)
    n = []

    def f(side):
        n.append(1)
        beh = (lambda env, t: [kvp_raw("heartbeat", "odd")]) if len(n) == 2 else None
        return FakeBackend(side, behaviour=beh)
    out = runner.run_cpp_only(sc, f)
    assert out.exit_code == runner.EXIT_DIFF
    assert any("deterministic" in m for m in out.messages)


def test_cpp_only_fails_on_empty_capture():
    sc = make_scenario(2)
    out = runner.run_cpp_only(sc, lambda side: FakeBackend(side, echo=False))
    assert out.exit_code == runner.EXIT_DIFF
    assert any("no messages" in m for m in out.messages)


def test_cpp_only_fails_on_malformed_capture():
    sc = make_scenario(2)
    out = runner.run_cpp_only(sc, lambda side: FakeBackend(
        side, behaviour=lambda env, t: [b"garbage"]))
    assert out.exit_code == runner.EXIT_DIFF
    assert any("malformed" in m for m in out.messages)


def test_cpp_only_crash_is_run_failure():
    sc = make_scenario(3)
    out = runner.run_cpp_only(sc, lambda s: FakeBackend(s, crash_at_ms=7))
    assert out.exit_code == runner.EXIT_RUN_FAILURE
