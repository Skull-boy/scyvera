# Python API: enforce, isolate, and prove

Scanning shows what the environment can do. This page turns that into enforcement: the draft from
[`quickstart.md`](./quickstart.md) is a normal v1.1 contract, so it loads into the enforcer, and
the registry makes the boundary provable after the fact.

Scyvera provides complementary governance layers:

| Layer | Component | Responsibility | Trust level |
|---|---|---|---|
| **Tier 0: Structural** | `validate_contract()`, `lint_contract()` | Validates that `contract.yaml` is structurally and semantically well-formed against JSON Schemas and the ACxxx rules. | Declaration conformance |
| **Tier 1: Static** | `check_contract()`, `Tier1Adapter` | Compares exercised services and approval paths in n8n/LangGraph code against the contract. | Static conformance |
| **Tier 2 groundwork** | `scyvera.evals` runner + `scyvera eval` CLI + the unified report envelope (`scyvera.unified`) | Runtime trace scoring: four-axis eval (constraints, approval, recovery, replay) over governed agent runs, projected into the same envelope as audit and check. | Measured conformance |
| **Runtime enforcement** | `ContractEnforcer` (`load()`, `from_declaration()`) | Gates Python calls against declared permissions and side effects with **Default-Deny**; interrupts at approval boundaries; seals contracts with SHA-256. | Execution boundary |
| **Identity pinning** | `ContractIdentity`, `verify_integrity()` | Pins the canonical path and load-time hash, refuses symlink escapes, and detects post-load path swaps. | Substitution defense (T5/T12/T14) |
| **Gateway isolation** | `BaseGateway`, `GitHubGateway`, `QdrantGateway` | Holds credentials privately and gates every external API call, structurally preventing gate bypass. | Credential & API isolation |
| **Provenance registry** | `ContractRegistry`, `RegistryEntry` | Append-only, hash-chained, versioned store. Answers what contract governed which agent at any historical moment. | Cryptographic provenance (T13) |
| **Re-seal ritual** | `reseal()` | The only sanctioned regeneration path: validate → lint → re-register → fresh sealed enforcer, with an audit record. | Authoring integrity (T12) |
| **Distribution integrity** | `self_check()`, release attestation | Verifies the installed runtime files against the signed manifest and binds the wheel to Sigstore provenance + SBOM. | Install integrity (T11) |

## Contract CLI

Create a starter contract, or inspect one you already have. The CLI detects the specification
version (`1` vs `1.1` vs `1.2`) and validates against the matching JSON Schema.

```bash
scyvera init contract.yaml --name "Research Assistant" --domain "research"
scyvera validate contract.yaml
scyvera lint contract.yaml
scyvera check contract.yaml
scyvera serve-mcp  # MCP server over stdio for agent hosts (see mcp.md)
```

```text
CREATED contract.yaml (spec version 1.1)
PASS  contract.yaml
PASS  contract.yaml (0 semantic warnings)
PASS  contract.yaml (tier 0 (structural): 0 schema errors, 0 semantic warnings)
```

`lint` runs the Tier 2 ACxxx rules: unbounded write permissions (AC101), high-risk systems without
approvals (AC201), vague idle behavior (AC301), and irreversible actions without an approval
boundary (AC302).

`check` runs the conformance tiers described in [`conformance.md`](./conformance.md). Use it in CI
in place of the two separate commands when you want one auditor-readable report.

## Runtime enforcer

The `ContractEnforcer` protects your agent's execution boundaries in Python by enforcing
**Default-Deny**: any undeclared permission or side effect raises `ContractViolationError`, and any
action requiring approval raises `ApprovalPendingError`.

### File-based contract gating

```python
from scyvera import ContractEnforcer, ContractViolationError, ApprovalPendingError

# 1. Load, validate, pin identity, and freeze contract.yaml from disk
enforcer = ContractEnforcer.load("implementations/n8n/duplicate-issue-detector/contract.yaml")

# 2. Gate sensitive tools and operations
@enforcer.gate(action_name="github:issues:write", action_type="permission")
def post_github_comment(issue_id: int, comment: str):
    print(f"Posting comment to issue #{issue_id}: {comment}")
    return True

@enforcer.gate(action_name="aws_s3:read", action_type="permission")
def read_s3_bucket():
    return "s3_data"

# 3. Allowed calls execute cleanly and log to the audit trail
post_github_comment(101, "Potential duplicate detected.")

# 4. Undeclared actions are denied immediately (Default-Deny)
try:
    read_s3_bucket()
except ContractViolationError as e:
    print(f"Blocked by Scyvera: {e}")

# 5. Inspect the immutable audit log
for entry in enforcer.get_audit_log():
    print(f"[{entry.timestamp}] {entry.decision} - {entry.action_name} ({entry.reason})")

# 6. Verify file integrity on disk (T5/T14 defense)
enforcer.verify_integrity()  # raises on modification or a post-load symlink swap
```

