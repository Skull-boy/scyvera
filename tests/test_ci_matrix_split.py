"""Pin how CI coverage is split between the merge gate and the nightly.

The split exists because macOS hosted runners were failing ~45% of the time
(the 24 hours to 2026-11-24: 6 successes, 5 cancellations, against 40/40 for
Linux and Windows), which made the merge gate noise. These tests make the
arrangement explicit so it cannot drift back by accident:

* pull requests gate on Linux and Windows only, all five Python versions;
* macOS runs every supported version nightly;
* the two sets together are still the full 15-cell matrix;
* every workflow the retry job watches exists, so a rename cannot silently
  disable the retry.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
GATE = WORKFLOWS / "validate-contracts.yml"
NIGHTLY = WORKFLOWS / "macos-nightly.yml"
RETRY = WORKFLOWS / "retry-cancelled-jobs.yml"

VERSIONS = ["3.10", "3.11", "3.12", "3.13", "3.14"]
EXPECTED_GATE_OS = ["ubuntu-latest", "windows-latest"]


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _matrix(path: Path) -> dict:
    return _load(path)["jobs"]["build-and-test"]["strategy"]["matrix"]


def test_pull_request_gate_never_waits_on_macos() -> None:
    matrix = _matrix(GATE)
    assert matrix["os"] == EXPECTED_GATE_OS
    assert not any("macos" in os for os in matrix["os"])
    assert matrix["python-version"] == VERSIONS
    # An exclude list here would mean macOS crept back in.
    assert "exclude" not in matrix


def test_gate_keeps_fail_fast_off() -> None:
    strategy = _load(GATE)["jobs"]["build-and-test"]["strategy"]
    assert strategy["fail-fast"] is False


def test_nightly_covers_every_supported_macos_version() -> None:
    job = _load(NIGHTLY)["jobs"]["build-and-test"]
    assert job["runs-on"] == "macos-latest"
    assert job["strategy"]["matrix"]["python-version"] == VERSIONS
    assert job["strategy"]["fail-fast"] is False


def test_union_is_still_the_full_matrix() -> None:
    gate = _matrix(GATE)
    nightly = _matrix(NIGHTLY)
    cells = {(os, v) for os in gate["os"] for v in gate["python-version"]}
    cells |= {("macos-latest", v) for v in nightly["python-version"]}
    assert len(cells) == 15
    for version in VERSIONS:
        assert {
            os for os, ver in cells if ver == version
        } == {"ubuntu-latest", "windows-latest", "macos-latest"}


def test_retry_job_watches_workflows_that_exist() -> None:
    names = {
        data["name"]
        for data in (_load(path) for path in WORKFLOWS.glob("*.yml"))
        if isinstance(data, dict) and "name" in data
    }
    watched = _load(RETRY)[True]["workflow_run"]["workflows"]
    missing = [name for name in watched if name not in names]
    assert not missing, f"retry watches a workflow that does not exist: {missing}"
