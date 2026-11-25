"""RFC 0004 Amendment 2: governed findings.

Each test builds a miniature repository (one npm publish workflow, optionally a
contract) and asserts the scored/governed outcome. The semantics table in the
amendment is the spec; this file is its executable form.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from scyvera.audit import scan_tree
from scyvera.audit_rules import RULES, RULE_PRESCRIPTIONS, prescription_for

#: Phase 1 grammar: ``service:scope`` with no wildcards. A wildcard permission is
#: an invalid contract (Threat T7), so it can never be the thing that governs.
PERMISSION_GRAMMAR = re.compile(r"^[a-zA-Z0-9_\-]+:[a-zA-Z0-9_\-:]+$")

WORKFLOW = "name: publish\njobs:\n  publish:\n    steps:\n      - run: npm publish --access public\n"

CONTRACT = """\
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


def _repo(tmp_path: Path, contract: str | None = CONTRACT) -> Path:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / "publish.yml").write_text(WORKFLOW, encoding="utf-8")
    if contract is not None:
        (tmp_path / "contract.yaml").write_text(contract, encoding="utf-8")
    return tmp_path


def _findings(report):
    return {(f.rule_id, f.path): f for f in report.findings}


def test_declared_and_approved_finding_is_governed(tmp_path: Path) -> None:
    report = scan_tree(_repo(tmp_path))
    finding = _findings(report)[("AU-CI-002", ".github/workflows/publish.yml")]

    assert finding.scoring_reason == "governed"
    assert finding.scored is False
    assert finding.governed_by == {
        "permission": "registry:publish",
        "approval_action": "registry:publish",
        "contract_path": "contract.yaml",
    }
    assert report.score == 100
    assert report.band == "Shielded"
    assert report.raw_score == 92
    assert report.raw_band == "Shielded"
    assert report.governed_count == 1
    # Rendered, not hidden: the finding is still in the report.
    assert len(report.findings) == 1


def test_removing_the_approval_rescores_the_finding(tmp_path: Path) -> None:
    """The approval is load-bearing: without it, the finding is scored again."""
    governed = scan_tree(_repo(tmp_path / "governed"))
    assert governed.score == 100

    contract = CONTRACT.replace(
        "approvals:\n  - action: registry:publish\n    required: true\n    approver: maintainer\n",
        "approvals: []\n",
    )
    unscored = scan_tree(_repo(tmp_path / "unapproved", contract))
    finding = _findings(unscored)[("AU-CI-002", ".github/workflows/publish.yml")]

    assert finding.scoring_reason == "scored"
    assert finding.scored is True
    assert unscored.score == 92
    assert unscored.raw_score == 92
    assert unscored.governed_count == 0


def test_required_false_is_not_an_approval(tmp_path: Path) -> None:
    contract = CONTRACT.replace("required: true", "required: false")
    report = scan_tree(_repo(tmp_path, contract))
    assert report.score == 92
    assert report.governed_count == 0


def test_approval_without_an_approver_is_not_authority(tmp_path: Path) -> None:
    contract = CONTRACT.replace("    approver: maintainer\n", "")
    report = scan_tree(_repo(tmp_path, contract))
    assert report.score == 92
    assert report.governed_count == 0


def test_provisional_contract_is_not_authority(tmp_path: Path) -> None:
    contract = CONTRACT.replace("version: 1.1", "version: 1.1\nprovisional: true")
    report = scan_tree(_repo(tmp_path, contract))
    assert report.score == 92
    assert report.governed_count == 0
    assert report.governance == "provisional"


def test_invalid_contract_is_not_authority(tmp_path: Path) -> None:
    contract = CONTRACT.replace('permissions: ["registry:publish"]', 'permissions: "*"')
    report = scan_tree(_repo(tmp_path, contract))
    assert report.score == 92
    assert report.governed_count == 0


def test_no_contract_keeps_the_amendment_fields_out_of_the_payload(
    tmp_path: Path,
) -> None:
    """Non-negotiable 2: no contract -> byte-identical output."""
    report = scan_tree(_repo(tmp_path, contract=None))
    payload = report.to_dict()

    assert "raw_score" not in payload
    assert "raw_band" not in payload
    assert "governed_count" not in payload
    assert all("scoring_reason" not in f for f in payload["findings"])
    assert all("governed_by" not in f for f in payload["findings"])
    assert payload["score"] == 92

    # Same bytes on a second run.
    assert report.to_json() == scan_tree(_repo(tmp_path, contract=None)).to_json()


