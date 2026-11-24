# RFC 0004 — Amendment 2: Governed findings (declared and approved capabilities)

> [!NOTE]
> **Status: Accepted (2026-11-24)**
> Amends RFC 0004 §4 (Blast Radius scoring) only. §7 check #1's covenant is
> re-pinned by the same change, through
> [Amendment 1](./0004-amendment-1-dogfood-declared-capability.md) §5.
> Author: Scyvera Core Team / Agent Contracts Working Group
> Applies to: `scyvera` 1.5.x and later

---

## 1. The rule

A **scored** finding becomes **governed** (rendered, but excluded from the scored
load) if and only if **all four** hold:

| # | Condition |
|---|---|
| a | the scan target has a `contract.yaml` at its root; |
| b | that contract parses and validates against its declared schema version; |
| c | the contract is **not** provisional (`provisional` absent or `false`); and |
| d | the finding's prescribed permission appears in `permissions`, **and** an entry in `approvals` has `action` equal to that permission with `required: true` **and a non-empty `approver`**. |

Any failure of (a)–(d) leaves the finding scored. The resolver fails closed: an
unreadable file, a symlinked contract, an unknown schema version, a malformed
approval list, or an exception anywhere in the path means "no discounts".

The prescription is the finding's own remediation metadata (the `permissions` /
`approvals` pair the AUxxx rule already emits for `--generate`). A rule that has
no prescription can never be governed — there is no capability a contract could
legitimise.

Quarantine is checked first: a finding under `tests/fixtures/` keeps
`scoring_reason: "quarantined"` even when a contract would also govern it.

---

## 2. Semantics table

Every row is a scan of a tree that contains the finding in question.

| # | Situation | Outcome | Why |
|---|---|---|---|
| 1 | No `contract.yaml` at the target root | **scored** | (a) fails: there is no declaration to honour. |
| 2 | Contract exists but cannot be read (IO error, invalid UTF-8, symlink) | **scored** | (a)/(b) fail closed. A file the engine cannot verify is not authority. |
| 3 | Contract parses but is not a YAML mapping | **scored** | (b) fails: not a contract. |
| 4 | Contract is a mapping but fails its declared JSON Schema | **scored** | (b) fails: an invalid contract declares nothing. |
| 5 | Contract declares an unsupported version (e.g. `version: 9`) | **scored** | (b) fails: unknown schema cannot be validated. |
| 6 | Contract is `provisional: true` (v1.1/v1.2) | **scored** | (c) fails: a draft has no authority until the human promotion ritual. |
| 7 | A wildcard permission (`*`, `all`, `any`) is present | **scored** | The contract is invalid (Threat T7), so (b) fails. Wildcards are never authority. |
| 8 | Permission is declared, but no approval entry names it | **scored** | (d) fails: declaring a capability is not approving it. |
| 9 | Approval exists with `required: false`, or `required` absent | **scored** | (d) fails: the gate is not load-bearing. |
| 10 | Approval exists for a **different** action | **scored** | (d) fails: approvals are per-action, never global. |
| 10b | Approval has the right action and `required: true` but no `approver` | **scored** | (d) fails: a nameless approval is a blank cheque, not authority. |
| 11 | Permission declared and a matching approval with `required: true` and a named approver | **governed** | All four hold. The finding is rendered with `governed_by` and excluded from scored load. |
| 12 | Two findings of the same rule, one governed and one not | First **governed**, second **scored** | Each finding is evaluated independently; a governed finding does not consume a coefficient slot, so the second scored occurrence still receives coefficient `1.00`. |
| 13 | Finding's rule has no prescription (AU-NET-002, AU-N8N-001, AU-SECRET-001, AU-NET-001, AU-DOC-001, AU-DEP-001) | **scored** | No capability could legitimise it; `None` means "permanently scored", not "nothing required". |
| 14 | Finding is under `tests/fixtures/` **and** a contract would govern it | **quarantined** | Quarantine precedence is preserved. `governed_by` is null; the reason names the winner. |
| 15 | Several findings, some governed | Mixed | Score uses scored findings only; `raw_score` uses every non-quarantined finding. |

---

## 3. Report contract

The change is **strictly additive**; `report_version` stays `1`.

### 3.1 Per finding

| Field | Type | Meaning |
|---|---|---|
| `scoring_reason` | `"scored" \| "quarantined" \| "governed"` | Why this finding does or does not contribute to the governed score. |
| `governed_by` | object or `null` | `{permission, approval_action, contract_path}` when governed; `null` otherwise. |
| `scored` | boolean | Unchanged meaning: `false` for quarantined and governed findings, `true` otherwise. |

`governed_by.contract_path` is scan-relative (`contract.yaml`), never absolute.

### 3.2 Per report

