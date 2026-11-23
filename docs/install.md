# Install, verify, and troubleshoot

## Install

```bash
pip install scyvera

# Optional adapters, only if you use the gated gateways
pip install "scyvera[github]"     # PyGithub
pip install "scyvera[qdrant]"     # qdrant-client
pip install "scyvera[all]"        # both
```

Scyvera is a pure-Python wheel (`py3-none-any`): no compiler, no native extension, no OS-specific
build step.

| Platform | Status | Notes |
|---|---|---|
| **Windows 10/11** | tested in CI | Narrow-console safe: the report falls back from `—` to `->` on cp437/cp850. Symlink tests skip where the OS denies link creation. |
| **Linux** | tested in CI | `ubuntu-latest`, all supported Python versions. |
| **macOS** | tested in CI | `macos-latest` on Python 3.10 and 3.14 on every PR — the OS-specific behaviour (paths, default case-insensitive APFS, NFD filenames, symlinks) is a property of the platform, not the interpreter minor, and the arm64 hosted pool is capacity-constrained. Minors 3.11–3.13 run in the nightly `macos-extended.yml`, so every supported version is covered on macOS. |
| **Python** | 3.10 – 3.14 | 12 cells per pull request (3 operating systems × 5 Python versions, minus the three macOS minors that Linux and Windows already cover) with `fail-fast: false`. The nightly macOS job runs those three, so the full 15 cells are covered daily. |

From a checkout instead:

```bash
git clone https://github.com/Skull-boy/scyvera.git
cd scyvera
pip install -e ".[dev]"
scyvera audit .
```

## Verify the installed distribution

The command that makes an install self-checking:

```bash
scyvera self-check
```

```text
PASS  self-check  scyvera 1.4.0
      manifest: 1
      verified: 37 files
```

`self-check` verifies the **installed** package — never the current directory — against the
`_self_manifest.json` shipped inside the wheel. It resolves the package through
`importlib.resources`, cross-checks the manifest version against installed distribution metadata,
and fails closed:

- a **modified** runtime file (any byte change) fails and is named;
- a **missing** listed file fails;
- an **unlisted addition** fails — a dropped-in module override is tampering surface
  (T5-consistent);
- a missing, malformed, or unsupported manifest is **unverifiable**, not silently OK.

Exit codes are deliberate:

| Code | Meaning |
|---|---|
| `0` | Every listed file matches; no unlisted additions. |
| `1` | A verifiable manifest disagrees with the installed files, or manifest/installed versions differ. |
| `2` | Unverifiable: missing/malformed/unsupported manifest, or an IO/installed-distribution problem. A pre-manifest install is `2`, not `1`. |

Machine-readable output:

```bash
scyvera self-check --json
```

The JSON report is `self_check_version: 1` and uses the same conventions as the audit report
(deterministic, no timestamps).

## Signed releases and the attestation bundle

Every tag release is attested with Sigstore build provenance. The release page carries:

| Artifact | What it proves |
|---|---|
| `scyvera-<version>-py3-none-any.whl` | The exact wheel published to PyPI. |
| `scyvera.cdx.json` | A deterministic CycloneDX **1.5** SBOM: scyvera, its declared runtime dependencies, and optional `pydantic` when present. |
| `release-manifest.json` | RFC 0003 §C6 bundle binding `{wheel_hash, schema_version, adapter_floors, self_check_manifest}`. |

The attested wheel is the published wheel **by construction**: the attestation workflow downloads
the completed publish run's `dist` artifact instead of rebuilding, installs that wheel in a clean
venv, regenerates the self manifest from the installed tree, runs `scyvera self-check` as a gate,
and signs the result. It never attests bytes that were not uploaded.

Verify a download yourself:

```bash
gh attestation verify dist/scyvera-<version>-py3-none-any.whl \
  --repo Skull-boy/scyvera
```

## Troubleshooting installs

Start with the version the command actually resolves:

```bash
scyvera --version
```

**Symptom:** `pip install` (git or PyPI) completes, but old commands or old behavior remain.

**Cause:** pip's satisfied-check or wheel cache reused a pre-existing wheel.

**Fix:** remove the old distribution twice (metadata and the launcher can live in different places),
then force a fresh install:

```bash
pip uninstall -y scyvera
pip uninstall -y scyvera
pip install --force-reinstall --no-deps --no-cache-dir <url>
```

**Symptom:** multiple `scyvera.exe` launchers on `PATH`, and the wrong one answers.

**Cause:** an earlier install (system Python, another venv, or a user-site shim) comes first.

**Fix:** list the candidates, activate the intended environment, and reinstall there. The first hit
wins.

```powershell
where.exe scyvera
```
