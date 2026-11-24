"""Permanent dogfood guardrail for RFC 0004 §7 check #1 (M2.0a.1).

This repository is the product's first customer. Since
[RFC 0004 Amendment 1](../rfcs/0004-amendment-1-dogfood-declared-capability.md)
(2026-11-18) the guardrail is a covenant rather than a fixed band: `scyvera
audit .` must produce exactly the scored findings declared below, and the root
`contract.yaml` must declare and approve the capability that introduces the one
high finding (AU-CI-002 for the npm publish workflow).

The intentional bad files under ``tests/fixtures/`` must remain visible but
quarantined (``scored == false``). Never mark these tests skip.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scyvera.audit import AuditReport, scan_tree
from scyvera.validator import load_contract


ROOT = Path(__file__).resolve().parent.parent

#: The exact scored-findings covenant (RFC 0004 Amendment 2). Every entry is
#: ``(severity, rule_id, path)``. Adding or removing a scored finding is a
#: covenant change: update this table together with a new amendment, never
#: silence a finding.
EXPECTED_SCORED_FINDINGS = frozenset(
    {
        (
            "medium",
            "AU-N8N-001",
            "implementations/n8n/competitor-feature-parity-watcher/workflow.json",
        ),
        (
            "medium",
            "AU-N8N-001",
            "implementations/n8n/duplicate-issue-detector/workflow.json",
        ),
        (
            "medium",
            "AU-N8N-001",
            "implementations/n8n/github-debugger-agent/workflow.json",
        ),
        (
            "medium",
            "AU-N8N-001",
            "implementations/n8n/telegram-github-antigravity-pipeline/workflow.json",
        ),
        (
            "medium",
            "AU-NET-002",
            "implementations/langgraph/duplicate-issue-detector/backfill.py",
        ),
        (
            "medium",
            "AU-NET-002",
            "implementations/langgraph/duplicate-issue-detector/duplicate_issue_detector/nodes.py",
        ),
    }
)

#: Findings excluded from the governed score because the root contract declares
#: and approves the capability (RFC 0004 Amendment 2). They remain in the
#: report with ``scoring_reason: "governed"``.
EXPECTED_GOVERNED_FINDINGS = frozenset(
    {
        ("high", "AU-CI-002", ".github/workflows/publish-scyvera-ts.yml"),
        ("high", "AU-CI-002", ".github/workflows/publish-scyvera-rs.yml"),
    }
)


@pytest.fixture(scope="module")
def repository_report() -> AuditReport:
    return scan_tree(ROOT)


def test_repository_scans_to_the_declared_covenant(
    repository_report: AuditReport,
) -> None:
    """Pin the honest numbers and the exact scored/governed surface."""
    assert repository_report.score == 92
    assert repository_report.band == "Shielded"
    assert repository_report.raw_score == 82
    assert repository_report.raw_band == "Controlled"
    assert repository_report.governed_count == 2
    assert repository_report.governance == "governed"

    scored = frozenset(
        (finding.severity, finding.rule_id, finding.path)
        for finding in repository_report.findings
        if finding.scored
    )
    governed = frozenset(
        (finding.severity, finding.rule_id, finding.path)
        for finding in repository_report.findings
        if finding.scoring_reason == "governed"
    )
    assert scored == EXPECTED_SCORED_FINDINGS
    assert governed == EXPECTED_GOVERNED_FINDINGS


def test_root_contract_declares_and_approves_the_publish_capability() -> None:
    """The one high finding is declared and approved, not hidden.

    AU-CI-002's own remediation metadata prescribes this exact permission and
    approval pair. Removing the approval must fail this test: that is what
    makes the covenant an approval rather than a waiver.
    """
    contract = load_contract(ROOT / "contract.yaml")

    assert "registry:publish" in contract["permissions"]

    publish_approvals = [
        approval
        for approval in contract["approvals"]
        if isinstance(approval, dict)
        and approval.get("action") == "registry:publish"
        and approval.get("required") is True
    ]
    assert publish_approvals, (
        "contract.yaml must approve registry:publish with required: true"
    )
    assert all(
        isinstance(approval.get("approver"), str)
        and approval["approver"].strip()
        for approval in publish_approvals
    ), "registry:publish must name a human approver role"


def test_positive_fixture_findings_are_quarantined(
    repository_report: AuditReport,
) -> None:
    fixture_findings = [
        finding
        for finding in repository_report.findings
        if finding.path.startswith("tests/fixtures/")
    ]
    known_finding = [
        finding
        for finding in fixture_findings
        if finding.rule_id == "AU-SH-001"
        and finding.path == "tests/fixtures/audit/positive/scripts/clean.sh"
    ]

    assert fixture_findings
    assert known_finding
    assert all(finding.scored is False for finding in fixture_findings)


def test_removing_the_approval_re_scores_both_publish_capabilities(
    tmp_path: Path,
) -> None:
    """The approval is load-bearing for npm and crates.io alike."""
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "publish-npm.yml").write_text(
        "jobs:\n  p:\n    steps:\n      - run: npm publish --access public\n",
        encoding="utf-8",
    )
    (workflows / "publish-crates.yml").write_text(
        "jobs:\n  p:\n    steps:\n      - run: cargo publish --locked\n",
        encoding="utf-8",
    )
    contract = """\
version: 1.1
system:
  name: demo
lifecycle:
  mode: request-response
  initiation: human-only
  resumability: stateless
permissions: ["registry:publish"]
side_effects: []
approvals:
  - action: registry:publish
    required: true
    approver: maintainer
"""
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(contract, encoding="utf-8")

    governed = scan_tree(tmp_path)
    assert governed.governed_count == 2
    assert governed.score == 100

    contract_path.write_text(
        contract.replace(
            "approvals:\n  - action: registry:publish\n"
            "    required: true\n    approver: maintainer\n",
            "approvals: []\n",
        ),
        encoding="utf-8",
    )
    ungoverned = scan_tree(tmp_path)
    assert ungoverned.governed_count == 0
    assert ungoverned.score == 90
    assert ungoverned.raw_score == 90
