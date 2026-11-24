"""RFC 0004 Amendment 2: govern findings a contract declares and approves.

A finding is *governed* when the scanned tree's own ``contract.yaml``
validates, is not provisional, declares the permission the finding's
remediation prescribes, and approves that action with ``required: true`` and a
named human approver. Governed findings stay in the report (rendered, with
``governed_by`` evidence) and leave the governed score; they still count in the
``raw_score``.

The resolver is deliberately small and **fail-closed**: it loads the contract
once, and any exception anywhere in that path means "no discounts". It never
raises into the scan.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from .audit_rules import Finding, prescription_for
from .validator import load_contract, validate_contract

CONTRACT_FILENAME = "contract.yaml"


@dataclass(frozen=True)
class GovernedSummary:
    """What the resolver learned about one scanned tree.

    ``contract_path`` is scan-relative and ``None`` when no contract could be
    used. ``governed_count`` counts findings exempted from the governed score.
    The two loads are computed by :mod:`scyvera.audit` because the coefficient
    table lives there.
    """

    contract_path: str | None
    governed_count: int


def _approved_permission(
    contract: Mapping[str, Any], permission: str
) -> str | None:
    """Return the approval action when ``permission`` is declared and approved.

    Fails closed on every shape that is not the prescribed one: a missing or
    non-list ``permissions`` field, a non-string entry, a missing approval
    list, an approval for another action, ``required`` absent or false, and an
    approval that names no approver.
    """
    permissions = contract.get("permissions")
    if not isinstance(permissions, list):
        return None
    if permission not in [item for item in permissions if isinstance(item, str)]:
        return None

    approvals = contract.get("approvals")
    if not isinstance(approvals, list):
        return None
    for entry in approvals:
        if not isinstance(entry, Mapping):
            continue
        if entry.get("action") != permission:
            continue
        if entry.get("required") is not True:
            continue
        approver = entry.get("approver")
        if not isinstance(approver, str) or not approver.strip():
            # A nameless approval is a blank cheque, not authority.
            continue
        return permission
    return None


def load_governing_contract(target_root: Path) -> tuple[Mapping[str, Any] | None, str | None]:
    """Load ``<target_root>/contract.yaml`` once, or ``(None, None)``.

    A symlinked contract is refused (T14-consistent). Validation uses the same
    loader and schema engine as every other product surface, so a contract that
    ``scyvera validate`` rejects can never grant authority here.
    """
    root = Path(target_root)
    if root.is_symlink() or not root.is_dir():
        return None, None
    contract_path = root / CONTRACT_FILENAME
    if contract_path.is_symlink() or not contract_path.is_file():
        return None, None

    try:
        validation = validate_contract(contract_path)
        if not validation.valid:
            return None, None
        data = load_contract(contract_path)
    except Exception:  # fail closed: no contract means no discounts
        return None, None

    if not isinstance(data, Mapping):
        return None, None
    if data.get("provisional") is True:
        # A draft has no authority until the human promotion ritual.
        return None, None
    return data, CONTRACT_FILENAME


def resolve_governed(
    findings: Sequence[Finding], target_root: Path
) -> tuple[list[Finding], GovernedSummary]:
    """Apply the Amendment 2 test to every finding.

    Quarantine wins: a fixture finding keeps ``scoring_reason: "quarantined"``
    even when a contract would also govern it. Every other finding is either
    ``scored`` or ``governed``; there is no third state and no partial
    discount.
    """
    contract, contract_path = load_governing_contract(target_root)

    resolved: list[Finding] = []
    governed = 0

    for finding in findings:
        if not finding.scored:
            resolved.append(
                replace(finding, scoring_reason="quarantined")
                if finding.scoring_reason == "scored"
                else finding
            )
            continue

        prescription = prescription_for(finding.rule_id)
        approval_action = (
            _approved_permission(contract, prescription.permission)
            if contract is not None and prescription is not None
            else None
        )

        if approval_action is not None:
            governed += 1
            resolved.append(
                replace(
                    finding,
                    scored=False,
                    scoring_reason="governed",
                    governed_by={
                        "permission": prescription.permission,
                        "approval_action": approval_action,
                        "contract_path": contract_path or CONTRACT_FILENAME,
                    },
                )
            )
        else:
            resolved.append(replace(finding, scoring_reason="scored"))

    return resolved, GovernedSummary(
        contract_path=contract_path,
        governed_count=governed,
    )