| Field | Meaning |
|---|---|
| `score` / `band` | **Governed** score: the number `--fail-under` gates on. Unchanged field names, changed derivation (governed findings excluded). |
| `raw_score` / `raw_band` | What the score would be if every non-quarantined finding were scored. Always `>= score`. |
| `raw_load` | The floating-point load behind `raw_score`, before `ceil`. |
| `governed_count` | Number of findings excluded by governance. |
| `stats.findings` | Unchanged: counts of **scored** findings by severity. |
| `draft_available` / `packs_suggested` | Unchanged: derived from scored findings. |

### 3.3 Output stability (deliberate decision)

Non-negotiable 2 requires a tree with **no** `contract.yaml` to be byte-identical
to today. Removing fields from the payload would violate §3.2, so the additive
fields are emitted **only when the target has a governing `contract.yaml`**:

- no contract → `to_dict()`, `--json`, the terminal render, and the unified
  envelope are byte-for-byte unchanged (pinned by a golden test);
- contract present → the new fields appear, and `raw_score >= score` is visible.

This is a conditional-additive contract, not a version bump: a reader that
ignores unknown keys works on both shapes, and a consumer that needs the raw
number reads it exactly when governance can exist.

### 3.4 The word "governed", disambiguated

Two different things have shared this word; this amendment fixes that:

- **Tree governance** (`governance.status` = `governed` / `provisional` /
  `ungoverned`) answers *"does this tree have a valid non-provisional
  contract?"* It is rendered today and carried in the unified envelope.
- **Governed finding** (`scoring_reason: "governed"`) answers *"did this
  specific declared-and-approved capability exempt this finding from the score?"*

A tree can be `governed` with zero governed findings (a contract that approves
nothing), and a finding can never be governed in an `ungoverned` or
`provisional` tree. The report shows both without conflating them.

---

## 4. Migration note

For any repository that already declares **and** approves a capability, the
reported score will rise and the band may change **without any code change**.
That is the intended behaviour, and it is why every report shows both numbers.

- The governed score is the gate (`--fail-under`).
- The raw score is the reviewer's escape hatch: it answers "what would this
  score be if nothing were approved?" and it never hides a finding.
- A repository that wants the old behaviour should not approve the capability.
  There is deliberately no flag to opt out per run.

---

## 5. Rejected alternatives

| Alternative | Why rejected |
|---|---|
| A CLI flag (`--honor-contract`) to opt in | Governance would become a reviewer's preference instead of a property of the scanned tree. Two runs over the same bytes could report different scores. |
| Discount by **resource** instead of permission | Resources are free-form (`npm_registry`, `crates_io_registry`); a typo would silently exempt a finding. Permissions are pattern-constrained (`service:scope`) and already validated. |
| Trust a `# scyvera:ignore` comment | An in-band escape hatch is exactly the waiver this amendment exists to avoid: it needs no approval, leaves no report trail, and can be added by the same change that introduces the risk. |
| Govern when the approval exists but names no approver | An approval with no human role is a blank cheque. `approvals[].approver` is required for a reason; the dogfood test asserts it. |
| Score half (e.g. 4 instead of 8) | A partial discount invents a weight nobody can audit. Governance is binary here: the capability is either declared and approved, or it is scored. |

---

## 6. Numbers

Load = `Σ severity_weight × per-rule coefficient`, with coefficients
`1.00, 0.25, 0.10, 0` assigned by occurrence order **among scored findings**;
`score = max(0, 100 - ceil(load))`.

| State | Scored findings | Scored load | Score / band | Raw load | Raw score / band |
|---|---|---|---|---|---|
| Today (Amendment 1) | CI-002 ×1, N8N-001 ×4, NET-002 ×2 | 8.0 + 4.05 + 3.75 = 15.8 | **84 / Controlled** | 15.8 | 84 / Controlled |
| Governed scoring only (one CI-002) | N8N-001 ×4, NET-002 ×2 | 7.8 | **92 / Shielded** | 15.8 | 84 / Controlled |
| Governed scoring + `cargo publish` matcher | N8N-001 ×4, NET-002 ×2 | 7.8 | **92 / Shielded** | 8.0 + 2.0 + 4.05 + 3.75 = 17.8 | **82 / Controlled** |

The third row is the ship state: two publish surfaces are measured (npm and
crates.io), both are governed by the same declared permission and required
approval, and the raw score is two points **lower** than before because the
matcher now sees a capability it previously did not measure. That is the point:
the base got stronger, not quieter.

The PyPI publish workflow remains a **gap**, not a governed surface: it has no
environment protection and its resource is not declared. It is recorded in the
trust-surface ledger with a pinned `gap` status; this amendment does not fix it.

---

## 7. Trust-surface ledger (companion artifact)

`docs/trust-surfaces.yaml` enumerates every surface that can affect the outside
world. `tests/test_trust_surfaces.py` enforces three properties: every publish
command the audit matcher finds under `.github/workflows/**` resolves to exactly
one entry; every governed entry's capability is declared with a required
approval; and the set of `gap` entries is pinned so adding one is a deliberate
edit.

The ledger is where "governed" becomes auditable outside a single scan: the
report says a finding was governed; the ledger says which workflow, which
credential, which approval, and what evidence.