The pinned identity is available for inspection:

```python
identity = enforcer.contract_identity
print(identity.canonical_path)      # resolved once at load time (None for declarations)
print(identity.load_hash)           # SHA-256 of the sealed contract
print(identity.resolved_symlink)    # True if a symlink was walked at/below the addressed dir
print(identity.crosscheck)          # matches-registry / stale-registry / unregistered / ...
```

### Draft mode and promotion

A contract with `provisional: true` loads only with `mode="draft"`; full mode raises
`ProvisionalContractError` until the human promotion ritual runs. Draft mode allows declared
actions, but an **irreversible** action still requires approval even when the draft declares none
(RFC 0005 §4.2, anchor A2). Promotion is `scyvera promote`, which prints a deterministic diff,
requires reviewer + intent + confirmation, and re-seals through the same registry machinery.

### Dynamic runtime declarations (no YAML file required)

For agents created dynamically at runtime, Scyvera supports code-declared contracts with the same
enforcement guarantees:

```python
from scyvera import ContractEnforcer, DeclarationValidationError

# Declare the contract directly in Python — sealed cryptographically at creation
enforcer = ContractEnforcer.from_declaration({
    "node_id": "researcher-v1",
    "permissions": ["arxiv:read", "database:read"],
    "side_effects": ["database:write"],
    "approval_points": ["database:write"],
    "lifecycle": "request-response",
    "state": "stateless",
})

print(f"Sealed SHA-256 Digest: {enforcer.integrity_hash}")
print(f"Contract Source: {enforcer.contract_source}")  # 'declaration'

# Enforces identical default-deny rules
@enforcer.gate("arxiv:read", "permission")
def fetch_papers(topic: str):
    return ["paper1", "paper2"]

fetch_papers("quantum computing")  # Executes and logs to the audit trail
```

## Gateway enforcement architecture

In agent architectures, security boundaries fail if agents can bypass enforcers by importing and
calling raw API clients directly. Scyvera solves this with **Gateways** (`BaseGateway`,
`GitHubGateway`, `QdrantGateway`):

- **Single enforcement boundary**: API credentials and raw SDK clients (e.g. `PyGithub`,
  `qdrant-client`) are encapsulated privately within the gateway. No outside node holds credentials
  or raw clients.
- **Structural gating**: every public method is decorated per-instance with `@enforcer.gate(...)`.
  Any undeclared or unapproved action halts execution immediately via `ContractViolationError` or
  `ApprovalPendingError`.
- **Exception normalization**: client exceptions are caught and wrapped into `GatewayError` to
  ensure deterministic fault isolation.
- **CI linting**: `.github/workflows/lint-gateway.yml` scans the codebase and fails the build if any
  raw API client is imported outside `gateway.py`.

Install optional adapters with `pip install "scyvera[github]"`, `pip install "scyvera[qdrant]"`, or
`pip install "scyvera[all]"`.

```python
from scyvera import ContractEnforcer, GitHubGateway, GatewayError, ContractViolationError

# 1. Load the contract enforcer
enforcer = ContractEnforcer.load("contract.yaml")

# 2. Instantiate the gateway with an injected enforcer and private credentials
gateway = GitHubGateway(enforcer, token="YOUR_GITHUB_TOKEN")

# 3. Gated read operation (succeeds if declared in the contract)
issue = gateway.read_issue("owner/repo", issue_number=42)

# 4. Gated mutating operation (enforces Default-Deny and approvals)
try:
    gateway.close_issue("owner/repo", issue_number=42)
except ContractViolationError as e:
    print(f"Blocked by Scyvera: {e}")
```

## Contract registry: hash-chained provenance

The `ContractRegistry` is a versioned, append-only, persistent record of every contract that has
governed any agent in your ecosystem. It answers: *"What contract governed this agent at this exact
moment, and has that contract ever changed?"*

