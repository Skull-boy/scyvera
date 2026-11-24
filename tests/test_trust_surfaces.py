"""Trust-surface ledger guardrails (RFC 0004 Amendment 2 §7).

The audit report says a finding was governed; this test makes the surrounding
claim auditable: every publish command in CI maps to exactly one ledger entry,
every approval-bearing entry is backed by the root contract, and the set of
known gaps is pinned so adding one is a deliberate edit.

Never mark these tests skip.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scyvera.audit_rules import _CI_PUBLISH_RE
from scyvera.validator import load_contract

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "docs" / "trust-surfaces.yaml"
WORKFLOWS = ROOT / ".github" / "workflows"

REQUIRED_FIELDS = frozenset(
    {
        "id",
        "capability",
        "resource",
        "trigger",
        "workflow_or_entrypoint",
        "credential",
        "approval",
        "evidence",
        "status",
    }
)

#: The exact gap set. Adding a gap requires editing this line, which is the
#: point: the ledger cannot grow a silent hole.
PINNED_GAPS = frozenset({"pypi-publish"})


@pytest.fixture(scope="module")
def surfaces() -> list[dict]:
    data = yaml.safe_load(LEDGER.read_text(encoding="utf-8"))
    assert data["version"] == 1
    entries = data["surfaces"]
    assert isinstance(entries, list) and entries
    return entries


def test_every_entry_has_the_required_shape(surfaces: list[dict]) -> None:
    ids = [entry["id"] for entry in surfaces]
    assert len(ids) == len(set(ids)), f"duplicate ledger ids: {ids}"

    for entry in surfaces:
        assert REQUIRED_FIELDS <= set(entry), (
            f"{entry.get('id')} is missing {sorted(REQUIRED_FIELDS - set(entry))}"
        )
        assert entry["status"] in {"governed", "gap"}
        assert entry["credential"] in {"oidc", "token", "none"}


def test_every_publish_command_resolves_to_one_entry(surfaces: list[dict]) -> None:
    """Coverage: no orphan workflow, no duplicate owner."""
    matched: dict[str, str] = {}
    for workflow in sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml")):
        for line in workflow.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#"):
                continue
            match = _CI_PUBLISH_RE.search(line)
            if match is not None:
                relative = workflow.relative_to(ROOT).as_posix()
                matched[relative] = match.group(0)
                break

    assert matched, "the audit matcher found no publish command in CI"

    owners: dict[str, int] = {}
    for entry in surfaces:
        path = entry["workflow_or_entrypoint"]
        if path in matched:
            owners[path] = owners.get(path, 0) + 1

    assert set(owners) == set(matched), (
        "publish workflows without a ledger entry: "
        f"{sorted(set(matched) - set(owners))}"
    )
    assert all(count == 1 for count in owners.values()), (
        f"a publish workflow has more than one ledger entry: {owners}"
    )

    for entry in surfaces:
        if entry["workflow_or_entrypoint"] in matched:
            # A surface that publishes must be a capability-bearing entry, even
            # when it is a gap: `none` is reserved for read-only surfaces.
            assert entry["capability"] != "none", (
                f"{entry['id']} publishes but declares capability: none"
            )


def test_every_governed_entry_is_backed_by_the_contract(
    surfaces: list[dict],
) -> None:
    """Authority: a governed entry's approval is declared, not assumed."""
    contract = load_contract(ROOT / "contract.yaml")
    permissions = contract.get("permissions") or []
    approvals = contract.get("approvals") or []

    for entry in surfaces:
        if entry["status"] != "governed":
            continue
        capability = entry["capability"]
        if capability == "none":
            # Read-only sentinel: no credential, no approval, nothing to govern.
            assert entry["credential"] == "none", (
                f"{entry['id']} is read-only but names a credential"
            )
            assert entry["approval"] == "none", (
                f"{entry['id']} is read-only but names an approval"
            )
            continue

        assert capability in permissions, (
            f"{entry['id']}: capability {capability!r} is not declared in contract.yaml"
        )
        matching = [
            approval
            for approval in approvals
            if isinstance(approval, dict)
            and approval.get("action") == capability
            and approval.get("required") is True
            and isinstance(approval.get("approver"), str)
            and approval["approver"].strip()
        ]
        assert matching, (
            f"{entry['id']}: {capability!r} has no required approval in contract.yaml"
        )


def test_gaps_are_pinned(surfaces: list[dict]) -> None:
    gaps = {entry["id"] for entry in surfaces if entry["status"] == "gap"}
    assert gaps == PINNED_GAPS, (
        "the gap set changed; update PINNED_GAPS deliberately. "
        f"new: {sorted(gaps - PINNED_GAPS)}, fixed: {sorted(PINNED_GAPS - gaps)}"
    )
    for entry in surfaces:
        if entry["status"] == "gap":
            assert entry.get("gap_ref"), (
                f"{entry['id']} is a gap without a roadmap row reference"
            )
