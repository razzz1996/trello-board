from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import UTC, date, datetime
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


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    app_secret = ROOT / "runtime" / "secrets" / "postgres_app_secret.txt"
    maintenance_secret = ROOT / "runtime" / "secrets" / "postgres_maintenance_secret.txt"
    env.setdefault("PRODUCTIVITY_DB_USER", "productivity_app")
    env.setdefault("PRODUCTIVITY_DB_HOST", "127.0.0.1")
    env.setdefault("PRODUCTIVITY_DB_PORT", "5432")
    if app_secret.is_file():
        env.setdefault("PRODUCTIVITY_DB_PASSWORD_FILE", str(app_secret))
    env.setdefault("PRODUCTIVITY_MAINTENANCE_DB_USER", "productivity_maintenance")
    if maintenance_secret.is_file():
        env.setdefault("PRODUCTIVITY_MAINTENANCE_DB_PASSWORD_FILE", str(maintenance_secret))
    return env


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
            env=_subprocess_env(),
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
    elif name in {"psql", "pg_dump", "pg_restore", "createdb", "dropdb"}:
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
        _check("frontend_build", [str(NPM), "run", "build"], cwd=ROOT / "frontend"),
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
        checks.append(
            _check(
                "database_integration",
                [
                    str(PYTHON),
                    "-m",
                    "pytest",
                    "tests",
                    "--reuse-db",
                    "-q",
                ],
                timeout=240,
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


def _read_secret_file(env_name: str) -> str:
    raw = os.environ.get(env_name)
    if not raw:
        defaults = {
            "PRODUCTIVITY_DB_PASSWORD_FILE": ROOT / "runtime" / "secrets" / "postgres_app_secret.txt",
            "PRODUCTIVITY_MAINTENANCE_DB_PASSWORD_FILE": ROOT / "runtime" / "secrets" / "postgres_maintenance_secret.txt",
        }
        candidate = defaults.get(env_name)
        if candidate is None or not candidate.is_file():
            raise RuntimeError(f"{env_name} is not configured.")
        raw = str(candidate)
    path = Path(raw)
    if not path.is_file():
        raise RuntimeError(f"{env_name} does not point to an existing file.")
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"{env_name} points to an empty file.")
    return value


def _database_identity(config: dict[str, Any]) -> tuple[str, str, str, str]:
    environment = str(config["environment"])
    default_name = {
        "development": "productivity_dev",
        "test": "productivity_test",
        "pilot": "productivity_pilot",
    }[environment]
    return (
        os.environ.get("PRODUCTIVITY_DB_HOST", "127.0.0.1"),
        os.environ.get("PRODUCTIVITY_DB_PORT", "5432"),
        os.environ.get("PRODUCTIVITY_DB_USER", "productivity_app"),
        os.environ.get("PRODUCTIVITY_DB_NAME", default_name),
    )


def _run_with_password(args: list[str], password: str, *, timeout: int = 600) -> dict[str, Any]:
    env = os.environ.copy()
    env["PGPASSWORD"] = password
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argument arrays; shell=False
            args,
            cwd=ROOT,
            timeout=timeout,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            env=env,
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prune_backups(
    directory: Path,
    *,
    daily_retention: int,
    weekly_retention: int,
) -> list[str]:
    paths = sorted(
        directory.glob("productivity_*.dump"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    keep: set[Path] = set()
    kept_dates: set[date] = set()
    kept_weeks: set[tuple[int, int]] = set()

    for path in paths:
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        backup_date = modified.date()
        iso = backup_date.isocalendar()
        week_key = (iso.year, iso.week)

        if backup_date not in kept_dates and len(kept_dates) < daily_retention:
            kept_dates.add(backup_date)
            keep.add(path)
        if week_key not in kept_weeks and len(kept_weeks) < weekly_retention:
            kept_weeks.add(week_key)
            keep.add(path)

    removed: list[str] = []
    for path in paths:
        if path not in keep:
            path.unlink(missing_ok=True)
            removed.append(path.name)
    return removed


def backup() -> tuple[int, dict[str, Any]]:
    pg_dump = _tool("pg_dump")
    if pg_dump is None:
        return 1, {"ok": False, "error": "pg_dump is unavailable; PostgreSQL is not installed."}
    try:
        config = validate_files(CONFIG, SCHEMA)
        password = _read_secret_file("PRODUCTIVITY_DB_PASSWORD_FILE")
    except (ConfigValidationError, RuntimeError) as exc:
        return 1, {"ok": False, "error": str(exc)}

    target_value = config.get("backup_target")
    if not target_value:
        return 1, {"ok": False, "error": "backup_target is not configured."}
    target_dir = Path(str(target_value))
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return 1, {"ok": False, "error": f"Cannot access backup_target: {exc}"}

    local_dir = ROOT / "runtime" / "backups"
    local_dir.mkdir(parents=True, exist_ok=True)
    host, port, user, db_name = _database_identity(config)
    filename = f"productivity_{config['environment']}_{_now_slug()}.dump"
    local_path = local_dir / filename
    dump_result = _run_with_password(
        [
            pg_dump,
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            "--host",
            host,
            "--port",
            port,
            "--username",
            user,
            "--file",
            str(local_path),
            db_name,
        ],
        password,
    )
    if dump_result["exit_code"] != 0 or not local_path.is_file():
        local_path.unlink(missing_ok=True)
        result = {"ok": False, "stage": "pg_dump", "dump": dump_result}
        _write_evidence("backup_failed", result)
        return 1, result

    local_hash = _sha256(local_path)
    copied_path = target_dir / filename
    try:
        shutil.copy2(local_path, copied_path)
        copied_hash = _sha256(copied_path)
    except OSError as exc:
        result = {"ok": False, "stage": "copy", "error": str(exc), "local_path": str(local_path)}
        _write_evidence("backup_failed", result)
        return 1, result
    if copied_hash != local_hash:
        copied_path.unlink(missing_ok=True)
        result = {"ok": False, "stage": "verify_copy", "error": "SHA-256 mismatch after copy."}
        _write_evidence("backup_failed", result)
        return 1, result

    daily_retention = int(config["backup_daily_retention"])
    weekly_retention = int(config["backup_weekly_retention"])
    removed_local = _prune_backups(
        local_dir,
        daily_retention=daily_retention,
        weekly_retention=weekly_retention,
    )
    removed_target = _prune_backups(
        target_dir,
        daily_retention=daily_retention,
        weekly_retention=weekly_retention,
    )
    result = {
        "ok": True,
        "local_path": str(local_path),
        "independent_copy": str(copied_path),
        "sha256": local_hash,
        "daily_retention": daily_retention,
        "weekly_retention": weekly_retention,
        "removed_local": removed_local,
        "removed_target": removed_target,
    }
    evidence = _write_evidence("backup", result)
    result["evidence_path"] = str(evidence.relative_to(ROOT))
    return 0, result


def restore_check(backup_path: Path | None = None) -> tuple[int, dict[str, Any]]:
    required_tools = {name: _tool(name) for name in ("createdb", "dropdb", "pg_restore", "psql")}
    missing = [name for name, path in required_tools.items() if path is None]
    if missing:
        return 1, {
            "ok": False,
            "error": "PostgreSQL restore tools are unavailable.",
            "missing": missing,
        }
    try:
        config = validate_files(CONFIG, SCHEMA)
        if not config["restore_mode"] or config["slack_mode"] != "off":
            raise RuntimeError("Restore drill requires restore_mode=true and slack_mode=off.")
        maintenance_user = os.environ.get("PRODUCTIVITY_MAINTENANCE_DB_USER")
        if not maintenance_user:
            raise RuntimeError("PRODUCTIVITY_MAINTENANCE_DB_USER is not configured.")
        password = _read_secret_file("PRODUCTIVITY_MAINTENANCE_DB_PASSWORD_FILE")
    except (ConfigValidationError, RuntimeError) as exc:
        return 1, {"ok": False, "error": str(exc)}

    if backup_path is None:
        candidates = sorted((ROOT / "runtime" / "backups").glob("productivity_*.dump"))
        if not candidates:
            return 1, {
                "ok": False,
                "error": "No local backup is available for restore verification.",
            }
        backup_path = candidates[-1]
    backup_path = backup_path.resolve()
    if not backup_path.is_file():
        return 1, {"ok": False, "error": f"Backup file does not exist: {backup_path}"}

    host, port, _, _ = _database_identity(config)
    restore_db = f"productivity_restore_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    createdb = str(required_tools["createdb"])
    dropdb = str(required_tools["dropdb"])
    pg_restore = str(required_tools["pg_restore"])
    psql = str(required_tools["psql"])
    create = _run_with_password(
        [createdb, "--host", host, "--port", port, "--username", maintenance_user, restore_db],
        password,
    )
    if create["exit_code"] != 0:
        result = {"ok": False, "stage": "createdb", "result": create}
        _write_evidence("restore_failed", result)
        return 1, result

    restore_result: dict[str, Any] | None = None
    smoke_result: dict[str, Any] | None = None
    cleanup_result: dict[str, Any] | None = None
    try:
        restore_result = _run_with_password(
            [
                pg_restore,
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                "--host",
                host,
                "--port",
                port,
                "--username",
                maintenance_user,
                "--dbname",
                restore_db,
                str(backup_path),
            ],
            password,
        )
        if restore_result["exit_code"] == 0:
            smoke_result = _run_with_password(
                [
                    psql,
                    "--host",
                    host,
                    "--port",
                    port,
                    "--username",
                    maintenance_user,
                    "--dbname",
                    restore_db,
                    "--no-psqlrc",
                    "--tuples-only",
                    "--command",
                    "SELECT COUNT(*) FROM django_migrations; SELECT COUNT(*) FROM accounts_user; SELECT COUNT(*) FROM boards_board; SELECT COUNT(*) FROM workitems_task;",
                ],
                password,
            )
    finally:
        cleanup_result = _run_with_password(
            [
                dropdb,
                "--if-exists",
                "--host",
                host,
                "--port",
                port,
                "--username",
                maintenance_user,
                restore_db,
            ],
            password,
        )

    ok = bool(
        restore_result
        and restore_result["exit_code"] == 0
        and smoke_result
        and smoke_result["exit_code"] == 0
        and cleanup_result
        and cleanup_result["exit_code"] == 0
    )
    result = {
        "ok": ok,
        "backup_path": str(backup_path),
        "restore_database": restore_db,
        "restore": restore_result,
        "smoke": smoke_result,
        "cleanup": cleanup_result,
    }
    evidence = _write_evidence("restore_check", result)
    result["evidence_path"] = str(evidence.relative_to(ROOT))
    return (0 if ok else 1), result


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
    restore_parser = sub.add_parser("restore-check")
    restore_parser.add_argument("--backup", type=Path)
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
        return _emit(*restore_check(args.backup))
    if args.command == "release-check":
        return _emit(*release_check())
    raise AssertionError("Unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
