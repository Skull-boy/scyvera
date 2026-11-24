# Quickstart: audit → draft → enforce

The four commands below turn an unknown repository into a declared, enforced boundary. Every
step is read-only until step 3, and the whole loop takes about two minutes.

```bash
pip install scyvera
scyvera audit .                      # 1. scan
scyvera audit . --generate contract.yaml   # 2. draft
scyvera check contract.yaml          # 3. verify the draft
```

## 1. Scan anything

```bash
scyvera audit <path>
```

The report answers one question: *what can this environment actually do?* It is deterministic, it
never writes to the scanned tree, and it does not need a contract to run.

Blast Radius bands (RFC 0004 §4):

| Band | Score | Interpretation |
|---|---|---|
| **Shielded** | 90–100 | Few or no scored findings; the scanned boundary is narrow. |
| **Controlled** | 70–89 | Some findings; the boundary is mostly declared, with gaps to review. |
| **Exposed** | 40–69 | Multiple or high-severity findings; the environment can do more than it declares. |
| **Unbounded** | 0–39 | Critical or broad findings; little enforceable boundary is present. |

A band summarizes a scan. It is not a security certification.

Language pattern coverage, including what is deliberately not caught, is listed in
[`language-coverage.md`](./language-coverage.md). Audit is pattern-level and review-grade; the
Tier 1 adapters handle AST-aware checks.

## 2. Put a badge in your README

```bash
scyvera audit . --badge
```

Alongside the report it prints the snippet below:

```markdown
[![Blast Radius: Controlled](https://img.shields.io/badge/blast%20radius-Controlled-orange)](scyvera)
```

The badge is band-only on purpose: a score changes when a rule refines, a band does not.

## 3. Gate CI

```bash
scyvera audit . --fail-under 90
```

Exit codes: `0` ok, `1` findings or threshold breach, `2` usage or I/O error.

One GitHub Actions step:

```yaml
- run: scyvera audit . --fail-under 90
```

Pick the floor you can defend. This repository pins `--fail-under 92`; its npm and crates.io publish
workflows are declared and approved capabilities, so they are **governed, not waived**: the report
shows `92/100 (Shielded)` with `raw 82/100 (Controlled)`, and the raw number still counts them
([RFC 0004 Amendment 2](../rfcs/0004-amendment-2-governed-findings.md)).

## 4. Adopt the boundary it found

```bash
scyvera audit . --generate contract.yaml
```

```text
Draft contract written to contract.yaml (validate with: scyvera validate contract.yaml).
```

The scan writes one schema-valid v1.1 contract. `scyvera validate contract.yaml` and
`scyvera lint contract.yaml` both pass with zero warnings, and a permanent fixture sweep enforces
that for every audit corpus. `--force` overwrites an existing file; nothing else is ever written.

That draft is the input to the enforcement layer: `ContractEnforcer.load("contract.yaml")` turns
the scanned boundary into a runtime gate. See [`python-api.md`](./python-api.md).

For a ready-made boundary for a shipped runtime, start from a per-target
[adoption kit](../kits/) (`n8n`, `langgraph`) instead of a blank template.

## 5. Start from a policy, not a blank page

```bash
scyvera audit . --generate contract.yaml --pack github-safe
```

The pack's constraints win over heuristic-derived entries; finding-only extras are appended. Six
golden packs ship in [`packs/`](../packs/): `dev-agent`, `github-safe`, `finance-ops`,
`research-assistant`, `email-triage`, `devops-safe`. Loading is local-only. A pack is a starting
boundary, not an audit result. See [`policy-packs.md`](./policy-packs.md).

## The one-line version

```bash
pip install scyvera && scyvera audit . && scyvera audit . --generate contract.yaml
```

Then load the draft in your agent, gate the tools, and let it run.
