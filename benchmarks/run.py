"""PD-5 benchmark harness: measure ``scyvera audit`` on synthetic repositories.

The protocol is stated in ``docs/performance.md`` and implemented here, not the
other way round. Every cell is verified before its number is trusted: the parsed
report must account for exactly the files and bytes the generator created, and
two consecutive ``--json`` runs must be byte-identical. A fast number from a
broken scan is the one failure mode that would make this benchmark worse than
no benchmark.

Nothing is optimized, and no flag is added to ``scyvera audit``. This module
spawns the published CLI exactly as a CI user would.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):  # ``python benchmarks/run.py``
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmarks import gen_corpus  # noqa: E402
from scyvera.audit import (  # noqa: E402
    BINARY_SNIFF_BYTES,
    MAX_FILE_BYTES,
    SKIP_DIRS,
    scan_tree,
)

SCHEMA_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = Path(__file__).resolve().parent / "results"

AUDIT_COMMAND = (sys.executable, "-m", "scyvera.cli", "audit", "{tree}", "--json")


# ---------------------------------------------------------------------------
# statistics
# ---------------------------------------------------------------------------


def percentile(values: list[float], q: float) -> float:
    """Linear-interpolation percentile (the numpy ``linear`` definition)."""
    if not values:
        raise ValueError("percentile of an empty sample")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = q * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def summarize(values: list[float]) -> dict[str, float | int | list[float]]:
    return {
        "samples": [round(value, 3) for value in values],
        "min": round(min(values), 3),
        "median": round(statistics.median(values), 3),
        "p95": round(percentile(values, 0.95), 3),
        "max": round(max(values), 3),
        "count": len(values),
    }


# ---------------------------------------------------------------------------
# peak resident memory (stdlib + ctypes only)
# ---------------------------------------------------------------------------


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _windows_peak_rss_mb(handle: int) -> float | None:
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    ok = psapi.GetProcessMemoryInfo(
        ctypes.c_void_p(int(handle)),
        ctypes.byref(counters),
        counters.cb,
    )
    if not ok:
        return None
    return counters.PeakWorkingSetSize / (1024 * 1024)


def _linux_vm_hwm_mb(pid: int) -> float | None:
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        return None
    return None


class _PeakRssMonitor:
    """Read the child's high-water RSS while it runs, or after it exits.

    Windows exposes ``PeakWorkingSetSize`` as an OS-maintained high-water mark,
    and Linux exposes ``VmHWM`` the same way, so a single successful read is
    enough; a poller is used on Linux because ``/proc/<pid>`` disappears at
    exit. macOS has no per-pid equivalent available without extra tooling, so
    :func:`_macos_children_peak_mb` reports the ``RUSAGE_CHILDREN`` high-water
    mark and the doc labels it as such.
    """

    def __init__(self, process: subprocess.Popen) -> None:
        self.process = process
        self._stop = threading.Event()
        self._value: float | None = None
        self._thread: threading.Thread | None = None
        if sys.platform.startswith("linux"):
            self._thread = threading.Thread(target=self._poll_linux, daemon=True)
            self._thread.start()

    def _poll_linux(self) -> None:
        pid = self.process.pid
        while not self._stop.is_set():
            value = _linux_vm_hwm_mb(pid)
            if value is not None and (self._value is None or value > self._value):
                self._value = value
            time.sleep(0.005)

    def finish(self) -> float | None:
        if sys.platform.startswith("win"):
            return _windows_peak_rss_mb(self.process._handle)  # type: ignore[attr-defined]
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        return self._value


def _macos_children_peak_mb() -> float | None:
    if sys.platform != "darwin":
        return None
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    except Exception:
        return None
    # macOS reports bytes; Linux reports KiB. This is macOS-only, so divide once.
    return peak / (1024 * 1024)


# ---------------------------------------------------------------------------
# environment block
# ---------------------------------------------------------------------------


def _windows_cpu_name() -> str | None:
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
        )
        with key:
            return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
    except Exception:
        return None


def _linux_cpu_name() -> str | None:
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as handle:
            for line in handle:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        return None
    return None


def _ram_gb() -> float | None:
    try:
        if sys.platform.startswith("win"):
            class _MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MemoryStatus()
            status.dwLength = ctypes.sizeof(status)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return None
            return round(status.ullTotalPhys / (1024 ** 3), 1)
        if sys.platform.startswith("linux"):
            with open("/proc/meminfo", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("MemTotal:"):
                        return round(int(line.split()[1]) / (1024 ** 2), 1)
        if sys.platform == "darwin":
            import subprocess as _subprocess

            out = _subprocess.run(
                ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True
            ).stdout.strip()
            return round(int(out) / (1024 ** 3), 1)
    except Exception:
        return None
    return None


def _os_build() -> str:
    if sys.platform.startswith("win"):
        release, version, service_pack, _ = platform.win32_ver()
        return f"Windows {release} {version} {service_pack}".strip()
    if sys.platform.startswith("linux"):
        pretty = ""
        try:
            with open("/etc/os-release", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("PRETTY_NAME="):
                        pretty = line.split("=", 1)[1].strip().strip('"')
        except OSError:
            pretty = ""
        return f"{pretty} (kernel {platform.release()})".strip()
    return platform.platform()


def _git_commit() -> tuple[str, bool]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=no"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
        return commit, dirty
    except Exception:
        return "unknown", False


def _package_version() -> str:
    try:
        from importlib.metadata import version

        return version("scyvera")
    except Exception:
        try:
            import scyvera

            return str(getattr(scyvera, "__version__", "unknown"))
        except Exception:
            return "unknown"


def collect_environment(repeats: int, scan_repeats: int) -> dict[str, object]:
    commit, dirty = _git_commit()
    cpu = (
        _windows_cpu_name()
        or _linux_cpu_name()
        or platform.processor()
        or platform.machine()
    )
    usage = shutil.disk_usage(REPO_ROOT)
    return {
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "os": platform.platform(),
        "os_build": _os_build(),
        "cpu": cpu,
        "cpu_count": os.cpu_count(),
        "ram_gb": _ram_gb(),
        "disk_free_gb": round(usage.free / (1024 ** 3), 1),
        "filesystem": "not probed",
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "scyvera_version": _package_version(),
        "commit": commit,
        "worktree_dirty": dirty,
        "repeats": repeats,
        "scan_repeats": scan_repeats,
        "cache_state": "warm (filesystem cache not dropped)",
    }


# ---------------------------------------------------------------------------
# verification
# ---------------------------------------------------------------------------


def tree_bytes(root: Path) -> tuple[int, int]:
    """Return ``(scanned_bytes, skipped_bytes)`` using the scanner's own rules."""
    scanned = skipped = 0
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        kept: list[str] = []
        for dirname in sorted(dirnames):
            if dirname in SKIP_DIRS:
                continue
            if (Path(dirpath) / dirname).is_symlink():
                continue
            kept.append(dirname)
        dirnames[:] = kept

        for filename in sorted(filenames):
            path = Path(dirpath) / filename
            if path.is_symlink():
                continue
            size = path.stat().st_size
            if size > MAX_FILE_BYTES:
                skipped += size
                continue
            with path.open("rb") as handle:
                head = handle.read(BINARY_SNIFF_BYTES)
            if b"\x00" in head:
                skipped += size
            else:
                scanned += size
    return scanned, skipped