def test_governed_payload_carries_the_evidence(tmp_path: Path) -> None:
    report = scan_tree(_repo(tmp_path))
    payload = json.loads(report.to_json())
    (finding,) = payload["findings"]

    assert payload["score"] == 100
    assert payload["raw_score"] == 92
    assert payload["raw_band"] == "Shielded"
    assert payload["governed_count"] == 1
    assert finding["scoring_reason"] == "governed"
    assert finding["governed_by"]["contract_path"] == "contract.yaml"


def test_quarantine_wins_over_governance(tmp_path: Path) -> None:
    fixtures = tmp_path / "tests" / "fixtures"
    workflows = fixtures / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "publish.yml").write_text(WORKFLOW, encoding="utf-8")
    (tmp_path / "contract.yaml").write_text(CONTRACT, encoding="utf-8")

    report = scan_tree(tmp_path)
    (finding,) = [
        f for f in report.findings if f.path.startswith("tests/fixtures/")
    ]
    assert finding.scoring_reason == "quarantined"
    assert finding.governed_by is None


def test_every_rule_has_a_prescription_or_an_explicit_none() -> None:
    assert set(RULE_PRESCRIPTIONS) == {rule.rule_id for rule in RULES}
    for rule in RULES:
        prescription = prescription_for(rule.rule_id)
        if prescription is None:
            continue
        assert prescription.permission == "registry:publish"
        assert prescription.resources


def test_only_capability_rules_are_governable() -> None:
    governable = {
        rule_id for rule_id, value in RULE_PRESCRIPTIONS.items() if value is not None
    }
    assert governable == {"AU-CI-002"}
    for rule_id in (
        "AU-NET-002",
        "AU-N8N-001",
        "AU-SECRET-001",
        "AU-NET-001",
        "AU-DOC-001",
        "AU-DEP-001",
    ):
        assert RULE_PRESCRIPTIONS[rule_id] is None


def test_prescription_permissions_follow_the_grammar() -> None:
    """A prescription names one concrete ``service:scope``, never a wildcard."""
    prescribed = [
        prescription
        for prescription in RULE_PRESCRIPTIONS.values()
        if prescription is not None
    ]
    assert prescribed, "no rule prescribes a capability; the registry is wrong"

    for prescription in prescribed:
        permission = prescription.permission
        assert PERMISSION_GRAMMAR.match(permission), (
            f"{permission!r} does not match service:scope"
        )
        assert "*" not in permission
        assert permission.lower() not in {"all", "any", "none"}


def test_resource_is_chosen_per_command() -> None:
    prescription = prescription_for("AU-CI-002")
    assert prescription is not None
    assert prescription.resource_for("npm publish --access public") == "npm_registry"
    assert prescription.resource_for("npm stage publish") == "npm_registry"
    assert prescription.resource_for("cargo publish --locked") == "crates_io_registry"
    assert prescription.resource_for("twine upload dist/*") is None


@pytest.mark.parametrize(
    "line",
    [
        "cargo publish --locked",
        "cargo publish",
    ],
)
def test_cargo_publish_matches(line: str) -> None:
    from scyvera.audit_rules import _CI_PUBLISH_RE

    assert _CI_PUBLISH_RE.search(line) is not None


@pytest.mark.parametrize(
    "line",
    [
        "cargo build --release",
        "cargo package --locked",
        "cargo test --locked",
        "cargo yank --version 0.1.0",
    ],
)
def test_non_publish_cargo_commands_do_not_match(line: str) -> None:
    from scyvera.audit_rules import _CI_PUBLISH_RE

    assert _CI_PUBLISH_RE.search(line) is None


def test_a_commented_cargo_publish_is_not_a_finding() -> None:
    from scyvera.audit_rules import _match_ci_publish

    workflow = "# cargo publish --locked\njobs:\n  p:\n    steps:\n      - run: cargo build\n"
    assert _match_ci_publish(".github/workflows/w.yml", workflow, "w.yml") == []


def test_a_changelog_line_is_never_scanned_as_a_workflow() -> None:
    from scyvera.audit_rules import _match_ci_publish

    assert _match_ci_publish("CHANGELOG.md", "cargo publish --locked\n", "CHANGELOG.md") == []