Every new entry carries `prev_hash`, the SHA-256 of the previous entry's canonical bytes (or a
fixed genesis hash). The chain is recomputable from `registry.jsonl` alone, so a break, splice,
reorder, edit, or fabricated insertion fails closed — the T13 mitigation.

```python
from scyvera import ContractEnforcer, ContractRegistry

# 1. Initialize a registry backed by a persistent JSON-lines file
registry = ContractRegistry(".scyvera/registry.jsonl")

# 2. Register an agent enforcer (idempotent on duplicate contract hash)
enforcer = ContractEnforcer.from_declaration({
    "node_id": "triage-agent-v1",
    "permissions": ["github:read"],
    "side_effects": ["github:comment"],
})
entry = enforcer.register(registry)

print(f"Registered Version: {entry.version}")
print(f"Registry Entry ID: {entry.entry_id}")
print(f"Integrity Hash: {entry.contract_hash}")
print(f"Chain Link: {entry.prev_hash}")

# 3. Recompute and verify the chain from the file alone
registry.verify_chain()  # raises RegistryError on any break

# 4. Query the latest contract for an agent
latest_entry = registry.get_latest("triage-agent-v1")

# 5. Time-travel audit query: the contract active at an exact historical timestamp
historical_entry = registry.get_at_time(
    node_id="triage-agent-v1",
    timestamp="2026-10-20T12:00:00+00:00",
)

# 6. Inspect the full version history for a node, or for a file contract by path
history = registry.get_history("triage-agent-v1")
file_history = registry.get_history_by_path("contract.yaml")

# 7. Migrate a pre-chain registry explicitly — idempotent, never silent
snapshot = registry.upgrade_chain()  # writes <registry>.prechain; None if already chained
```

Pre-chain files remain readable but refuse new `register()` calls until the explicit
`upgrade_chain()` migration. The snapshot sidecar and warning make the historical boundary explicit:
backfilled hashes prove integrity from the upgrade moment, not before it.

## Identity pinning and the re-seal ritual

`ContractEnforcer.load()` refuses contracts that escape through symlinks and pins the canonical
path at load time. When a contract changes, the supported path is `reseal()` — validate → lint with
zero errors → chain-verified register → fresh enforcer, plus a frozen audit record:

```python
from scyvera import reseal, ResealError

try:
    result = reseal("contract.yaml", ".scyvera/registry.jsonl")
except ResealError as error:
    raise SystemExit(f"re-seal refused: {error}")

enforcer = result.enforcer          # a fresh, governable enforcer
record = result.record
print(record.version, record.contract_hash, record.lint_warnings)
```

A skipped or partial registration raises `ResealError` instead of returning a governable enforcer.
`allow_unsealed_reseal=True` (default `False`) exists only for test scaffolds and documented dev
iteration.

## Programmatic contract builder

You can construct, inspect, serialize, and validate Agent Contracts in Python without writing YAML
by hand:

```python
from scyvera import Contract, validate_contract

# Programmatically construct a v1.1 Contract
contract = (
    Contract(name="Literature Research Assistant", purpose="Analyzes scientific papers")
    .set_domain("research")
    .add_capability("search_documents", description="Queries research repositories")
    .add_resource("paper_db", type="pdf_repository", access="read")
    .add_input("research_topic", type="string", required=True)
    .add_output("summary", type="document")
    .add_permission("paper_db", actions=["read", "search"])
    .set_state("session")
    .set_recovery("retry")
    .set_replay("idempotent")
    .set_observability("basic")
    .set_risk("low", category="misinformation_risk")
)

# Validate directly in code
result = contract.validate()

if result.valid:
    print("Contract is valid")
    contract.save("contract.yaml")
else:
    for err in result.errors:
        print(f"Error at {err.path}: {err.message}")
```

## Related

- Contract model: [`contract-model-v1.1.md`](./contract-model-v1.1.md),
  [`contract-reference.md`](./contract-reference.md)
- Threat models: [`threat-model-lifecycle.md`](./threat-model-lifecycle.md),
  [`threat-model-enforcer.md`](./threat-model-enforcer.md),
  [`threat-model-distribution.md`](./threat-model-distribution.md)
- MCP server mode: [`mcp.md`](./mcp.md)
