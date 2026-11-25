"""Render a PD-5 result JSON as the markdown published in ``docs/performance.md``.

The table in the document is generated, never hand-copied, so a published number
cannot drift from the stored result. ``--write`` replaces the region between the
benchmark markers in the document; the surrounding prose is not touched.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

START_MARKER = "<!-- benchmark:start -->"
END_MARKER = "<!-- benchmark:end -->"


def _format_bytes(value: int | float) -> str:
    return f"{value / (1024 * 1024):.1f}"


def _median(value: dict | None) -> float | None:
    if not value:
        return None
    return float(value["median"])


def _row(cell: dict) -> str:
    if cell.get("status") != "measured":
        return (
            f"| {cell['files']:,} | {cell['profile']} | — | — | — | — | "
            f"not measured | — | — | — | — |"
        )

    end = cell["end_to_end_ms"]
    scan = cell["scan_ms"]
    rss = cell.get("peak_rss_mb") or {}
    ratio = end["p95"] / end["median"] if end["median"] else float("nan")
    return (
        f"| {cell['files']:,} | {cell['profile']} | {cell['files_scanned']:,} | "
        f"{cell['files_skipped']:,} | {_format_bytes(cell['bytes_scanned'])} | "
        f"{cell['findings']} | {end['median']:.0f} | {end['p95']:.0f} | "
        f"{ratio:.2f} | {scan['median']:.0f} | "
        f"{(rss.get('median') or float('nan')):.1f} |"
    )


def _environment_lines(environment: dict, protocol: dict) -> list[str]:
    dirty = " (worktree had uncommitted tracked changes)" if environment.get("worktree_dirty") else ""
    return [
        f"- **Measured:** {environment['measured_at']}",
        f"- **Commit:** `{environment['commit']}`{dirty}",
        f"- **scyvera:** {environment['scyvera_version']} · "
        f"**Python:** {environment['python']} ({environment['python_implementation']})",
        f"- **OS:** {environment['os_build']}",
        f"- **CPU:** {environment['cpu']} ({environment['cpu_count']} logical cores)",
        f"- **RAM:** {environment['ram_gb']} GB total · "
        f"**Disk free at measurement:** {environment['disk_free_gb']} GB · "
        f"**Filesystem:** {environment['filesystem']}",
        f"- **Runs:** {protocol['repeats']} timed end-to-end runs after 1 discarded "
        f"warm-up; {protocol['scan_repeats']} in-process scans after 1 discarded warm-up",
        f"- **Cache:** {protocol['cache_state']}",
        f"- **Command:** `{protocol['command']}`",
        f"- **Corpus seed:** {protocol['corpus_seed']}",
    ]


def render_markdown(result: dict) -> str:
    cells = result.get("cells") or []
    environment = result.get("environment") or {}
    protocol = result.get("protocol") or {}

    lines = [
        "### Measured results",
        "",
        "| files | profile | scanned | skipped | MiB scanned | findings | "
        "e2e median (ms) | e2e p95 (ms) | p95/median | scan median (ms) | "
        "peak RSS median (MiB) |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    lines.extend(_row(cell) for cell in cells)
    lines.append("")

    missing = [cell for cell in cells if cell.get("status") != "measured"]
    if missing:
        lines.append("**Not measured:**")
        lines.append("")
        for cell in missing:
            lines.append(
                f"- `{cell['profile']}` at {cell['files']:,} files — "
                f"{cell.get('reason', 'unknown')}: {cell.get('detail', '')}"
            )
        lines.append("")

    lines.append("### Environment")
    lines.append("")
    lines.extend(_environment_lines(environment, protocol))
    lines.append("")
    return "\n".join(lines)


def write_document(document: Path, block: str) -> None:
    text = document.read_text(encoding="utf-8")
    if START_MARKER not in text or END_MARKER not in text:
        raise SystemExit(
            f"{document} is missing the {START_MARKER} / {END_MARKER} markers"
        )
    before, _, rest = text.partition(START_MARKER)
    _, _, after = rest.partition(END_MARKER)
    document.write_text(
        f"{before}{START_MARKER}\n\n{block}\n{END_MARKER}{after}",
        encoding="utf-8",
        newline="\n",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a PD-5 benchmark result as markdown.")
    parser.add_argument("result", type=Path, help="result JSON written by benchmarks/run.py")
    parser.add_argument(
        "--write",
        type=Path,
        default=None,
        help="replace the benchmark block in this markdown document",
    )
    args = parser.parse_args(argv)

    result = json.loads(args.result.read_text(encoding="utf-8"))
    block = render_markdown(result)
    if args.write is not None:
        write_document(args.write, block)
        print(f"updated {args.write}")
    else:
        print(block)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
