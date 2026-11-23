"""Guard the runner-acquisition retry classifier.

``.github/workflows/retry-cancelled-jobs.yml`` re-runs a failed run *only* when
every non-success job was cancelled with zero executed steps. Both directions
are dangerous:

* too loose — a real test failure gets retried until it looks green;
* too tight — CI stays red on GitHub capacity noise, which is what the
  workflow exists to absorb.

The classifier is extracted from the workflow file itself and exercised here, so
editing the YAML without re-checking these cases fails the suite.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "retry-cancelled-jobs.yml"
MARKER = "<<'PY'"


@pytest.fixture(scope="module")
def classifier(tmp_path_factory: pytest.TempPathFactory) -> Path:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    script = data["jobs"]["retry"]["steps"][0]["run"]
    start = script.index(MARKER) + len(MARKER)
    end = script.index("\nPY\n", start)
    body = script[start:end].strip("\n")
    # If the heredoc shape changes, fail loudly instead of testing nothing.
    assert "acquisition" in body and "SystemExit" in body
    target = tmp_path_factory.mktemp("retry") / "classifier.py"
    target.write_text(body + "\n", encoding="utf-8")
    return target


def _job(
    name: str,
    conclusion: str,
    *,
    steps: int = 0,
    failed_step: bool = False,
) -> dict[str, object]:
    payload_steps = [{"conclusion": "success"} for _ in range(steps)]
    if failed_step:
        payload_steps.append({"conclusion": "failure"})
    return {"name": name, "conclusion": conclusion, "steps": payload_steps}


def _decide(
    classifier: Path,
    tmp_path: Path,
    jobs: list[dict[str, object]],
    *,
    attempt: int = 1,
) -> tuple[str, str]:
    payload = tmp_path / "jobs.json"
    payload.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
    report = tmp_path / "report.txt"
    completed = subprocess.run(
        [sys.executable, str(classifier), str(payload)],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "ATTEMPT": str(attempt),
            "MAX_ATTEMPTS": "3",
            "REPORT": str(report),
        },
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() in {
        "retry",
        "keep: no non-success jobs",
        "keep: at least one job executed steps and failed",
        "keep: runner acquisition failed 3 times",
    }, completed.stdout
    return completed.stdout.strip(), report.read_text(encoding="utf-8")


def test_acquisition_cancellation_is_retried(
    classifier: Path, tmp_path: Path
) -> None:
    decision, report = _decide(
        classifier,
        tmp_path,
        [
            _job("ubuntu 3.12", "success", steps=5),
            _job("windows 3.12", "success", steps=5),
            _job("macos 3.14", "cancelled"),
        ],
    )
    assert decision == "retry"
    assert "macos 3.14: cancelled, steps=0" in report


def test_real_failure_is_never_retried(
    classifier: Path, tmp_path: Path
) -> None:
    decision, _ = _decide(
        classifier,
        tmp_path,
        [
            _job("ubuntu 3.12", "success", steps=5),
            _job("windows 3.12", "failure", steps=4, failed_step=True),
            _job("macos 3.14", "cancelled"),
        ],
    )
    assert decision == "keep: at least one job executed steps and failed"


def test_cancelled_job_that_ran_steps_is_not_acquisition(
    classifier: Path, tmp_path: Path
) -> None:
    """A run cancelled mid-flight is a human decision, not a capacity failure."""
    decision, _ = _decide(
        classifier,
        tmp_path,
        [
            _job("ubuntu 3.12", "success", steps=5),
            _job("windows 3.12", "cancelled", steps=2),
        ],
    )
    assert decision == "keep: at least one job executed steps and failed"


def test_retries_are_capped(classifier: Path, tmp_path: Path) -> None:
    decision, _ = _decide(
        classifier,
        tmp_path,
        [_job("macos 3.14", "cancelled")],
        attempt=3,
    )
    assert decision == "keep: runner acquisition failed 3 times"


def test_nothing_to_retry(classifier: Path, tmp_path: Path) -> None:
    decision, _ = _decide(
        classifier,
        tmp_path,
        [_job("ubuntu 3.12", "success", steps=5), _job("macos 3.10", "skipped")],
    )
    assert decision == "keep: no non-success jobs"
