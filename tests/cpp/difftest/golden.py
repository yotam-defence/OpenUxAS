"""Golden-file cache for reference (Ada) captures."""
import json
import os
import time

SCHEMA = 1


class GoldenError(Exception):
    pass


def golden_path(golden_dir: str, scenario_name: str, impl: str = "ada") -> str:
    return os.path.join(golden_dir, "%s.%s.golden.json" % (scenario_name, impl))


def save(path, scenario, impl, records):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    doc = {"schema": SCHEMA, "scenario": scenario.name, "impl": impl,
           "fingerprint": scenario.fingerprint(),
           "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "records": records}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fd:
        json.dump(doc, fd, indent=1, sort_keys=True)
        fd.write("\n")
    os.replace(tmp, path)


def load(path, scenario, allow_stale=False):
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
    return doc["records"]
