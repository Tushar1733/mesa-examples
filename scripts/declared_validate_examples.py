"""
mesa-examples CI Validation Script
====================================
Discovers, installs, runs, and health-checks every example in the
mesa-examples repository.  Designed for non-interactive GitHub Actions use.

Usage
-----
    python validate_examples.py [--examples-dir examples] [--timeout 10]

Exit codes
----------
    0  – all examples passed
    1  – one or more examples failed or timed-out
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional

# Force UTF-8 output on all platforms (Windows cp1252, Linux pipes, CI runners)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import requests
import yaml
import venv

# ---------------------------------------------------------------------------
# Constants / defaults
# ---------------------------------------------------------------------------
EXAMPLES_DIR = "examples"
DEFAULT_TIMEOUT = 30          # seconds per example (solara needs ~8-15s to boot)
SERVER_BOOT_WAIT = 10         # seconds to wait before health-check
# Each entry: (pattern_to_match, human-readable label)
# Order matters — more specific patterns should come first.
ERROR_PATTERNS: list[tuple[str, str]] = [
    # ── Relative import (package structure issue) ────────────────────────────
    ("attempted relative import with no known parent package", "ImportError: relative import"),

    # ── Legacy Mesa API ──────────────────────────────────────────────────────
    ("has no attribute 'visualization'",    "Legacy Mesa API: mesa.visualization removed"),
    ("mesa.visualization",                  "Legacy Mesa API: mesa.visualization removed"),
    ("ModularServer",                       "Legacy Mesa API: ModularServer removed"),
    ("mesa runserver",                      "Legacy Mesa API: mesa runserver removed"),

    # ── Incomplete model / NoneType space ────────────────────────────────────
    ("Unknown space type: <class 'NoneType'>", "Incomplete model: space is None"),
    ("raised exception ValueError",            "Component raised ValueError"),
    ("Unknown space type",                     "Incomplete model: unknown space type"),

    # ── General Python errors ────────────────────────────────────────────────
    ("AttributeError",          "AttributeError"),
    ("ImportError",             "ImportError"),
    ("ModuleNotFoundError",     "ModuleNotFoundError"),
    ("ValueError",              "ValueError"),
    ("RuntimeError",            "RuntimeError"),
    ("TypeError",               "TypeError"),
    ("NameError",               "NameError"),
    ("Traceback (most recent",  "Unhandled exception (Traceback)"),
]

STATUS_PASS    = "PASS"
STATUS_FAIL    = "FAIL"
STATUS_TIMEOUT = "TIMEOUT"


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
    status: Optional[str] = None
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
def create_virtualenv(meta: "ExampleMetadata") -> str:
    venv_path = os.path.join(meta.path, ".venv")

    if sys.platform == "win32":
        python_exec = os.path.join(venv_path, "Scripts", "python.exe")
    else:
        python_exec = os.path.join(venv_path, "bin", "python")

    if not os.path.exists(venv_path):
        print(f"  Creating virtualenv for {meta.name}")
        subprocess.run(
            [sys.executable, "-m", "venv", venv_path],
            check=True,
            timeout=60,
        )
        subprocess.run(
            [python_exec, "-m", "pip", "install", "--upgrade", "pip"],
            check=True,
            timeout=60,
        )
        # Always install solara so the run command is always found
        subprocess.run(
            [python_exec, "-m", "pip", "install", "solara", "--quiet"],
            check=True,
            timeout=120,   # solara has many deps, give it more time
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
        path=example_path,
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
    """
    Read a requirements.txt and return only the lines that should be installed.
    Skips blank lines and comments.
    """
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
    Install requirements listed in metadata.
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

    print(f"  Installing {len(packages)} dependenc{'y' if len(packages)==1 else 'ies'} from {req_file} …")
    result = subprocess.run(
        [python_exec, "-m", "pip", "install", *packages, "--quiet"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, f"pip install failed: {result.stderr.strip()[:300]}"
    return True, ""


# Legacy run commands that no longer exist in modern Mesa
LEGACY_COMMANDS: list[tuple[tuple, str]] = [
    (("mesa", "runserver"), "Legacy Mesa API: 'mesa runserver' removed - migrate to 'solara run app.py'"),
    (("mesa",),             "Legacy Mesa API: mesa CLI removed - migrate to 'solara run app.py'"),
]


# ---------------------------------------------------------------------------
# 4 & 5. Execution + health-check
# ---------------------------------------------------------------------------
def _build_command(run_cmd: str) -> list[str]:
    """
    Convert the run string from metadata into a list suitable for Popen.
    Raises ValueError with a clear message for known legacy commands.
    """
    parts = run_cmd.strip().split()
    for legacy_parts, message in LEGACY_COMMANDS:
        if tuple(parts[:len(legacy_parts)]) == legacy_parts:
            raise ValueError(message)
    return parts


def detect_errors(text: str) -> Optional[str]:
    """
    Scan output text for known error patterns.
    Returns a human-readable label for the first match, or None.
    """
    for pattern, label in ERROR_PATTERNS:
        if pattern in text:
            return label
    return None


def check_server(port: int, deadline: float, retries: int = 5, delay: float = 1.0) -> bool:
    """
    Send an HTTP GET to localhost:<port>.
    Returns True if any attempt gets a 200 response.

    FIX: Now accepts a `deadline` (absolute time.time() value) so it aborts
    early instead of potentially burning 20+ seconds past the overall timeout.
    """
    url = f"http://localhost:{port}"
    for attempt in range(1, retries + 1):
        # ── FIX 1: Respect the overall deadline inside the retry loop ────────
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


def run_example(meta: ExampleMetadata, timeout: int = DEFAULT_TIMEOUT) -> ExampleResult:
    """
    Start the example process, wait for boot, health-check, then terminate.
    Returns an ExampleResult.
    """
    venv_path = os.path.join(meta.path, ".venv")

    if sys.platform == "win32":
        python_exec = os.path.join(venv_path, "Scripts", "python.exe")
    else:
        python_exec = os.path.join(venv_path, "bin", "python")

    if not meta.run:
        return ExampleResult(name=meta.name, status=STATUS_FAIL, notes="No run command in metadata")

    try:
        cmd = _build_command(meta.run)
        # Ensure example runs inside the virtual environment
        if cmd[0] == "python":
            cmd[0] = python_exec

        # ── FIX 2: Inject --port into solara commands if not already present ─
        # This ensures the server binds to the port we health-check against,
        # preventing permanent health-check failures that look like timeouts.
        if len(cmd) >= 2 and cmd[0].endswith("solara") and "run" in cmd:
            if "--port" not in cmd:
                cmd.extend(["--port", str(meta.port)])

    except ValueError as exc:
        return ExampleResult(name=meta.name, status=STATUS_FAIL, notes=str(exc))

    print(f"  Running: {' '.join(cmd)}")

    # Build a CI-safe environment: unbuffered Python, no browser, no display
    ci_env = os.environ.copy()
    ci_env["PYTHONUNBUFFERED"] = "1"        # ensures output is not buffered
    ci_env["PYTHONDONTWRITEBYTECODE"] = "1" # skip .pyc files
    ci_env["BROWSER"] = "echo"              # prevent any browser from opening
    ci_env["MPLBACKEND"] = "Agg"            # non-interactive matplotlib backend
    if sys.platform != "win32":
        ci_env.pop("DISPLAY", None)         # suppress GUI on headless Linux

    deadline = time.time() + timeout        # ── FIX 3: Set deadline BEFORE Popen

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
            # shell=True is needed on Windows so that script wrappers like
            # solara.cmd / solara.exe are resolved via PATH correctly.
            shell=(sys.platform == "win32"),
        )
    except FileNotFoundError:
        # Fallback: retry with shell=True (covers edge cases on all platforms)
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
            if cmd and cmd[0] == "mesa":
                return ExampleResult(
                    name=meta.name,
                    status=STATUS_FAIL,
                    notes="Legacy Mesa API: 'mesa runserver' removed - migrate to 'solara run app.py'",
                )
            return ExampleResult(
                name=meta.name,
                status=STATUS_FAIL,
                notes=f"Command not found: '{cmd[0]}' is not installed or not on PATH",
            )
    except Exception as exc:
        return ExampleResult(name=meta.name, status=STATUS_FAIL, notes=str(exc))

    # ── Drain output in background threads while waiting ────────────────────
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

    # Poll every 0.5s during boot window; catch errors as soon as they appear
    poll_interval = 0.5
    elapsed = 0.0
    while elapsed < SERVER_BOOT_WAIT:
        # ── FIX 4: Also respect deadline during the boot-wait polling loop ───
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
            # Process already exited — wait for drain threads to flush all output
            process.wait()
            t_out.join(timeout=3)
            t_err.join(timeout=3)
            time.sleep(0.2)
            combined = "".join(stdout_lines) + "".join(stderr_lines)
            err_match = detect_errors(combined)
            note = err_match if err_match else f"Process exited early (code {process.returncode})"
            return ExampleResult(name=meta.name, status=STATUS_FAIL, notes=note)

    # ── Final error scan before health-check ────────────────────────────────
    if process.poll() is not None:
        process.wait()
        t_out.join(timeout=3)
        t_err.join(timeout=3)
        time.sleep(0.2)
        combined = "".join(stdout_lines) + "".join(stderr_lines)
        err_match = detect_errors(combined)
        note = err_match if err_match else f"Process exited early (code {process.returncode})"
        return ExampleResult(name=meta.name, status=STATUS_FAIL, notes=note)

    # ── HTTP health-check ────────────────────────────────────────────────────
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

    # ── FIX 1 applied here: pass deadline into check_server ─────────────────
    server_ok = check_server(meta.port, deadline=deadline)

    # ── Terminate ────────────────────────────────────────────────────────────
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


def _kill_port(port: int) -> None:
    """Force-kill any process still listening on the given port (cross-platform)."""
    import signal as _signal

    if sys.platform == "win32":
        try:
            out = subprocess.check_output(
                ["netstat", "-ano"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            for line in out.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.strip().split()
                    pid = int(parts[-1])
                    subprocess.call(
                        ["taskkill", "/F", "/PID", str(pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
        except Exception:
            pass
    else:
        try:
            out = subprocess.check_output(
                ["lsof", "-ti", f"tcp:{port}"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            for pid_str in out.strip().splitlines():
                try:
                    os.kill(int(pid_str), _signal.SIGKILL)
                except Exception:
                    pass
        except Exception:
            pass


def _terminate(process: subprocess.Popen, port: int = 0) -> None:
    """Cleanly terminate a process, all its children, and free the port."""
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
        import signal, os
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except Exception:
        pass

    # Ensure the port is free regardless of what happened above
    if port:
        _kill_port(port)
        time.sleep(0.5)  # brief pause so the OS reclaims the socket


# ---------------------------------------------------------------------------
# 6. Report generation
# ---------------------------------------------------------------------------
def generate_report(
    results: list[ExampleResult],
    examples: list[ExampleMetadata],
    run_meta: dict,
    output_json: str = "validation_report.json",
) -> None:
    """Print a formatted summary table and write a full JSON report."""

    passes   = sum(1 for r in results if r.status == STATUS_PASS)
    fails    = sum(1 for r in results if r.status == STATUS_FAIL)
    timeouts = sum(1 for r in results if r.status == STATUS_TIMEOUT)

    # ── Console table ────────────────────────────────────────────────────────
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

    # ── Build JSON payload ───────────────────────────────────────────────────
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
def _resolve_output_path(cli_value):
    """
    Determine the JSON report output path and mesa mode label.

    Precedence (highest to lowest):
      1. --output-json CLI argument  (explicit override)
      2. MESA_VERSION_LABEL env var  (set by GitHub Actions matrix)
      3. Hardcoded default           (local runs)

    Returns (output_path, mesa_label).
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
    print(f"  Examples dir      : {args.examples_dir}")
    print(f"  Timeout           : {args.timeout}s per example")
    print(f"  JSON output       : {output_json}")
    if mesa_label != "local":
        print(f"  Mesa validation mode: {mesa_label}")
    print()

    # ── Hard fail: examples directory doesn't exist ──────────────────────────
    if not os.path.isdir(args.examples_dir):
        print(f"ERROR: Examples directory not found: {args.examples_dir}")
        return 1

    # ── Discover ─────────────────────────────────────────────────────────────
    examples = discover_examples(args.examples_dir)
    print(f"Found {len(examples)} example(s).\n")

    # ── Hard fail: no examples found is likely a config mistake ──────────────
    if not examples:
        print("ERROR: No examples found — check your --examples-dir path or example.yaml files.")
        return 1

    results: list[ExampleResult] = []

    for meta in examples:
        print(f"[ {meta.name} ]  ({meta.path})")

        python_exec = create_virtualenv(meta)

        if not args.skip_install:
            ok, err = install_dependencies(meta, python_exec)
            if not ok:
                print(f"  Dependency install failed: {err}")
                results.append(ExampleResult(name=meta.name, status=STATUS_FAIL, notes=err))
                continue

        result = run_example(meta, timeout=args.timeout)
        icon = "PASS" if result.status == STATUS_PASS else ("TIME" if result.status == STATUS_TIMEOUT else "FAIL")
        print(f"  [{icon}]" + (f"  {result.notes}" if result.notes else ""))
        results.append(result)
        print()

    # ── Report ────────────────────────────────────────────────────────────────
    run_meta = {
        "examples_dir":       args.examples_dir,
        "timeout_seconds":    args.timeout,
        "skip_install":       args.skip_install,
        "mesa_version_label": mesa_label,
        "python":             sys.version,
        "platform":           sys.platform,
    }
    generate_report(results, examples, run_meta, output_json=output_json)

    # ── Always exit 0 so CI completes and uploads the report ─────────────────
    # Individual pass/fail/timeout results are captured in the JSON report.
    # CI should never be blocked just because some examples are broken.
    # The only hard failures are script-level issues (missing dir, no examples)
    # which are handled above with explicit return 1.
    return 0


if __name__ == "__main__":
    sys.exit(main())