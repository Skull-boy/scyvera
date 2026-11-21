# README rework plan

> Status: **implemented on 2026-11-21**, kept as the decision record. Deviations from the plan are
> noted inline: the hero uses the Scyvera mark as SVG (not the GIF), the layer diagram was dropped
> in favour of the flow diagram, and the demo GIF re-encoded to 2.6 MB rather than 2.0 MB to keep
> 7 fps instead of 14 → 5.
>
> Goal: turn the README from a 784-line manual into a landing page that a stranger reads in 60
> seconds, while every removed word lands in a docs page instead of disappearing.

---

## 1. What the current README costs

Measured on 2026-11-21 (`README.md`, 784 lines):

| Block | Lines | Words | Share |
|---|---:|---:|---:|
| Hero, badges, status blockquote | 34 | 205 | 4% |
| 2-minute demo (5 sub-steps) | 106 | 538 | 10% |
| Install, verify, attestation, troubleshooting | 113 | 599 | 11% |
| Conformance + eval scoring | 63 | 524 | 10% |
| Governing for Real (Python API tutorials) | 250 | 1421 | **27%** |
| What this is / what it does not guarantee | 30 | 327 | 6% |
| Domain-neutral example contracts | 15 | 129 | 2% |
| Documentation map | 24 | 190 | 4% |
| Repository structure | 85 | 630 | **12%** |
| Status & roadmap | 31 | 513 | 10% |
| Running tests | 17 | 148 | 3% |
| Contributing / license | 13 | 78 | 1% |
| **Total** | **784** | **5308** | |

The two biggest blocks (Governing + Repository structure = 335 lines, 39%) are reference material,
not a pitch. The status blockquote alone is 12 lines of prose before a visitor sees anything they
can run.

---

## 2. What well-run OSS READMEs actually look like

