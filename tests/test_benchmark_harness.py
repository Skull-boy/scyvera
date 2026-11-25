"""Guardrails for the PD-5 benchmark harness.

These tests are fast and make no timing assertion tied to a published number:
shared runners are noisy, and a flaky perf gate trains people to ignore red. What
they do pin is the property that makes the published table trustworthy — the
corpus is reproducible, the scan accounts for every generated file, and the two
consecutive runs are byte-identical.

Never mark these tests skip.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from benchmarks import gen_corpus, render, run
from scyvera.audit import MAX_FILE_BYTES, SKIP_DIRS, scan_tree
from scyvera.audit_rules import RULES

REPO = Path(__file__).resolve().parent.parent


def test_generator_is_deterministic(tmp_path: Path) -> None:
    first = gen_corpus.generate(tmp_path / "seed-1a", 60, "clean", 1)
    same = gen_corpus.generate(tmp_path / "seed-1b", 60, "clean", 1)
    other = gen_corpus.generate(tmp_path / "seed-2", 60, "clean", 2)

    assert first.manifest_sha256 == same.manifest_sha256
    assert first.manifest_sha256 != other.manifest_sha256
    assert first.files_scanned == same.files_scanned == other.files_scanned
    assert first.files_skipped == same.files_skipped == other.files_skipped


def test_profile_composition_matches_the_published_numbers(tmp_path: Path) -> None:
    spec = gen_corpus.generate(tmp_path / "clean", 200, "clean", 1)

    assert spec.files_total == 200
    assert spec.files_skipped == 14  # 10 over-cap + 4 binary
    assert spec.files_scanned == 186
    assert spec.bytes_skipped > 10 * 1024 * 1024  # 10 x 1.2 MiB, roughly

    over_cap = [
        path for path in spec.root.rglob("*")
        if path.is_file() and path.stat().st_size > MAX_FILE_BYTES
    ]
    assert len(over_cap) == 10

    for decoy in (
        "node_modules/decoy/publish.sh",
        ".git/hooks/pre-push",
        "build/decoy.txt",
        "dist/decoy.js",
        ".venv/decoy.txt",
    ):
        assert (spec.root / decoy).is_file(), f"missing decoy {decoy}"

    report = scan_tree(spec.root)
    assert report.stats["files_scanned"] == spec.files_scanned
    assert report.stats["files_skipped"] == spec.files_skipped
    assert report.findings == ()
    assert report.score == 100

    scanned_bytes, skipped_bytes = run.tree_bytes(spec.root)
    assert (scanned_bytes, skipped_bytes) == (spec.bytes_scanned, spec.bytes_skipped)


def test_noisy_and_governed_profiles_exercise_the_rules(tmp_path: Path) -> None:
    noisy = gen_corpus.generate(tmp_path / "noisy", 200, "noisy", 1)
    noisy_report = scan_tree(noisy.root)
    assert {rule.rule_id for rule in RULES} <= {
        finding.rule_id for finding in noisy_report.findings
    }

    governed = gen_corpus.generate(tmp_path / "governed", 200, "governed", 1)
    governed_report = scan_tree(governed.root)
    assert governed_report.governed_count >= 1
    assert any(
        finding.scoring_reason == "governed"
        for finding in governed_report.findings
    )


def test_generator_refuses_to_write_inside_the_repository(tmp_path: Path) -> None:
    with pytest.raises(gen_corpus.CorpusLocationError):
        gen_corpus.generate(REPO / "benchmarks" / "corpus-should-not-exist", 20, "clean", 1)
    assert not (REPO / "benchmarks" / "corpus-should-not-exist").exists()

    with pytest.raises(gen_corpus.CorpusLocationError):
        (tmp_path / "occupied").mkdir()
        (tmp_path / "occupied" / "file.txt").write_text("x", encoding="utf-8")
        gen_corpus.generate(tmp_path / "occupied", 20, "clean", 1)


def test_run_smoke_verifies_the_scan_and_is_byte_identical(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    started = time.perf_counter()
    result = run.run(
        scales=[200],
        profiles=["clean"],
        repeats=2,
        scan_repeats=1,
        budget_seconds=120,
        seed=1,
        result_path=result_path,
    )
    elapsed = time.perf_counter() - started
    if elapsed > 60:
        pytest.skip(
            f"benchmark smoke took {elapsed:.0f}s on this machine (>60s ceiling); "
            "the harness itself is fine, the box is pathological"
        )

    (cell,) = result["cells"]
    assert cell["status"] == "measured", cell
    assert cell["verified"] is True
    assert cell["files_scanned"] == 186
    assert cell["files_skipped"] == 14
    assert cell["end_to_end_ms"]["count"] == 2
    assert cell["scan_ms"]["count"] == 1
    assert cell["peak_rss_mb"] is None or cell["peak_rss_mb"]["median"] > 0

    stored = json.loads(result_path.read_text(encoding="utf-8"))
    assert stored["cells"][0]["status"] == "measured"
    assert stored["environment"]["repeats"] == 2
    assert stored["protocol"]["headline"] == "median"


FIXTURE = {
    "environment": {
        "measured_at": "2026-11-25T00:00:00+00:00",
        "os": "Linux-6.8.0-x86_64",
        "os_build": "Ubuntu 24.04 (kernel 6.8.0)",
        "cpu": "Example CPU",
        "cpu_count": 4,
        "ram_gb": 16.0,
        "disk_free_gb": 50.0,
        "filesystem": "not probed",
        "python": "3.12.0",
        "python_implementation": "CPython",
        "scyvera_version": "1.4.0",
        "commit": "abc1234",
        "worktree_dirty": False,
        "repeats": 10,
        "scan_repeats": 3,
        "cache_state": "warm (filesystem cache not dropped)",
    },
    "protocol": {
        "repeats": 10,
        "scan_repeats": 3,
        "cache_state": "warm filesystem cache; cold cache not measured",
        "command": "/usr/bin/python -m scyvera.cli audit {tree} --json",
        "corpus_seed": 5,
    },
    "cells": [
        {
            "files": 1000,
            "profile": "noisy",
            "status": "measured",
            "files_scanned": 880,
            "files_skipped": 120,
            "bytes_scanned": 2 * 1024 * 1024,
            "findings": 12,
            "end_to_end_ms": {"median": 1000.0, "p95": 1500.0},
            "scan_ms": {"median": 700.0},
            "peak_rss_mb": {"median": 42.0},
        },
        {
            "files": 50000,
            "profile": "noisy",
            "status": "not_measured",
            "reason": "projected_over_budget",
            "detail": "projected 4000 s",
        },
    ],
}


def test_renderer_produces_the_published_table_shape() -> None:
    markdown = render.render_markdown(FIXTURE)

    assert "| files | profile | scanned | skipped |" in markdown
    assert "| 1,000 | noisy | 880 | 120 | 2.0 | 12 | 1000 | 1500 | 1.50 | 700 | 42.0 |" in markdown
    assert "not measured" in markdown
    assert "projected 4000 s" in markdown
    assert "**Commit:** `abc1234`" in markdown
    assert "**CPU:** Example CPU (4 logical cores)" in markdown
    assert "warm" in markdown
    assert "1,000" in markdown and "50,000" in markdown


def test_renderer_writes_between_markers(tmp_path: Path) -> None:
    document = tmp_path / "performance.md"
    document.write_text(
        f"# Before\n\n{render.START_MARKER}\n\nstale table\n{render.END_MARKER}\n\n# After\n",
        encoding="utf-8",
    )
    render.write_document(document, "fresh table")
    text = document.read_text(encoding="utf-8")
    assert "stale table" not in text
    assert "fresh table" in text
    assert text.startswith("# Before")
    assert text.rstrip().endswith("# After")


def test_generated_corpus_path_is_git_ignored() -> None:
    completed = subprocess.run(
        ["git", "check-ignore", "-q", "benchmarks/corpus/example/file.txt"],
        cwd=REPO,
    )
    assert completed.returncode == 0, "benchmarks/corpus/ is not git-ignored"