class CellInvalid(RuntimeError):
    """A run disagreed with the corpus; the number must not be published."""


def _run_audit(tree: Path) -> tuple[float, float | None, bytes, str, int]:
    command = [part.format(tree=str(tree)) for part in AUDIT_COMMAND]
    environment = dict(os.environ)
    environment["PYTHONHASHSEED"] = "0"

    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
    )
    monitor = _PeakRssMonitor(process)
    stdout, stderr = process.communicate()
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    peak_mb = monitor.finish()

    # Without --fail-under the house exit codes are 0 (no scored finding) and
    # 1 (findings); 2 is reserved for usage errors. Both 0 and 1 are valid here,
    # and the caller cross-checks the code against the parsed payload.
    if process.returncode not in (0, 1):
        raise CellInvalid(
            f"audit exited {process.returncode}: {stderr.decode('utf-8', 'replace')[:400]}"
        )

    if peak_mb is None:
        peak_mb = _macos_children_peak_mb()
    return elapsed_ms, peak_mb, stdout, stderr.decode("utf-8", "replace"), process.returncode


def measure_cell(
    profile: str,
    files: int,
    seed: int,
    repeats: int,
    scan_repeats: int,
    budget_seconds: float,
    work_root: Path,
    *,
    keep: bool,
) -> dict[str, object]:
    """Measure one (profile, scale) cell, or record why it was not measured."""
    tree = work_root / f"{profile}-{files}"
    spec = gen_corpus.generate(tree, files, profile, seed)
    scanned_bytes, skipped_bytes = tree_bytes(tree)

    cell: dict[str, object] = {
        "profile": profile,
        "files": files,
        "seed": seed,
        "corpus": spec.to_dict(),
        "bytes_verified": {
            "scanned": scanned_bytes,
            "skipped": skipped_bytes,
            "matches_generator": (
                scanned_bytes == spec.bytes_scanned
                and skipped_bytes == spec.bytes_skipped
            ),
        },
    }

    try:
        if not cell["bytes_verified"]["matches_generator"]:  # type: ignore[index]
            raise CellInvalid(
                "generator and harness disagree on scanned/skipped bytes: "
                f"generator {(spec.bytes_scanned, spec.bytes_skipped)}, "
                f"harness {(scanned_bytes, skipped_bytes)}"
            )

        # One discarded warm-up. Its time is recorded only to project the budget;
        # it never contributes to a published statistic.
        warmup_ms, _, warmup_out, _, warmup_code = _run_audit(tree)
        runs = repeats + scan_repeats
        projected_seconds = (warmup_ms / 1000.0) * runs
        cell["warmup_ms"] = round(warmup_ms, 3)

        if projected_seconds > budget_seconds:
            cell.update(
                {
                    "status": "not_measured",
                    "reason": "budget_exceeded",
                    "detail": (
                        f"one warm-up run took {warmup_ms:.0f} ms; "
                        f"{runs} runs project to {projected_seconds:.0f} s, "
                        f"above the {budget_seconds:.0f} s per-cell budget"
                    ),
                }
            )
            return cell

        warmup_payload = json.loads(warmup_out.decode("utf-8"))
        cell["findings"] = len(warmup_payload["findings"])
        cell["governed"] = int(warmup_payload.get("governed_count", 0))
        cell["score"] = warmup_payload["score"]

        # The CLI without --fail-under exits 0 when nothing is scored and 1 when
        # something is. Pin that against the payload so a broken run cannot hide
        # behind a valid-looking JSON body.
        expected_code = 0 if not any(
            finding.get("scored", True) for finding in warmup_payload["findings"]
        ) else 1
        if warmup_code != expected_code:
            raise CellInvalid(
                f"exit code {warmup_code} disagrees with the payload "
                f"(expected {expected_code})"
            )

        # Verify the warm-up report against the corpus before trusting anything.
        if warmup_payload["stats"]["files_scanned"] != spec.files_scanned:
            raise CellInvalid(
                "files_scanned mismatch: report "
                f"{warmup_payload['stats']['files_scanned']}, corpus {spec.files_scanned}"
            )
        if warmup_payload["stats"]["files_skipped"] != spec.files_skipped:
            raise CellInvalid(
                "files_skipped mismatch: report "
                f"{warmup_payload['stats']['files_skipped']}, corpus {spec.files_skipped}"
            )
        rule_ids = sorted({finding["rule_id"] for finding in warmup_payload["findings"]})
        cell["rule_ids"] = rule_ids
        if profile == "clean" and rule_ids:
            raise CellInvalid(f"clean corpus produced findings: {rule_ids}")
        if profile in {"noisy", "governed"}:
            from scyvera.audit_rules import RULES

            missing = {rule.rule_id for rule in RULES} - set(rule_ids)
            if missing:
                raise CellInvalid(f"profile missed rules: {sorted(missing)}")
        if profile == "governed":
            governed_ids = {
                finding["rule_id"]
                for finding in warmup_payload["findings"]
                if finding.get("scoring_reason") == "governed"
            }
            if not governed_ids:
                raise CellInvalid("governed profile produced no governed finding")

        end_to_end: list[float] = []
        peaks: list[float] = []
        payloads: list[bytes] = []

        for _ in range(repeats):
            elapsed_ms, peak_mb, raw, _, code = _run_audit(tree)
            if code != expected_code:
                raise CellInvalid(
                    f"measured run exited {code}, expected {expected_code}"
                )
            end_to_end.append(elapsed_ms)
            payloads.append(raw)
            if peak_mb is not None:
                peaks.append(peak_mb)

        if len(payloads) >= 2 and payloads[0] != payloads[1]:
            raise CellInvalid("two consecutive --json runs were not byte-identical")
        if len(payloads) >= 2 and payloads[0] != warmup_out:
            raise CellInvalid("measured run bytes differ from the warm-up bytes")

        scan_samples: list[float] = []
        previous = time.perf_counter()
        scan_tree(tree)  # in-process warm-up, discarded
        del previous
        for _ in range(scan_repeats):
            started = time.perf_counter()
            scan_tree(tree)
            scan_samples.append((time.perf_counter() - started) * 1000.0)

        cell.update(
            {
                "status": "measured",
                "verified": True,
                "end_to_end_ms": summarize(end_to_end),
                "scan_ms": summarize(scan_samples),
                "peak_rss_mb": summarize(peaks) if peaks else None,
                "files_scanned": warmup_payload["stats"]["files_scanned"],
                "files_skipped": warmup_payload["stats"]["files_skipped"],
                "bytes_scanned": scanned_bytes,
                "bytes_skipped": skipped_bytes,
            }
        )
        return cell
    except CellInvalid as exc:
        cell.update({"status": "invalid", "verified": False, "reason": str(exc)})
        raise
    finally:
        if not keep:
            gen_corpus.remove(spec)