Fetched and measured on 2026-11-21 (raw `README.md` from each repository's default branch):

| Project | Category | Lines | Words | What the README is |
|---|---|---:|---:|---|
| `shadcn-ui/ui` | UI toolkit | 17 | 58 | A pointer: docs, contributing, license |
| `colinhacks/zod`, `vercel/ai`, `biomejs/biome` | libs / tools | ~1 | ~1 | One line + link to the docs site |
| `langchain-ai/langgraph` | agent framework | 82 | 601 | Why + ecosystem + docs links |
| `slsa-framework/slsa` | **standard** | 85 | 403 | What SLSA is, what's in the repo, how to get involved |
| `open-policy-agent/opa` | **policy engine** | 109 | 929 | What it is, get started, community, how it works |
| `modelcontextprotocol/python-sdk` | **protocol SDK** | 126 | 470 | Docs pointer, what MCP is, install, "a server in 15 lines" |
| `trpc/trpc` | framework | 199 | 799 | Intro, features, quickstart, team, sponsors |
| `open-telemetry/collector` | **standard + runtime** | 226 | 1073 | Community, stability, compatibility, contributing |
| `astral-sh/uv` | **CLI tool** | 326 | 1080 | Pitch + hero image, highlights, install, features, docs |
| `oven-sh/bun` | runtime | 448 | 2064 | Docs pointer, what, install, guides |
| `BurntSushi/ripgrep` | CLI tool | 541 | 2874 | Deep comparison content (an outlier; the product's value *is* comparison) |
| `sigstore/cosign` | security tool | 793 | 3906 | Recipe book (an outlier) |
| **Scyvera today** | standard + tool + runtimes | **784** | **5308** | Everything above at once |

**The median of projects comparable to Scyvera is 85–230 lines, 400–1100 words.** Scyvera is 3–6×
that, and sits in the range of the two outliers whose value proposition is exhaustive recipes.

### The seven patterns that repeat

1. **The docs site (or `docs/`) owns depth; the README owns the first minute.** zod, vercel/ai and
   biome ship a one-line README. shadcn/ui ships 58 words. This is not laziness — it is a deliberate
   split: README converts, docs teach.
2. **First screen = name, one sentence, badges, visual.** uv: one sentence ("An extremely fast
   Python package and project manager, written in Rust"), then a centred benchmark image, then
   "Highlights". MCP SDK: name, one bold line, six badges, then a docs pointer.
3. **"What is X?" is 2–4 sentences, not a page.** OPA spends ~5 paragraphs on *how the model works*
   and links out for everything else. SLSA: three sentences.
4. **A capability list is links, not tutorials.** uv's Highlights is 11 one-line bullets, each
   linking to a section or doc. Scyvera's equivalents are 250 lines of Python API walkthroughs.
5. **One runnable example beats five.** MCP SDK has "A server in 15 lines" and "A client in 10
   lines" — exactly two. OPA links to a playground. Nobody pastes their whole API surface.
6. **Proof is specific and machine-checkable.** Badges + version + CI status + (where real) "used
   in production". No project in the sample invents logos or benchmarks.
7. **Repository structure, roadmap, and test instructions live elsewhere.** Not one of the sampled
   READMEs contains a directory tree. Roadmaps are a link (OPA → a GitHub project; SLSA → links).
   Test instructions live in `CONTRIBUTING.md`.

Two outliers confirm the rule: ripgrep and cosign are long **because their value is comparative
detail and recipes**. Scyvera's value is a *model* — which a diagram and one contract explain
faster than 1400 words of API.

---

## 3. What the README should say, in order

Target: **240–270 lines, ~1200–1500 words**, of which roughly half is code and diagrams.

| # | Section | Budget | Content |
|---|---|---:|---|
| 1 | Header | ~15 lines | Logo (small), `# Scyvera`, one-sentence pitch, 6 badges, hero visual |
| 2 | What is Scyvera? | ~12 lines | 3 bullets: the layer above MCP/A2A; scan→draft→enforce→prove; one standard, three runtimes. Then one sentence on who it is for |
| 3 | 30-second proof | ~20 lines | `pip install scyvera && scyvera audit .` with the **real** output (84/100 Controlled, one AU-CI-002 line) |
| 4 | Quickstart | ~45 lines | install → scan → draft (8-line contract) → gate → MCP in one line. Code-first, no prose between steps |
| 5 | Capabilities | ~25 lines | 9 rows, table or cards: audit, contracts/packs, conformance, enforcer, guardrails, trace+evals, registry, MCP, CI action + skill + kits. Each row: 6–10 words + doc link |
| 6 | How it works | ~10 lines + diagram | Scan → Draft → Enforce → Prove, with the layer diagram next to it |
| 7 | Runtimes | ~12 lines | Table: Python (reference, PyPI 1.4.0), TypeScript (npm 0.1.1), Rust (`0.1.0`, source; **not yet published**), each with conformance 33/33 at suite v1 |
| 8 | Proof, not promises | ~15 lines | The two pinned numbers (33/33 vectors, 84/100 dogfood covenant), SLSA provenance on the wheel, `self-check` 37 files, CI badge. No drifting test counts |
| 9 | Honest limits | ~12 lines | Keep the existing "what it does not guarantee" bullets, trimmed to four |
| 10 | Documentation | ~12 lines | 8 links: install, Python API, conformance, evals, MCP, registry, threat models, roadmap |
| 11 | Contributing | ~10 lines | One paragraph + quickstart for contributors + "add your runtime / add yourself to ADOPTERS" |
| 12 | License | ~3 lines | MIT |

### Explicit cuts (and where each lands)

| Cut from README | Destination |
|---|---|
| 2-minute demo steps b–e | `docs/quickstart.md` (new); keep step a inline |
| Install matrix, platform notes, `self-check`, signed-release/attestation, troubleshooting | `docs/install.md` (new) |
| Conformance tiers + eval scoring | `docs/conformance.md` (new); eval detail already in `docs/evals.md` |
| Entire "Governing for Real" API walkthrough (enforcer, dynamic declarations, gateways, registry, identity/re-seal, builder) | `docs/python-api.md` (new) |
| Three domain-neutral example contracts | `docs/contract-reference.md` (extend) |
| Repository structure tree | `CONTRIBUTING.md` → "Repository layout" |
| Status & roadmap block | `docs/roadmap.md` (append "Current status") |
| Running tests / gates | `CONTRIBUTING.md` (already has the gate list) |
| 11 badges → 6 | license, PyPI, npm, CI, docs, blast radius |

**One deliberate exception to "remove the example contract":** the Quickstart keeps a **10-line
contract**. A governance product that never shows its artifact is asking to be misunderstood. It is
the smallest possible version — `version`, `system`, `permissions`, `side_effects`, one approval —
and it links to the reference for the rest.

---

## 4. Visuals

The README currently has one image (a 3.9 MB GIF). The plan adds three, all committed as text
(SVG) or small binaries, all with absolute URLs so PyPI renders them:

| Asset | Format | Purpose |
|---|---|---|
| `assets/scyvera-mark.svg` | traced SVG of the existing mark | The hero image, vectorised from `scyvera.png`; sharp at any size, 171 KB instead of 797 KB |
| `assets/hero-flow.svg` | hand-authored SVG | The 4-step loop: **Scan → Draft → Enforce → Prove**. This is the "aha" in one image |
| `assets/social-preview.png` | 1280×640 PNG | GitHub repo social preview + link unfurls (repo setting, not in README) |
| `scyvera-demo.gif` | re-encoded 14 → 7 fps, 3.9 → 2.6 MB | Keeps the demo below the hero; the poster fallback was dropped because GitHub cannot use it |

The layer diagram proposed in the first draft was dropped: the pitch sentence already says "the
layer above MCP and A2A", and a second diagram would repeat it.

Why SVG for the diagrams: crisp at any zoom, diff-able in review, and no image-generation
artifacts to defend. The mark is a colour trace of the existing render, so the brand does not
change. Mermaid is rejected because PyPI does not render it (and `pyproject.toml` publishes the
README to PyPI).

---

## 5. Growth beyond the README (honest levers only)

| Lever | Action | Why |
|---|---|---|
| Repo metadata | Description: *"Operational contracts for AI agents: scan, draft, enforce, prove."* Topics: `agent-contracts`, `ai-agents`, `agent-governance`, `mcp`, `policy-as-code`, `llm-security`, `guardrails`, `runtime-enforcement`, `conformance`, `python`, `typescript`, `rust` | GitHub search and topic pages are a real discovery path |
| Social preview | Upload the 1280×640 card | Every shared link becomes an ad |
| Badges | 6, all live badges (PyPI, npm, CI, license, docs, blast radius) | 11 badges is visual noise; 6 reads as confidence |
| Runtimes table | Three runtimes, one conformance number, honest Rust status | "One standard, three native runtimes" is the most distinctive fact about the project |
| `ADOPTERS.md` | Create empty-with-invitation | The OPA pattern: a home for adopters before there are any |
| Star history | Optional `star-history.com` chart in a footer `<details>` | Used by tRPC; cheap, honest, non-blocking |
| Contributor path | Link `good first issue` + the two doc gaps created by this plan | Turns the README rewrite into onboarding work |

**Not doing:** logo walls, "trusted by", benchmark charts, or star-count bragging until they are
real. The project's credibility is that its claims are machine-checked; a fake logo would spend it.

---

## 6. Constraints the build must respect

1. **PyPI rendering.** `pyproject.toml` sets `readme = "README.md"`, so every image must use an
   absolute URL (`https://raw.githubusercontent.com/Skull-boy/scyvera/main/assets/...`). Relative
   `assets/...` paths already break on PyPI today.
2. **Anchors.** Two badges link to `#-the-2-minute-demo` and `#-install-and-platform-support`.
   New headings change anchors; update the badges in the same commit.
3. **Dogfood covenant.** The README is scanned by `scyvera audit .`; the scored set is pinned at
   seven findings and 84/100. Re-run the audit after the rewrite; a new scored finding means the
   rewrite introduced a capability claim in code, not that the covenant should move.
4. **Pinned numbers only.** The proof strip may cite `33/33` (suite v1) and `84/100 Controlled`
   (covenant) because tests enforce them. Raw test counts (`925 passed`) drift monthly and are
   banned from the README; the CI badge covers "is it green".
5. **Honest Rust status.** `scyvera-rs` is built and CI-green but **not on crates.io**. The runtime
   table says so, and the Quickstart does not offer `cargo install` until it does.

---

## 7. Build plan (one PR, four commits)

1. **`docs: extract the README's reference material`**
   New: `docs/install.md`, `docs/python-api.md`, `docs/conformance.md`, `docs/quickstart.md`.
   Extended: `docs/contract-reference.md` (examples), `docs/roadmap.md` (current status),
   `CONTRIBUTING.md` (repository layout + test gates). Content moved verbatim first, then edited.
2. **`docs: rewrite the README as a landing page`**
   The 12-section structure above, 240–270 lines, absolute image URLs, 6 badges, corrected anchors.
3. **`assets: add the flow and layer diagrams; re-encode the demo`**
   Two SVGs, the poster, the compressed GIF, the social-preview PNG.
4. **`docs: add ADOPTERS.md and the contributor path`**
   Empty-with-invitation adopters file, `good first issue` links.

Manual, non-repo steps listed in the PR body: GitHub description, topics, social preview upload.

### Acceptance

- README ≤ 270 lines, ≤ 1500 words, no section over 40 lines except Quickstart.
- First 20 lines contain the name, the pitch, the badges, and a visual.
- Every capability row links to a doc page that exists.
- `pytest tests/ -q` green; `scyvera audit . --fail-under 84` still 84/100 `Controlled`.
- All image links absolute; `twine check`/PyPI preview shows no broken image.
- No directory tree, no roadmap table, no API tutorial in the README.

### Open choices for you

1. **Pitch.** Keep *"Set the boundary once. Get it enforced everywhere. Prove it forever."* or move
   to a plain-language first line (*"Operational contracts for AI agents"*) with the three-beat line
   as the subhead? The research says the plain description first, poetry second.
2. **Hero visual.** 4-step flow diagram, or the demo GIF as the hero with the flow diagram in "How
   it works"? (GIF-first is more convincing; SVG-first is faster and works on PyPI.)
3. **Docs site.** Stay with GitHub-rendered `docs/`, or add MkDocs Material later? The plan assumes
   GitHub-rendered docs, which is why every link is a repo path.
