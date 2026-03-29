"""
mesa-examples CI Validation Script
====================================
Discovers, installs, runs, and health-checks every example in the
mesa-examples repository.  Designed for non-interactive GitHub Actions use.

Usage
-----
    python validate_examples.py [--examples-dir examples] [--timeout 30]

Exit codes
----------
    0  – script completed successfully (check JSON report for per-example results)
    1  – script-level failure (examples dir not found, or no examples discovered)
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional

# Force UTF-8 output on all platforms (Windows cp1252, Linux pipes, CI runners)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import requests
import yaml

# ---------------------------------------------------------------------------
# Constants / defaults
# ---------------------------------------------------------------------------
EXAMPLES_DIR     = "examples"
DEFAULT_TIMEOUT  = 30    # seconds per example (solara needs ~8-15s to boot)
SERVER_BOOT_WAIT = 10    # seconds to poll for errors before health-check

# Each entry: (pattern_to_match, human-readable label)
# Order matters — more specific patterns must come first.
ERROR_PATTERNS: list[tuple[str, str]] = [
    # ── Relative import ──────────────────────────────────────────────────────
    ("attempted relative import with no known parent package", "ImportError: relative import"),

    # ── Legacy Mesa API ──────────────────────────────────────────────────────
    ("has no attribute 'visualization'", "Legacy Mesa API: mesa.visualization removed"),
    ("mesa.visualization",               "Legacy Mesa API: mesa.visualization removed"),
    ("ModularServer",                    "Legacy Mesa API: ModularServer removed"),
    ("mesa runserver",                   "Legacy Mesa API: mesa runserver removed"),

    # ── Incomplete model ─────────────────────────────────────────────────────
    ("Unknown space type: <class 'NoneType'>", "Incomplete model: space is None"),
    ("raised exception ValueError",            "Component raised ValueError"),
    ("Unknown space type",                     "Incomplete model: unknown space type"),

    # ── General Python errors ────────────────────────────────────────────────
    ("AttributeError",         "AttributeError"),
    ("ImportError",            "ImportError"),
    ("ModuleNotFoundError",    "ModuleNotFoundError"),
    ("ValueError",             "ValueError"),
    ("RuntimeError",           "RuntimeError"),
    ("TypeError",              "TypeError"),
    ("NameError",              "NameError"),
    ("Traceback (most recent", "Unhandled exception (Traceback)"),
]

STATUS_PASS    = "PASS"
STATUS_FAIL    = "FAIL"
STATUS_TIMEOUT = "TIMEOUT"

# Legacy run commands that no longer exist in modern Mesa
LEGACY_COMMANDS: list[tuple[tuple, str]] = [
    (("mesa", "runserver"), "Legacy Mesa API: 'mesa runserver' removed - migrate to 'solara run app.py'"),
    (("mesa",),             "Legacy Mesa API: mesa CLI removed - migrate to 'solara run app.py'"),
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class ExampleMetadata:
    name: str
    path: str
    requirements: Optional[str] = None
    run: Optional[str] = None
    port: int = 8765
    maintainer: Optional[str] = None
    mesa_version: Optional[str] = None
    python: Optional[str] = None


@dataclass
class ExampleResult:
    name: str
    status: str
    notes: str = ""


# ---------------------------------------------------------------------------
# Virtualenv creation
# ---------------------------------------------------------------------------
def create_virtualenv(meta: ExampleMetadata) -> str:
    """
    Create an isolated .venv inside the example's directory (if not already
    present), upgrade pip, and always install solara.

    FIX: Many examples don't list solara in their requirements.txt, which
    caused code 127 ("command not found") when the run command was
    'solara run app.py'. Installing it here unconditionally fixes that.

    Returns the path to the venv's Python executable.
    """
    venv_path = os.path.join(meta.path, ".venv")

    if sys.platform == "win32":
        python_exec = os.path.join(venv_path, "Scripts", "python.exe")
    else:
        python_exec = os.path.join(venv_path, "bin", "python")

    if not os.path.exists(venv_path):
        print(f"  Creating virtualenv for {meta.name} …")

        # Use subprocess with timeout to avoid hanging on slow CI runners
        subprocess.run(
            [sys.executable, "-m", "venv", venv_path],
            check=True,
            timeout=60,
        )
        subprocess.run(
            [python_exec, "-m", "pip", "install", "--upgrade", "pip", "--quiet"],
            check=True,
            timeout=60,
        )
        # Always install solara and mesa so every example has its core deps.
        # mesa is not on PyPI under 'mesa' for all versions — we install it
        # from the local repo so the venv uses the in-development version.
        print(f"  Installing solara + mesa into venv for {meta.name} …")
        subprocess.run(
            [python_exec, "-m", "pip", "install", "solara", "--quiet"],
            check=True,
            timeout=120,  # solara has many deps — give it extra time
        )
        # Install mesa from the local repo (editable) so venv picks up the
        # in-development version rather than a potentially stale PyPI release.
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if os.path.isfile(os.path.join(repo_root, "pyproject.toml")) or            os.path.isfile(os.path.join(repo_root, "setup.py")):
            subprocess.run(
                [python_exec, "-m", "pip", "install", "-e", repo_root, "--quiet"],
                check=True,
                timeout=120,
            )
        else:
            # Fallback: install mesa from PyPI if no local repo found
            subprocess.run(
                [python_exec, "-m", "pip", "install", "mesa", "--quiet"],
                check=True,
                timeout=120,
            )

    return python_exec


# ---------------------------------------------------------------------------
# 1. Discovery
# ---------------------------------------------------------------------------
def discover_examples(examples_dir: str = EXAMPLES_DIR) -> list[ExampleMetadata]:
    """Recursively find all directories containing example.yaml."""
    found: list[ExampleMetadata] = []
    for root, _dirs, files in os.walk(examples_dir):
        if "example.yaml" in files:
            meta = load_metadata(root)
            if meta:
                found.append(meta)
    return found


# ---------------------------------------------------------------------------
# 2. Metadata loading
# ---------------------------------------------------------------------------
def load_metadata(example_path: str) -> Optional[ExampleMetadata]:
    """Parse example.yaml and return an ExampleMetadata object."""
    yaml_path = os.path.join(example_path, "example.yaml")
    try:
        with open(yaml_path, "r") as fh:
            raw: dict = yaml.safe_load(fh) or {}
    except Exception as exc:
        print(f"  [WARN] Could not read {yaml_path}: {exc}")
        return None

    return ExampleMetadata(
        name=raw.get("name", os.path.basename(example_path)),
        path=os.path.abspath(example_path),
        requirements=raw.get("requirements"),
        run=raw.get("run"),
        port=int(raw.get("port", 8765)),
        maintainer=raw.get("maintainer"),
        mesa_version=str(raw.get("mesa_version", "")),
        python=str(raw.get("python", "")),
    )


# ---------------------------------------------------------------------------
# 3. Dependency installation
# ---------------------------------------------------------------------------
def _filter_requirements(req_file: str) -> list[str]:
    """Read requirements.txt, skip blank lines and comments."""
    kept: list[str] = []
    with open(req_file, "r") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            kept.append(line)
    return kept


def install_dependencies(meta: ExampleMetadata, python_exec: str) -> tuple[bool, str]:
    """
    Install requirements listed in metadata into the venv.
    Returns (success, error_message).
    """
    if not meta.requirements:
        return True, ""

    req_file = os.path.join(meta.path, meta.requirements)
    if not os.path.isfile(req_file):
        return False, f"requirements file not found: {req_file}"

    packages = _filter_requirements(req_file)
    if not packages:
        print(f"  No external dependencies to install for {meta.name}.")
        return True, ""

    print(f"  Installing {len(packages)} dependenc{'y' if len(packages) == 1 else 'ies'} from {req_file} …")
    result = subprocess.run(
        [python_exec, "-m", "pip", "install", *packages, "--quiet"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        return False, f"pip install failed: {result.stderr.strip()[:300]}"
    return True, ""


# ---------------------------------------------------------------------------
# 4. Command building
# ---------------------------------------------------------------------------
def _build_command(run_cmd: str, python_exec: str, port: int) -> list[str]:
    """
    Convert the run string from metadata into an argv list for Popen.

    FIX: Previously this function only took run_cmd as an argument, so it
    had no way to resolve the venv binary paths. It now receives python_exec
    and port so it can:
      - Reject legacy Mesa commands with a clear error message.
      - Replace 'python' with the venv python executable.
      - Replace 'solara' with the venv solara binary — fixes code 127 in CI
        where solara is inside the venv but not on the system PATH.
      - Auto-inject --port so the server binds to the port we health-check.
    """
    parts = run_cmd.strip().split()

    # Reject legacy commands immediately
    for legacy_parts, message in LEGACY_COMMANDS:
        if tuple(parts[:len(legacy_parts)]) == legacy_parts:
            raise ValueError(message)

    venv_bin = os.path.dirname(python_exec)

    # Replace 'python' with venv python
    if parts[0] == "python":
        parts[0] = python_exec

    # FIX: Replace 'solara' with the full venv binary path.
    # On CI, solara is only inside the venv — it is NOT on the system PATH —
    # so Popen would raise FileNotFoundError / exit 127 without this.
    if parts[0] == "solara":
        solara_in_venv = os.path.join(venv_bin, "solara")
        if os.path.exists(solara_in_venv):
            parts[0] = solara_in_venv

    # FIX: Auto-inject --port so the server binds to the expected port.
    # Without this, solara picks its own port and the health-check always fails.
    if "solara" in parts[0] and "run" in parts and "--port" not in parts:
        parts.extend(["--port", str(port)])

    return parts


# ---------------------------------------------------------------------------
# 5. Error detection
# ---------------------------------------------------------------------------
def detect_errors(text: str) -> Optional[str]:
    """
    Scan captured output for known error patterns.
    Returns a human-readable label for the first match, or None.
    """
    for pattern, label in ERROR_PATTERNS:
        if pattern in text:
            return label
    return None


# ---------------------------------------------------------------------------
# 6. Health check
# ---------------------------------------------------------------------------
def check_server(port: int, deadline: float, retries: int = 5, delay: float = 1.0) -> bool:
    """
    Send HTTP GET to localhost:<port>.
    Returns True on first 200 response.
    Aborts early if the overall deadline is exceeded.
    """
    url = f"http://localhost:{port}"
    for attempt in range(1, retries + 1):
        if time.time() >= deadline:
            return False
        try:
            resp = requests.get(url, timeout=2)
            if resp.status_code == 200:
                return True
        except requests.RequestException:
            pass
        if attempt < retries:
            time.sleep(delay)
    return False


# ---------------------------------------------------------------------------
# 7. Run example
# ---------------------------------------------------------------------------
def run_example(meta: ExampleMetadata, python_exec: str, timeout: int = DEFAULT_TIMEOUT) -> ExampleResult:
    """
    Launch the example, wait for boot, health-check the server, terminate.
    Returns an ExampleResult with PASS / FAIL / TIMEOUT status.

    FIX: Now receives python_exec so it can pass it into _build_command(),
    which needs it to resolve the venv solara binary path. Previously
    python_exec was re-derived here but never passed down, so solara was
    never resolved and every example hit code 127.
    """
    if not meta.run:
        return ExampleResult(name=meta.name, status=STATUS_FAIL, notes="No run command in metadata")

    try:
        cmd = _build_command(meta.run, python_exec, meta.port)
    except ValueError as exc:
        return ExampleResult(name=meta.name, status=STATUS_FAIL, notes=str(exc))

    print(f"  Running: {' '.join(cmd)}")

    # CI-safe environment
    ci_env = os.environ.copy()
    ci_env["PYTHONUNBUFFERED"]        = "1"
    ci_env["PYTHONDONTWRITEBYTECODE"] = "1"
    ci_env["BROWSER"]                 = "echo"
    ci_env["MPLBACKEND"]              = "Agg"
    if sys.platform != "win32":
        ci_env.pop("DISPLAY", None)

    # FIX: Prepend the venv's bin/ directory to PATH.
    # Solara is a shell script that internally calls other binaries (uvicorn,
    # starlette workers, etc.) via PATH lookups. Even though we pass the full
    # path to the solara binary itself, those child processes still inherit the
    # parent PATH which doesn't include the venv — so they exit with code 127.
    # Prepending venv bin/ here makes every binary the venv installed visible
    # to solara and all its child processes.
    venv_bin = os.path.dirname(python_exec)
    ci_env["PATH"]        = venv_bin + os.pathsep + ci_env.get("PATH", "")
    ci_env["VIRTUAL_ENV"] = os.path.dirname(venv_bin)  # activate venv for tools that check it

    # Set deadline BEFORE launching so the full budget is available
    deadline = time.time() + timeout

    try:
        process = subprocess.Popen(
            cmd,
            cwd=meta.path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=ci_env,
            shell=(sys.platform == "win32"),
        )
    except FileNotFoundError:
        try:
            process = subprocess.Popen(
                " ".join(cmd),
                cwd=meta.path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=ci_env,
                shell=True,
            )
        except Exception:
            return ExampleResult(
                name=meta.name,
                status=STATUS_FAIL,
                notes=f"Command not found: '{cmd[0]}' is not installed or not on PATH",
            )
    except Exception as exc:
        return ExampleResult(name=meta.name, status=STATUS_FAIL, notes=str(exc))

    # Drain stdout/stderr in background threads so output never blocks Popen
    import threading

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def drain(stream, bucket: list):
        try:
            for line in stream:
                bucket.append(line)
        except Exception:
            pass

    t_out = threading.Thread(target=drain, args=(process.stdout, stdout_lines), daemon=True)
    t_err = threading.Thread(target=drain, args=(process.stderr, stderr_lines), daemon=True)
    t_out.start()
    t_err.start()

    # ── Boot-wait polling loop ───────────────────────────────────────────────
    poll_interval = 0.5
    elapsed = 0.0
    while elapsed < SERVER_BOOT_WAIT:

        # Respect overall deadline even during boot wait
        if time.time() >= deadline:
            _terminate(process, meta.port)
            t_out.join(timeout=2)
            t_err.join(timeout=2)
            combined = "".join(stdout_lines) + "".join(stderr_lines)
            err_match = detect_errors(combined)
            if err_match:
                return ExampleResult(name=meta.name, status=STATUS_FAIL, notes=err_match)
            return ExampleResult(
                name=meta.name,
                status=STATUS_TIMEOUT,
                notes=f"Timed out during boot wait after {timeout}s",
            )

        time.sleep(poll_interval)
        elapsed += poll_interval

        combined = "".join(stdout_lines) + "".join(stderr_lines)
        err_match = detect_errors(combined)
        if err_match:
            _terminate(process, meta.port)
            t_out.join(timeout=2)
            t_err.join(timeout=2)
            return ExampleResult(name=meta.name, status=STATUS_FAIL, notes=err_match)

        if process.poll() is not None:
            process.wait()
            t_out.join(timeout=3)
            t_err.join(timeout=3)
            time.sleep(0.2)
            combined = "".join(stdout_lines) + "".join(stderr_lines)
            err_match = detect_errors(combined)
            note = err_match if err_match else f"Process exited early (code {process.returncode})"
            # Print captured output so we can see WHY the process exited
            if combined.strip():
                print(f"  --- captured output ---")
                for line in combined.splitlines()[-20:]:  # last 20 lines
                    print(f"  | {line}")
                print(f"  --- end output ---")
            return ExampleResult(name=meta.name, status=STATUS_FAIL, notes=note)

    # ── Final check: did process exit at end of boot window? ────────────────
    if process.poll() is not None:
        process.wait()
        t_out.join(timeout=3)
        t_err.join(timeout=3)
        time.sleep(0.2)
        combined = "".join(stdout_lines) + "".join(stderr_lines)
        err_match = detect_errors(combined)
        note = err_match if err_match else f"Process exited early (code {process.returncode})"
        # Print captured output so we can see WHY the process exited
        if combined.strip():
            print(f"  --- captured output ---")
            for line in combined.splitlines()[-20:]:
                print(f"  | {line}")
            print(f"  --- end output ---")
        return ExampleResult(name=meta.name, status=STATUS_FAIL, notes=note)

    # ── Pre health-check deadline guard ─────────────────────────────────────
    if time.time() >= deadline:
        _terminate(process, meta.port)
        t_out.join(timeout=2)
        t_err.join(timeout=2)
        combined = "".join(stdout_lines) + "".join(stderr_lines)
        err_match = detect_errors(combined)
        if err_match:
            return ExampleResult(name=meta.name, status=STATUS_FAIL, notes=err_match)
        return ExampleResult(
            name=meta.name,
            status=STATUS_TIMEOUT,
            notes=f"Timed out before health-check after {timeout}s",
        )

    # ── HTTP health-check ────────────────────────────────────────────────────
    server_ok = check_server(meta.port, deadline=deadline)

    _terminate(process, meta.port)
    t_out.join(timeout=2)
    t_err.join(timeout=2)

    if server_ok:
        return ExampleResult(name=meta.name, status=STATUS_PASS)

    if time.time() >= deadline:
        return ExampleResult(
            name=meta.name,
            status=STATUS_TIMEOUT,
            notes=f"Timed out during health-check after {timeout}s",
        )

    return ExampleResult(
        name=meta.name,
        status=STATUS_FAIL,
        notes=f"Server did not respond on port {meta.port}",
    )


# ---------------------------------------------------------------------------
# 8. Process cleanup
# ---------------------------------------------------------------------------
def _kill_port(port: int) -> None:
    """Force-kill any process still listening on the given port."""
    import signal as _signal

    if sys.platform == "win32":
        try:
            out = subprocess.check_output(["netstat", "-ano"], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    pid = int(line.strip().split()[-1])
                    subprocess.call(
                        ["taskkill", "/F", "/PID", str(pid)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
        except Exception:
            pass
    else:
        try:
            out = subprocess.check_output(
                ["lsof", "-ti", f"tcp:{port}"], text=True, stderr=subprocess.DEVNULL,
            )
            for pid_str in out.strip().splitlines():
                try:
                    os.kill(int(pid_str), _signal.SIGKILL)
                except Exception:
                    pass
        except Exception:
            pass


def _terminate(process: subprocess.Popen, port: int = 0) -> None:
    """Terminate a process, kill its children, and free the port."""
    try:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    except Exception:
        pass

    # Kill child processes on POSIX
    try:
        import signal
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except Exception:
        pass

    if port:
        _kill_port(port)
        time.sleep(1.5)  # FIX: increased from 0.5s — CI runners need more time
                         # to fully reclaim the socket before the next example


# ---------------------------------------------------------------------------
# 9. Report generation
# ---------------------------------------------------------------------------
def generate_report(
    results: list[ExampleResult],
    examples: list[ExampleMetadata],
    run_meta: dict,
    output_json: str = "validation_report.json",
) -> None:
    """Print a summary table to console and write a full JSON report to disk."""

    passes   = sum(1 for r in results if r.status == STATUS_PASS)
    fails    = sum(1 for r in results if r.status == STATUS_FAIL)
    timeouts = sum(1 for r in results if r.status == STATUS_TIMEOUT)

    col_name = max(max((len(r.name) for r in results), default=0), 20)
    header   = f"{'Example Name':<{col_name}}  {'Status':<8}  Notes"
    print("\n" + "=" * (len(header) + 4))
    print(header)
    print("-" * (len(header) + 4))
    for r in results:
        print(f"{r.name:<{col_name}}  {r.status:<8}  {r.notes[:60] if r.notes else ''}")
    print("=" * (len(header) + 4))
    print(f"\nTotal : {len(results)}")
    print(f"  {STATUS_PASS:<8}: {passes}")
    print(f"  {STATUS_FAIL:<8}: {fails}")
    print(f"  {STATUS_TIMEOUT:<8}: {timeouts}")
    print()

    meta_by_name = {m.name: m for m in examples}
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run": run_meta,
        "summary": {
            "total":   len(results),
            "passed":  passes,
            "failed":  fails,
            "timeout": timeouts,
        },
        "examples": [
            {
                "name":         r.name,
                "status":       r.status,
                "notes":        r.notes or None,
                "path":         meta_by_name[r.name].path         if r.name in meta_by_name else None,
                "run_command":  meta_by_name[r.name].run          if r.name in meta_by_name else None,
                "port":         meta_by_name[r.name].port         if r.name in meta_by_name else None,
                "maintainer":   meta_by_name[r.name].maintainer   if r.name in meta_by_name else None,
                "mesa_version": meta_by_name[r.name].mesa_version if r.name in meta_by_name else None,
                "requirements": meta_by_name[r.name].requirements if r.name in meta_by_name else None,
            }
            for r in results
        ],
    }

    with open(output_json, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    print(f"  JSON report saved to: {output_json}\n")


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------
def _resolve_output_path(cli_value: Optional[str]) -> tuple[str, str]:
    """
    Determine the JSON report output path and mesa label.
    Precedence: CLI arg > MESA_VERSION_LABEL env var > hardcoded default.
    """
    mesa_label = os.getenv("MESA_VERSION_LABEL", "").strip()

    if cli_value:
        return cli_value, mesa_label or "local"
    if mesa_label:
        return f"example_validation_results_{mesa_label}.json", mesa_label
    return "example_validation_results(declared-deps).json", "local"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate mesa-examples in CI")
    parser.add_argument("--examples-dir", default=EXAMPLES_DIR,
                        help="Root directory containing examples (default: examples)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help="Max seconds per example (default: 30)")
    parser.add_argument("--skip-install", action="store_true",
                        help="Skip pip install step (useful if deps already present)")
    parser.add_argument("--output-json", default=None,
                        help="Override report path (default: auto-named from MESA_VERSION_LABEL)")
    args = parser.parse_args()

    output_json, mesa_label = _resolve_output_path(args.output_json)

    print("mesa-examples Validator")
    print(f"  Working dir  : {os.getcwd()}")
    print(f"  Script dir   : {os.path.dirname(os.path.abspath(__file__))}")
    print(f"  Examples dir : {args.examples_dir}")
    print(f"  Timeout      : {args.timeout}s per example")
    print(f"  JSON output  : {output_json}")
    if mesa_label != "local":
        print(f"  Mesa label   : {mesa_label}")
    print()

    # Resolve to absolute path so all downstream path joins work correctly
    # regardless of what directory CI runs the script from.
    args.examples_dir = os.path.abspath(args.examples_dir)

    # Hard fail — directory doesn't exist, something is wrong with the setup
    if not os.path.isdir(args.examples_dir):
        print(f"ERROR: Examples directory not found: {args.examples_dir}")
        return 1

    examples = discover_examples(args.examples_dir)
    print(f"Found {len(examples)} example(s).\n")

    # Hard fail — no examples found is almost always a config mistake
    if not examples:
        print("ERROR: No examples found — check --examples-dir or example.yaml files.")
        return 1

    results: list[ExampleResult] = []

    for meta in examples:
        print(f"[ {meta.name} ]  ({meta.path})")

        # Create venv and install solara into it
        try:
            python_exec = create_virtualenv(meta)
        except Exception as exc:
            print(f"  Virtualenv creation failed: {exc}")
            results.append(ExampleResult(name=meta.name, status=STATUS_FAIL, notes=f"Venv error: {exc}"))
            continue

        # Install example-specific dependencies on top of solara
        if not args.skip_install:
            ok, err = install_dependencies(meta, python_exec)
            if not ok:
                print(f"  Dependency install failed: {err}")
                results.append(ExampleResult(name=meta.name, status=STATUS_FAIL, notes=err))
                continue

        # FIX: Pass python_exec into run_example so it flows into
        # _build_command() and the venv solara binary gets resolved correctly.
        result = run_example(meta, python_exec=python_exec, timeout=args.timeout)
        icon = "PASS" if result.status == STATUS_PASS else ("TIME" if result.status == STATUS_TIMEOUT else "FAIL")
        print(f"  [{icon}]" + (f"  {result.notes}" if result.notes else ""))
        results.append(result)
        print()

    run_meta = {
        "examples_dir":       args.examples_dir,
        "timeout_seconds":    args.timeout,
        "skip_install":       args.skip_install,
        "mesa_version_label": mesa_label,
        "python":             sys.version,
        "platform":           sys.platform,
    }
    generate_report(results, examples, run_meta, output_json=output_json)

    # Always exit 0 — per-example results are captured in the JSON report.
    # CI should never be blocked just because some examples are broken.
    # Only hard script-level failures (above) return 1.
    return 0


if __name__ == "__main__":
    sys.exit(main())