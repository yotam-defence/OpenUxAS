"""Golden-file cache for reference (Ada) captures."""
import json
import os
import time

SCHEMA = 1


class GoldenError(Exception):
    pass


def golden_path(golden_dir: str, scenario_name: str, impl: str = "ada") -> str:
    return os.path.join(golden_dir, "%s.%s.golden.json" % (scenario_name, impl))


BOOTSTRAP_NOTE = ("BOOTSTRAP golden: recorded from the C++ binary (obj/cpp/uxas), "
                  "NOT from uxas_ada, because no Ada toolchain was available. "
                  "It only guards C++ against regressions; re-record it from "
                  "uxas_ada with --record-golden when Ada is available.")


def save(path, scenario, impl, records, source=None):
    """Store a capture. ``impl`` is the role (always "ada": the reference);
    ``source`` is the implementation that actually produced the capture
    (default: same as ``impl``). source != "ada" marks a bootstrap golden."""
    source = source or impl
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    doc = {"schema": SCHEMA, "scenario": scenario.name, "impl": impl,
           "source_impl": source, "bootstrap": source != impl,
           "note": BOOTSTRAP_NOTE if source != impl else
                   "recorded from the Ada reference implementation",
           "fingerprint": scenario.fingerprint(),
           "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "records": records}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fd:
        json.dump(doc, fd, indent=1, sort_keys=True)
        fd.write("\n")
    os.replace(tmp, path)


def load(path, scenario, allow_stale=False):
    return load_doc(path, scenario, allow_stale)["records"]


def load_doc(path, scenario, allow_stale=False):
    """Like load() but return the whole document (records + metadata)."""
    try:
        with open(path, "r", encoding="utf-8") as fd:
            doc = json.load(fd)
    except OSError as e:
        raise GoldenError("cannot read golden file %s: %s (record it with "
                          "--record-golden)" % (path, e))
    except json.JSONDecodeError as e:
        raise GoldenError("golden file %s is corrupt: %s" % (path, e))
    if doc.get("schema") != SCHEMA:
        raise GoldenError("golden %s has unsupported schema %r"
                          % (path, doc.get("schema")))
    if doc.get("fingerprint") != scenario.fingerprint() and not allow_stale:
        raise GoldenError(
            "golden %s is stale: scenario changed since it was recorded "
            "(re-record with --record-golden or pass --allow-stale-golden)"
            % path)
    return doc