def _parse_scales(text: str) -> list[int]:
    values = [int(part) for part in text.split(",") if part.strip()]
    if not values:
        raise argparse.ArgumentTypeError("--files must list at least one scale")
    return values


def _default_result_path(environment: dict[str, object]) -> Path:
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    platform_tag = "windows" if sys.platform.startswith("win") else (
        "linux" if sys.platform.startswith("linux") else
        "macos" if sys.platform == "darwin" else "unknown"
    )
    return RESULTS_DIR / f"{date}-{platform_tag}-{environment['commit']}.json"


def run(
    scales: list[int],
    profiles: list[str],
    repeats: int,
    scan_repeats: int,
    budget_seconds: float,
    seed: int,
    keep: bool = False,
    result_path: Path | None = None,
) -> dict[str, object]:
    work_root = Path(tempfile.mkdtemp(prefix="scyvera-bench-"))
    environment = collect_environment(repeats, scan_repeats)
    result: dict[str, object] = {
        "schema": SCHEMA_VERSION,
        "profiles_requested": list(profiles),
        "scales_requested": sorted(scales),
        "environment": environment,
        "protocol": {
            "warmup_runs": 1,
            "repeats": repeats,
            "scan_repeats": scan_repeats,
            "percentile_method": "linear interpolation (numpy 'linear'), p95 at q=0.95",
            "headline": "median",
            "budget_seconds_per_cell": budget_seconds,
            "cache_state": "warm filesystem cache; cold cache not measured",
            "command": " ".join(AUDIT_COMMAND),
            "corpus_seed": seed,
        },
        "cells": [],
    }

    try:
        ordered_scales = sorted(scales)
        for profile in profiles:
            last_measured: dict[str, object] | None = None
            for index, files in enumerate(ordered_scales):
                projected = None
                if last_measured is not None:
                    previous_files = int(last_measured["files"])
                    previous_median = float(
                        last_measured["end_to_end_ms"]["median"]  # type: ignore[index]
                    )
                    projected = (
                        previous_median
                        * (files / previous_files)
                        * (repeats + scan_repeats)
                        / 1000.0
                    )
                    if projected > budget_seconds:
                        result["cells"].append(  # type: ignore[union-attr]
                            {
                                "profile": profile,
                                "files": files,
                                "status": "not_measured",
                                "reason": "projected_over_budget",
                                "detail": (
                                    f"projected from the measured {previous_files}-file "
                                    f"cell: {previous_median:.0f} ms x {files / previous_files:g} "
                                    f"x {repeats + scan_repeats} runs = {projected:.0f} s, "
                                    f"above the {budget_seconds:.0f} s per-cell budget; "
                                    "no corpus was generated"
                                ),
                            }
                        )
                        continue

                cell = measure_cell(
                    profile,
                    files,
                    seed,
                    repeats,
                    scan_repeats,
                    budget_seconds,
                    work_root,
                    keep=keep,
                )
                result["cells"].append(cell)  # type: ignore[union-attr]
                if cell.get("status") == "measured":
                    last_measured = cell
                else:
                    # A budget stop ends this profile's ladder: smaller cells are
                    # already measured, larger ones would only project higher. The
                    # remaining scales still get a cell, so the gap is published
                    # rather than silently absent from the table and the result.
                    stop_reason = str(cell.get("reason", "unknown"))
                    for remaining in ordered_scales[index + 1:]:
                        result["cells"].append(  # type: ignore[union-attr]
                            {
                                "profile": profile,
                                "files": remaining,
                                "status": "not_measured",
                                "reason": "ladder_stopped",
                                "detail": (
                                    f"not attempted: the {files:,}-file cell stopped "
                                    f"the ladder ({stop_reason}); larger cells would "
                                    "only project higher, so no corpus was generated"
                                ),
                            }
                        )
                    break
    finally:
        if not keep:
            shutil.rmtree(work_root, ignore_errors=True)

    if result_path is not None:
        result_path = Path(result_path)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(result, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        result["result_path"] = str(result_path)
    return result


def _parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(
        description="Measure scyvera audit on generated corpora (PD-5).",
    )
    parser.add_argument("--files", default="1000,5000,10000", help="comma-separated scales")
    parser.add_argument(
        "--profiles",
        default=",".join(gen_corpus.PROFILES),
        help="comma-separated profiles",
    )
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument(
        "--scan-repeats",
        type=int,
        default=3,
        help="in-process scan samples (e2e is the headline; 3 keeps runtime bounded)",
    )
    parser.add_argument("--budget-seconds", type=float, default=1200.0)
    parser.add_argument("--seed", type=int, default=5)
    parser.add_argument("--json", dest="result_json", default=None)
    parser.add_argument("--keep", action="store_true", help="keep generated corpora")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    profiles = [part.strip() for part in args.profiles.split(",") if part.strip()]
    unknown = [profile for profile in profiles if profile not in gen_corpus.PROFILES]
    if unknown:
        print(f"error: unknown profiles {unknown}", file=sys.stderr)
        return 2

    result_path = Path(args.result_json) if args.result_json else None
    result = run(
        scales=_parse_scales(args.files),
        profiles=profiles,
        repeats=args.repeats,
        scan_repeats=args.scan_repeats,
        budget_seconds=args.budget_seconds,
        seed=args.seed,
        keep=args.keep,
        result_path=result_path,
    )
    for cell in result["cells"]:  # type: ignore[index]
        if cell.get("status") == "measured":
            e2e = cell["end_to_end_ms"]
            print(
                f"{cell['profile']:>8} {cell['files']:>6} files  "
                f"median {e2e['median']:.0f} ms  p95 {e2e['p95']:.0f} ms  "
                f"scanned {cell['files_scanned']}  skipped {cell['files_skipped']}"
            )
        else:
            print(
                f"{cell['profile']:>8} {cell['files']:>6} files  NOT MEASURED: "
                f"{cell.get('reason')} ({cell.get('detail')})"
            )
    if result_path is None:
        print(json.dumps(result, indent=2))
    else:
        print(f"wrote {result_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
