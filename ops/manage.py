from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config_validation import ConfigValidationError, validate_files

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "deployment.json"
SCHEMA = ROOT / "config" / "deployment.schema.json"
EVIDENCE = ROOT / "evidence"
STATUS_FILE = ROOT / "docs" / "implementation_status.json"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
NPM = Path(r"C:\Program Files\nodejs\npm.cmd")
SECRET_PATTERN = re.compile(r"(?i)(password|passwd|token|secret|api[_-]?key)\s*[:=]\s*([^\s,;]+)")


def _redact(value: str) -> str:
    return SECRET_PATTERN.sub(r"\1=[REDACTED]", value)


def _now_slug() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _run(args: list[str], *, cwd: Path = ROOT, timeout: int = 180) -> dict[str, Any]:
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argument arrays; shell=False
            args,
            cwd=cwd,
            timeout=timeout,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
        )
        return {
            "args": [str(item) for item in args],
            "exit_code": completed.returncode,
            "stdout": _redact(completed.stdout[-20000:]),
            "stderr": _redact(completed.stderr[-20000:]),
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "args": [str(item) for item in args],
            "exit_code": 127,
            "stdout": "",
            "stderr": _redact(str(exc)),
        }


def _write_evidence(name: str, result: dict[str, Any]) -> Path:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE / f"{name}_{_now_slug()}.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return path


