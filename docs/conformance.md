# Conformance: check what the code actually does

`scyvera check` implements the RFC 0003 §C3 tiers. Tier 0 is a strict superset of `validate` +
`lint`; Tier 1 inspects implementation source against the declared contract.

```bash
# Tier 0 — structural: schema errors + ACxxx semantic warnings in one report
scyvera check contract.yaml

# Tier 1 — static: an n8n workflow or LangGraph implementation directory
scyvera check implementations/n8n/duplicate-issue-detector --tier 1
scyvera check implementations/langgraph/duplicate-issue-detector --tier 1
```

```text
FAIL  implementations/n8n/duplicate-issue-detector/contract.yaml (tier 1 (static): 2 tier-1 finding(s))
      [T101] undeclared action: node 'Embed New Issue (Ollama)' reaches 'local-llm' ...

WARN  implementations/langgraph/duplicate-issue-detector/contract.yaml (tier 1 (static): 6 tier-1 finding(s))
      [T103] unused declaration: contract declares a permission for 'github.close' ...
```

The n8n reference intentionally reports `T101` for its two Ollama endpoints; the LangGraph
reference is `T103`-only, which is warn-only and exits `0`. Both behaviours are pinned in
`tests/test_tier1_n8n.py` and `tests/test_tier1_langgraph.py`.

Tier behaviour is explicit, never silent:

- `--tier auto` (default) resolves to the highest implemented tier and prints a `note:` saying
  which one it chose.
- `--tier 1` dispatches to the adapter that claims the target (n8n workflow JSON or LangGraph
  Python source). An unclaimed target exits `2` with one actionable line.
- `--tier 2` (runtime trace) is reserved and fails loudly with exit `2` until the trace adapter
  ships. That adapter is the `check --tier 2` surface only: the runtime trace and eval engine
  itself shipped in M2.4/M2.5, and `scyvera eval` already runs four-axis scoring over governed
  agents.

## Tier 1 finding taxonomy

| Code | Severity | Meaning |
|---|---|---|
| `T101` | error | **Undeclared action** — the implementation reaches an external service the contract does not declare. |
| `T102` | error | **Ungated call** — a write-capable path is reachable from a trigger without traversing a declared approval gate. |
| `T103` | warning | **Unused declaration** — the contract declares something the implementation never exercises. Additive symmetry, never fails a check on its own. |

Exit codes: `0` pass (or warn-only), `1` a T101/error-severity T102, `2` usage/IO or an unavailable
tier.

The adapters never import or execute the target: n8n is parsed as JSON, LangGraph as Python `ast`.
Unknown externally-reaching node types, unknown hosts, and unparseable source fail closed as
findings rather than being skipped.

## Eval scoring (`scyvera eval`)

An eval case is a YAML file naming a contract, a scenario, and the expected trace. The harness runs
the case's reference agent through a `ContractEnforcer`, records the RFC 0003 §C4 trace, and scores
four axes.

```bash
scyvera eval implementations/langgraph/duplicate-issue-detector/evals/refund-agent.eval.yaml
```

```text
WARN  refund-agent
      total: 75.0/100
      constraints: 0.0
      approval: 1.0
      recovery: 1.0
      replay: 1.0
      trace: 4 entries
```

The total is `100 × Σ(weight × axis)`; this fixture deliberately attempts one undeclared action, so
`constraints` is `0.0` and the case reports `WARN`. A matching run is a measurement, not a
certification. Warnings, when a run records any, print as `[EVAL]` lines below the axes. `--json`
emits the unified report envelope; `check` and `audit` gain additive `--unified` flags with the same
envelope, and their existing `--json` outputs stay byte-identical. Exit codes: `0` pass/warn, `1`
fail, `2` usage/IO.

Case format and scoring details: [`evals.md`](./evals.md).

## What the tiers do not cover

Tier 0 and Tier 1 reason about declarations and source structure. They do not execute the target,
do not inspect a running process, and do not perform bytecode analysis. Runtime behaviour is
covered by the enforcer and by traces; see the threat models in
[`threat-model-lifecycle.md`](./threat-model-lifecycle.md),
[`threat-model-enforcer.md`](./threat-model-enforcer.md), and
[`threat-model-distribution.md`](./threat-model-distribution.md).
