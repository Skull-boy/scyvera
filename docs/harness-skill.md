# Harness skill: `scyvera-governance` (M3.1)

`skills/scyvera-governance/` packages Scyvera's governance workflow as an
installable skill for agent harnesses. The skill teaches an agent to run the
deterministic CLI and MCP tools and to report their verdicts unchanged. It
does not give the agent governance authority.

## What is in the package

| Path | Purpose |
|---|---|
| `SKILL.md` | Front-matter plus the invocation rules, command map, MCP path, and the three NEVERs. |
| `contract.yaml` | The skill's own v1.1 contract: reads repository/contract files, writes one draft, no approval path. It validates at Tier 0. |
| `reference/finding-codes.md` | Every `AU-xxx`, `ACxxx`, and `T1xx` code with its engine severity and meaning. |
| `reference/exit-codes.md` | The `0`/`1`/`2` table for every command. |
| `scripts/audit.sh` | POSIX wrapper that runs `scyvera audit` and preserves its exit code. |
| `scripts/audit.ps1` | PowerShell wrapper with the same behavior. |

`skills-registry.json` at the repository root hash-locks every file.

## Install into a harness

Copy the directory into the harness's skills path, keeping the directory name. Every host below
reads the same `SKILL.md`:

| Host | Project path | Global path | Invoke with |
|---|---|---|---|
| **Claude Code** | `.claude/skills/scyvera-governance/` | `~/.claude/skills/scyvera-governance/` | `/scyvera-governance` |
| **Codex** | `.agents/skills/scyvera-governance/` (scanned from the working directory up to the repository root) | `~/.agents/skills/scyvera-governance/` | `$scyvera-governance` |
| **OpenCode** | `.opencode/skills/scyvera-governance/` (also reads `.agents/skills/` and `.claude/skills/`) | `~/.config/opencode/skills/scyvera-governance/` | `@scyvera-governance` |
| **Antigravity** | `.agents/skills/scyvera-governance/` | `~/.gemini/config/skills/scyvera-governance/` | `/scyvera-governance` |

```bash
git clone --depth 1 https://github.com/Skull-boy/scyvera /tmp/scyvera

cp -R /tmp/scyvera/skills/scyvera-governance .agents/skills/   # Codex, OpenCode, Antigravity
cp -R /tmp/scyvera/skills/scyvera-governance .claude/skills/    # Claude Code
```

On Windows, copy the folder by hand. Then:

1. Confirm the host discovers `SKILL.md` and its `name` / `description` front-matter.
2. Make sure `scyvera` is installed and on `PATH` (`scyvera --version`). The skill calls the CLI
   and the MCP server; it does not bundle a runtime.

The skill directory is self-contained. It has no network calls, no secrets, no
`sudo`, and no code that imports the scanned target.

## Verify the lock

```bash
python -m tools.lock_skill --verify
```

- Exit `0`: every locked file recomputes to the recorded SHA-256.
- Exit `1`: drift. The output names each `modified`, `missing`, or `unlisted`
  file. Do not install a drifting copy until the change is reviewed.
- Exit `2`: the registry is missing, unreadable, or an unsupported version.

After an intentional skill edit, refresh the lock and commit both:

```bash
python -m tools.lock_skill
git add skills/scyvera-governance skills-registry.json
```

The registry is deterministic: sorted keys, repo-relative POSIX paths, no
timestamps, no hostnames. Two runs over the same tree are byte-identical.

## The lock format

`skills-registry.json` follows the ecosystem shape already used by
`skills-lock.json`: a top-level `version` and a `skills` map keyed by skill
name, with `source`, `sourceType`, `skillPath`, and `computedHash`. It adds a
per-file `files` map plus `version` and `locked_at_version` so verification can
localize drift instead of only reporting "the skill changed". `computedHash` is
the SHA-256 of `SKILL.md` (the entry point).

## Honest scope note

The skill guides tool **use**; enforcement still lives in the engines. A
misbehaving agent is caught by the same exit codes it is taught to respect:
`1` for a finding or failed verdict, `2` for usage, IO, or unverifiable input.
The skill cannot make an engine pass, cannot lower a severity, and cannot
execute scanned code. Hash-locking closes artifact substitution for the skill
files; it is not a sandbox and does not protect a compromised host. Scyvera
remains beta-serious, not production-certified.

The skill's bundled `contract.yaml` is reflexive: the same Tier 0 check the
skill teaches is run against the skill itself.