def _tool(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found

    candidates: list[Path] = []
    if name == "git":
        candidates.append(Path(r"C:\Program Files\Git\cmd\git.exe"))
    elif name in {"psql", "pg_dump", "pg_restore"}:
        executable = f"{name}.exe"
        candidates.extend(Path(r"C:\Program Files\PostgreSQL").glob(f"*\\bin\\{executable}"))
    elif name == "caddy":
        packages = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
        candidates.extend(packages.glob("CaddyServer.Caddy_*\\caddy.exe"))

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def doctor() -> tuple[int, dict[str, Any]]:
    probes: dict[str, tuple[str, list[str]]] = {
        "python": (str(PYTHON), ["--version"]),
        "node": ("node", ["--version"]),
        "npm": (str(NPM), ["--version"]),
        "git": ("git", ["--version"]),
        "psql": ("psql", ["--version"]),
        "caddy": ("caddy", ["version"]),
    }
    tools: dict[str, Any] = {}
    for name, (executable, arguments) in probes.items():
        resolved = executable if Path(executable).is_file() else _tool(executable)
        present = resolved is not None
        tools[name] = {"present": present, "path": resolved}
        if present and resolved is not None:
            tools[name]["probe"] = _run([resolved, *arguments], timeout=20)
    missing = [name for name, value in tools.items() if not value["present"]]
    result = {"ok": not missing, "missing": missing, "tools": tools, "project_root": str(ROOT)}
    return (0 if not missing else 1), result


def config_check(config_path: Path = CONFIG) -> tuple[int, dict[str, Any]]:
    try:
        config = validate_files(config_path, SCHEMA)
    except ConfigValidationError as exc:
        return 1, {"ok": False, "config": str(config_path), "error": str(exc)}
    return 0, {
        "ok": True,
        "config": str(config_path),
        "environment": config["environment"],
        "slack_mode": config["slack_mode"],
        "restore_mode": config["restore_mode"],
    }


def _check(label: str, args: list[str], *, cwd: Path = ROOT, timeout: int = 180) -> dict[str, Any]:
    result = _run(args, cwd=cwd, timeout=timeout)
    result["label"] = label
    result["ok"] = result["exit_code"] == 0
    return result


def _base_checks() -> list[dict[str, Any]]:
    return [
        _check(
            "python_compile", [str(PYTHON), "-m", "compileall", "-q", "backend", "ops", "tests"]
        ),
        _check(
            "django_check", [str(PYTHON), "backend/manage.py", "check", "--fail-level", "WARNING"]
        ),
        _check(
            "migration_drift",
            [
                str(PYTHON),
                "backend/manage.py",
                "makemigrations",
                "--check",
                "--dry-run",
                "--noinput",
            ],
        ),
        _check("ruff", [str(PYTHON), "-m", "ruff", "check", "backend", "ops", "tests"]),
        _check("mypy", [str(PYTHON), "-m", "mypy", "backend", "ops", "--ignore-missing-imports"]),
        _check("frontend_typecheck", [str(NPM), "run", "typecheck"], cwd=ROOT / "frontend"),
        _check("npm_audit", [str(NPM), "audit", "--audit-level=high"], cwd=ROOT / "frontend"),
    ]


def verify(step: str | None = None, verify_all: bool = False) -> tuple[int, dict[str, Any]]:
    if not verify_all and not step:
        return 2, {"ok": False, "error": "Specify --step Sxx or --all."}
    step = step.upper() if step else None
    if step is not None and not re.fullmatch(r"S(?:0\d|1\d|2[0-3])", step):
        return 2, {"ok": False, "error": f"Invalid step: {step}"}

    checks: list[dict[str, Any]] = []
    doctor_code, doctor_result = doctor()
    checks.append({"label": "doctor", "ok": doctor_code == 0, **doctor_result})
    config_code, config_result = config_check()
    checks.append({"label": "config_check", "ok": config_code == 0, **config_result})
    checks.extend(_base_checks())

    if verify_all or step in {"S09", "S15"}:
        checks.append(
            _check(
                "calendar_fixtures",
                [str(PYTHON), "-m", "pytest", "tests/test_calendar_engine.py", "-q"],
            )
        )

    if verify_all or (step and int(step[1:]) >= 4):
        checks.append(
            _check(
                "postgres_connectivity",
                [str(PYTHON), "backend/manage.py", "showmigrations", "--plan"],
            )
        )

    failed = [item["label"] for item in checks if not item.get("ok")]
    result = {
        "ok": not failed,
        "step": "ALL" if verify_all else step,
        "failed": failed,
        "checks": checks,
    }
    evidence_label = "all" if verify_all else (step or "unknown").lower()
    evidence_path = _write_evidence(f"verify_{evidence_label}", result)
    result["evidence_path"] = str(evidence_path.relative_to(ROOT))
    return (0 if not failed else 1), result


def _load_status() -> list[dict[str, Any]]:
    try:
        value = json.loads(STATUS_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read implementation status: {exc}") from exc
    if not isinstance(value, list):
        raise RuntimeError("implementation_status.json must contain a list.")
    return value


def status() -> tuple[int, dict[str, Any]]:
    rows = _load_status()
    counts: dict[str, int] = {}
    blocked: list[dict[str, Any]] = []
    for row in rows:
        state = str(row.get("status", "UNKNOWN"))
        counts[state] = counts.get(state, 0) + 1
        if state == "BLOCKED" or row.get("blocking_reason"):
            blocked.append({"step_id": row.get("step_id"), "reason": row.get("blocking_reason")})
    return 0, {"ok": True, "counts": counts, "blocked": blocked, "steps": rows}


def backup() -> tuple[int, dict[str, Any]]:
    pg_dump = _tool("pg_dump")
    if pg_dump is None:
        return 1, {"ok": False, "error": "pg_dump is unavailable; PostgreSQL is not installed."}
    return 1, {
        "ok": False,
        "error": "Backup execution is intentionally blocked until database credentials, backup target, and maintenance procedure are configured.",
        "pg_dump": pg_dump,
    }


def restore_check() -> tuple[int, dict[str, Any]]:
    pg_restore = _tool("pg_restore")
    if pg_restore is None:
        return 1, {"ok": False, "error": "pg_restore is unavailable; PostgreSQL is not installed."}
    return 1, {
        "ok": False,
        "error": "Restore drill is not yet configured. It must use a separate database with restore_mode=true and slack_mode=off.",
        "pg_restore": pg_restore,
    }


def release_check() -> tuple[int, dict[str, Any]]:
    rows = _load_status()
    incomplete = [
        {
            "step_id": row.get("step_id"),
            "status": row.get("status"),
            "reason": row.get("blocking_reason"),
        }
        for row in rows
        if row.get("status") != "VERIFIED"
    ]
    verify_code, verification = verify(verify_all=True)
    ok = not incomplete and verify_code == 0
    result = {
        "ok": ok,
        "readiness": "LIVE_READY" if ok else "BLOCKED",
        "incomplete_steps": incomplete,
        "verification": verification,
    }
    _write_evidence("release_check", result)
    return (0 if ok else 1), result


def _emit(code: int, result: dict[str, Any]) -> int:
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description="eMEGA productivity website operator CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    config_parser = sub.add_parser("config-check")
    config_parser.add_argument("--config", type=Path, default=CONFIG)
    verify_parser = sub.add_parser("verify")
    group = verify_parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--step")
    group.add_argument("--all", action="store_true")
    sub.add_parser("status")
    sub.add_parser("backup")
    sub.add_parser("restore-check")
    sub.add_parser("release-check")
    args = parser.parse_args()

    if args.command == "doctor":
        return _emit(*doctor())
    if args.command == "config-check":
        return _emit(*config_check(args.config))
    if args.command == "verify":
        return _emit(*verify(step=args.step, verify_all=args.all))
    if args.command == "status":
        return _emit(*status())
    if args.command == "backup":
        return _emit(*backup())
    if args.command == "restore-check":
        return _emit(*restore_check())
    if args.command == "release-check":
        return _emit(*release_check())
    raise AssertionError("Unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
