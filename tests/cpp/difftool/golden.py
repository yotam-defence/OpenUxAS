"""Golden-file cache of Ada reference outputs.

The Ada toolchain (Alire/GNAT) is often unavailable, so the raw captured
Ada output is stored once and later compared against fresh C++ output.
Raw (pre-normalisation) captures are stored so normalisation rules can
evolve without re-recording.
"""
import json
import os
import re

FORMAT = 1


class GoldenError(Exception):
    pass


class GoldenMissing(GoldenError):
    pass


class GoldenStale(GoldenError):
    pass


def golden_path(directory, scenario_name):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", scenario_name)
    return os.path.join(directory, safe + ".ada.golden.json")


def save(directory, scenario_name, fingerprint, messages):
    os.makedirs(directory, exist_ok=True)
    path = golden_path(directory, scenario_name)
    doc = {"format": FORMAT, "scenario": scenario_name, "side": "ada",
           "fingerprint": fingerprint, "messages": messages}
    tmp = path + ".tmp"
    with open(tmp, "w") as fd:
        json.dump(doc, fd, indent=1, sort_keys=True)
        fd.write("\n")
    os.replace(tmp, path)
    return path


def load(directory, scenario_name, fingerprint=None, allow_stale=False):
    path = golden_path(directory, scenario_name)
    if not os.path.isfile(path):
        raise GoldenMissing("no golden file: %s" % path)
    try:
        with open(path) as fd:
            doc = json.load(fd)
    except ValueError as e:
        raise GoldenError("corrupt golden file %s: %s" % (path, e))
    if doc.get("format") != FORMAT or "messages" not in doc:
        raise GoldenError("unsupported golden file format: %s" % path)
    if fingerprint is not None and doc.get("fingerprint") != fingerprint and not allow_stale:
        raise GoldenStale("golden file %s is stale (scenario or Ada config changed); "
                          "re-record with --record-golden or pass --allow-stale" % path)
    return doc["messages"]
