"""Reject cached mechanics produced by a different converter or native input set."""
import hashlib
from pathlib import Path

from .sources import read


def implementation_hashes(*, runtime=False):
    directory = Path(__file__).parent
    paths = [*directory.glob("*.py")]
    if runtime:
        paths.extend(directory.glob("runtime/*.lua"))
    return {p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths)}


def file_hashes(paths):
    return {name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in paths.items()}


def require_matching(recorded, current, label):
    if not isinstance(recorded, dict):
        raise ValueError(f"The catalog has no {label} fingerprints; rerun convert before using cached mechanics")
    changed = sorted(name for name in recorded.keys() | current.keys() if recorded.get(name) != current.get(name))
    if changed:
        raise ValueError(f"The catalog's {label} changed ({', '.join(changed)}); rerun convert before using cached mechanics")


def require_current_run(output, converter):
    from .compiler import SCHEMA_VERSION
    output = Path(output)
    run = read(output/"run.json")
    if not isinstance(run, dict) or run.get("status") != "complete":
        raise ValueError("The conversion run has not completed; partial output cannot be exported or verified")
    report = read(output/"report.json")
    if (run.get("schemaVersion") != SCHEMA_VERSION or not isinstance(report, dict)
            or report.get("schemaVersion") != SCHEMA_VERSION):
        raise ValueError("The catalog schema is missing or outdated; rerun convert before using cached mechanics")
    if type(run.get("records")) is not int or run["records"] <= 0 or run["records"] != report.get("records"):
        raise ValueError("The catalog completion marker does not match its report; rerun convert")
    require_matching(report.get("implementation"), implementation_hashes(), "implementation")
    require_matching(converter.artifacts, file_hashes(converter.artifact_paths), "loaded conversion inputs")
    require_matching(report.get("artifacts"), converter.artifacts, "conversion inputs")
    return report
