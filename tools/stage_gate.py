#!/usr/bin/env python3
"""Manual stage gate for the Luna Validator + Preference Ranker project.

Codex may verify scope and request completion. Only a user who possesses
LUNA_STAGE_GATE_KEY may initialize, advance, or close the stage state.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import hmac
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

STATE_REL = Path(".codex/stage_state.json")
PLAN_REL = Path(".codex/stage_plan.json")
REQUEST_DIR_REL = Path(".codex/completion_requests")
IGNORED_CONTROL_PATHS = {STATE_REL.as_posix()}
KEY_ENV = "LUNA_STAGE_GATE_KEY"


class GateError(RuntimeError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and proc.returncode != 0:
        raise GateError(
            f"Command failed ({proc.returncode}): {' '.join(cmd)}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc


def repo_root() -> Path:
    probe = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if probe.returncode == 0:
        return Path(probe.stdout.strip()).resolve()
    return Path.cwd().resolve()


def require_git_repo(root: Path) -> None:
    if run(["git", "rev-parse", "--is-inside-work-tree"], root, check=False).returncode != 0:
        raise GateError("This command must run inside a Git repository.")


def git_head(root: Path) -> str:
    return run(["git", "rev-parse", "HEAD"], root).stdout.strip()


def git_status_porcelain(root: Path) -> list[str]:
    out = run(["git", "status", "--porcelain=v1"], root).stdout
    lines: list[str] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        # Completion requests are local gate receipts created after the stage commit.
        # They intentionally remain outside the stage commit and must not block user advance.
        path_part = line[3:] if len(line) >= 4 else line
        path_part = normalize_path(path_part.split(" -> ")[-1])
        if path_part.startswith(REQUEST_DIR_REL.as_posix() + "/"):
            continue
        lines.append(line)
    return lines


def require_clean_worktree(root: Path) -> None:
    dirty = git_status_porcelain(root)
    if dirty:
        raise GateError("Worktree must be clean:\n" + "\n".join(dirty))


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise GateError(f"Required file not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GateError(f"Invalid JSON: {path}: {exc}") from exc


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        raise GateError(f"Protected file missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def get_key(required: bool) -> bytes | None:
    value = os.environ.get(KEY_ENV)
    if not value:
        if required:
            raise GateError(
                f"{KEY_ENV} is required for this command. "
                "Only the user should possess this key."
            )
        return None
    if len(value) < 32:
        raise GateError(f"{KEY_ENV} must contain at least 32 characters.")
    return value.encode("utf-8")


def state_payload(state: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in state.items() if key != "signature"}


def sign_state(state: dict[str, Any], key: bytes) -> str:
    return hmac.new(key, canonical_json(state_payload(state)), hashlib.sha256).hexdigest()


def verify_state_signature(state: dict[str, Any], key: bytes) -> None:
    signature = state.get("signature")
    if not isinstance(signature, str) or not signature:
        raise GateError("Stage state has no signature.")
    expected = sign_state(state, key)
    if not hmac.compare_digest(signature, expected):
        raise GateError("Stage state signature is invalid.")


def plan_hash(root: Path) -> str:
    return sha256_file(root / PLAN_REL)


def stage_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    stages = plan.get("stages")
    if not isinstance(stages, list):
        raise GateError("stage_plan.json must contain a stages list.")
    result: dict[str, dict[str, Any]] = {}
    for stage in stages:
        if not isinstance(stage, dict) or not isinstance(stage.get("id"), str):
            raise GateError("Every stage must have a string id.")
        if stage["id"] in result:
            raise GateError(f"Duplicate stage id: {stage['id']}")
        result[stage["id"]] = stage
    return result


def protected_hashes(root: Path, plan: dict[str, Any]) -> dict[str, str]:
    files = plan.get("protected_files", [])
    if not isinstance(files, list):
        raise GateError("protected_files must be a list.")
    result: dict[str, str] = {}
    for rel in files:
        if not isinstance(rel, str):
            raise GateError("protected_files entries must be strings.")
        result[rel] = sha256_file(root / rel)
    return result


def verify_protected_files(root: Path, plan: dict[str, Any], state: dict[str, Any]) -> None:
    expected = state.get("protected_hashes")
    if not isinstance(expected, dict):
        raise GateError("Stage state has no protected_hashes map.")
    actual = protected_hashes(root, plan)
    if actual != expected:
        changed = sorted(set(actual) | set(expected))
        details = [
            f"{path}: state={expected.get(path)} current={actual.get(path)}"
            for path in changed
            if actual.get(path) != expected.get(path)
        ]
        raise GateError("Protected control files changed:\n" + "\n".join(details))


def validate_state(root: Path, require_signature: bool) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    plan = load_json(root / PLAN_REL)
    state = load_json(root / STATE_REL)
    stages = stage_map(plan)

    if state.get("project_id") != plan.get("project_id"):
        raise GateError("Project id mismatch between plan and state.")
    active = state.get("active_stage")
    if active not in stages:
        raise GateError(f"Unknown active_stage: {active}")
    current_plan_hash = plan_hash(root)
    if state.get("plan_sha256") != current_plan_hash:
        raise GateError("stage_plan.json hash does not match signed state.")
    verify_protected_files(root, plan, state)

    key = get_key(required=require_signature)
    if key is not None:
        verify_state_signature(state, key)
        signature_status = "verified"
    else:
        signature_status = "not_verified_no_key"

    return plan, state, {"signature_status": signature_status, "stage": stages[active]}


def normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.lstrip("/")


def unique_paths(values: Iterable[str]) -> list[str]:
    return sorted({normalize_path(value.strip()) for value in values if value.strip()})


def changed_paths(root: Path, start_commit: str) -> list[str]:
    paths: list[str] = []
    # Committed changes since stage start.
    paths += run(
        ["git", "diff", "--name-only", f"{start_commit}..HEAD"], root
    ).stdout.splitlines()
    # Staged and unstaged changes.
    paths += run(["git", "diff", "--name-only", "--cached"], root).stdout.splitlines()
    paths += run(["git", "diff", "--name-only"], root).stdout.splitlines()
    # Untracked files, excluding .gitignore rules.
    paths += run(
        ["git", "ls-files", "--others", "--exclude-standard"], root
    ).stdout.splitlines()
    return [path for path in unique_paths(paths) if path not in IGNORED_CONTROL_PATHS]


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def scope_violations(
    root: Path, plan: dict[str, Any], state: dict[str, Any]
) -> tuple[list[str], list[str]]:
    stages = stage_map(plan)
    stage = stages[state["active_stage"]]
    start_commit = state.get("stage_start_commit")
    if not isinstance(start_commit, str) or not start_commit:
        raise GateError("stage_start_commit is missing from state.")

    paths = changed_paths(root, start_commit)
    always_allowed = plan.get("always_allowed_paths", [])
    allowed = stage.get("allowed_paths", [])
    forbidden = stage.get("forbidden_paths", [])
    protected = set(plan.get("protected_files", []))

    if not all(isinstance(item, str) for item in always_allowed + allowed + forbidden):
        raise GateError("Path patterns must all be strings.")

    violations: list[str] = []
    for path in paths:
        if path in protected:
            violations.append(f"protected control file: {path}")
            continue
        if matches_any(path, forbidden):
            violations.append(f"forbidden in {stage['id']}: {path}")
            continue
        if not matches_any(path, always_allowed + allowed):
            violations.append(f"outside allowed scope for {stage['id']}: {path}")
    return paths, violations


def command_init(args: argparse.Namespace, root: Path) -> None:
    require_git_repo(root)
    require_clean_worktree(root)
    plan = load_json(root / PLAN_REL)
    stages = stage_map(plan)
    if args.stage not in stages:
        raise GateError(f"Unknown stage: {args.stage}")
    state_path = root / STATE_REL
    if state_path.exists() and not args.force:
        raise GateError(f"State already exists: {state_path}. Use --force only after review.")

    key = get_key(required=True)
    assert key is not None
    state: dict[str, Any] = {
        "schema_version": 1,
        "project_id": plan["project_id"],
        "active_stage": args.stage,
        "status": "ACTIVE",
        "sequence": 0,
        "stage_start_commit": git_head(root),
        "approved_by": args.approved_by,
        "approved_at": utc_now(),
        "plan_sha256": plan_hash(root),
        "protected_hashes": protected_hashes(root, plan),
    }
    state["signature"] = sign_state(state, key)
    write_json(state_path, state)
    print(f"Initialized {args.stage}. Commit {STATE_REL.as_posix()} before starting Codex.")



def command_codex_safe(args: argparse.Namespace, root: Path) -> None:
    del args, root
    if os.environ.get(KEY_ENV):
        raise GateError(
            f"{KEY_ENV} is exposed in this process. Remove it before starting Codex. "
            "Use a separate approval terminal for init/advance/close."
        )
    print(f"Codex-safe check passed: {KEY_ENV} is not exposed.")

def command_verify(args: argparse.Namespace, root: Path) -> None:
    plan, state, details = validate_state(root, require_signature=args.require_signature)
    stage = details["stage"]
    print(
        json.dumps(
            {
                "ok": True,
                "active_stage": state["active_stage"],
                "status": state.get("status"),
                "model": stage.get("model"),
                "reasoning": stage.get("reasoning"),
                "signature": details["signature_status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if details["signature_status"] != "verified":
        print(
            f"WARNING: {KEY_ENV} is not present, so the HMAC signature was not verified. "
            "GitHub CI should use --require-signature.",
            file=sys.stderr,
        )


def command_status(args: argparse.Namespace, root: Path) -> None:
    del args
    plan, state, details = validate_state(root, require_signature=False)
    stage = details["stage"]
    print(f"Project: {plan['project_id']}")
    print(f"Active stage: {stage['id']} — {stage['name']}")
    print(f"Recommended model: {stage.get('model')} / {stage.get('reasoning')}")
    print(f"Prompt: {stage.get('prompt_file')}")
    print(f"Next stage: {stage.get('next_stage')}")
    print(f"Stage start commit: {state.get('stage_start_commit')}")
    print(f"State status: {state.get('status')}")


def command_check_scope(args: argparse.Namespace, root: Path) -> None:
    del args
    require_git_repo(root)
    plan, state, _ = validate_state(root, require_signature=False)
    paths, violations = scope_violations(root, plan, state)
    print(json.dumps({"changed_paths": paths}, ensure_ascii=False, indent=2))
    if violations:
        raise GateError("Scope violations:\n" + "\n".join(violations))
    print(f"Scope check passed for {state['active_stage']}.")


def command_request_completion(args: argparse.Namespace, root: Path) -> None:
    require_git_repo(root)
    plan, state, _ = validate_state(root, require_signature=False)
    if state["active_stage"] != args.stage:
        raise GateError(
            f"Requested stage {args.stage} does not match active stage {state['active_stage']}."
        )
    require_clean_worktree(root)
    paths, violations = scope_violations(root, plan, state)
    if violations:
        raise GateError("Scope violations:\n" + "\n".join(violations))

    report_rel = normalize_path(args.report)
    report_path = root / report_rel
    if not report_path.exists():
        raise GateError(f"Stage report not found: {report_rel}")

    request = {
        "schema_version": 1,
        "project_id": plan["project_id"],
        "stage": args.stage,
        "requested_at": utc_now(),
        "git_head": git_head(root),
        "stage_start_commit": state["stage_start_commit"],
        "report": report_rel,
        "report_sha256": sha256_file(report_path),
        "changed_paths": paths,
        "tests": args.test or [],
        "next_stage": stage_map(plan)[args.stage].get("next_stage"),
        "note": "This request does not unlock or advance the next stage.",
    }
    request_path = root / REQUEST_DIR_REL / f"{args.stage}.json"
    write_json(request_path, request)
    print(f"Completion request written: {request_path.relative_to(root)}")
    print("The active stage is unchanged. User review and signed advance are required.")


def command_advance(args: argparse.Namespace, root: Path) -> None:
    require_git_repo(root)
    require_clean_worktree(root)
    plan, state, _ = validate_state(root, require_signature=True)
    stages = stage_map(plan)
    current = stages[state["active_stage"]]
    expected_next = current.get("next_stage")
    if expected_next is None:
        raise GateError("Final stage has no next stage. Use close after review.")
    if args.to != expected_next:
        raise GateError(
            f"Invalid transition: {current['id']} may advance only to {expected_next}, not {args.to}."
        )

    request_path = root / REQUEST_DIR_REL / f"{current['id']}.json"
    request = load_json(request_path)
    if request.get("stage") != current["id"]:
        raise GateError("Completion request stage mismatch.")
    if request.get("git_head") != git_head(root):
        raise GateError(
            "Completion request is stale because HEAD changed. Re-run request-completion after review."
        )
    report_path = root / str(request.get("report"))
    if not report_path.exists() or request.get("report_sha256") != sha256_file(report_path):
        raise GateError("Completion report is missing or changed after the request.")

    paths, violations = scope_violations(root, plan, state)
    if violations:
        raise GateError("Scope violations:\n" + "\n".join(violations))

    key = get_key(required=True)
    assert key is not None
    new_state = {
        "schema_version": 1,
        "project_id": plan["project_id"],
        "active_stage": args.to,
        "status": "ACTIVE",
        "sequence": int(state.get("sequence", 0)) + 1,
        "stage_start_commit": git_head(root),
        "approved_by": args.approved_by,
        "approved_at": utc_now(),
        "previous_stage": current["id"],
        "previous_stage_report": request.get("report"),
        "previous_stage_changed_paths": paths,
        "plan_sha256": plan_hash(root),
        "protected_hashes": protected_hashes(root, plan),
    }
    new_state["signature"] = sign_state(new_state, key)
    write_json(root / STATE_REL, new_state)
    print(f"Advanced {current['id']} -> {args.to}.")
    print(f"Commit {STATE_REL.as_posix()}, switch to the recommended model, and start a new Codex session.")


def command_close(args: argparse.Namespace, root: Path) -> None:
    require_git_repo(root)
    require_clean_worktree(root)
    plan, state, _ = validate_state(root, require_signature=True)
    stages = stage_map(plan)
    current = stages[state["active_stage"]]
    if current.get("next_stage") is not None:
        raise GateError(f"{current['id']} is not the final stage.")

    request_path = root / REQUEST_DIR_REL / f"{current['id']}.json"
    request = load_json(request_path)
    if request.get("git_head") != git_head(root):
        raise GateError("Final completion request is stale.")

    key = get_key(required=True)
    assert key is not None
    closed = dict(state)
    closed["status"] = "CLOSED"
    closed["closed_at"] = utc_now()
    closed["closed_by"] = args.approved_by
    closed["signature"] = sign_state(closed, key)
    write_json(root / STATE_REL, closed)
    print("Project stage gate is CLOSED. Commit the signed state.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Initialize a signed stage state (user only).")
    p_init.add_argument("--stage", default="S00")
    p_init.add_argument("--approved-by", default="USER")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=command_init)

    p_safe = sub.add_parser(
        "codex-safe",
        help="Fail when the user-only stage key is exposed to the Codex process.",
    )
    p_safe.set_defaults(func=command_codex_safe)

    p_verify = sub.add_parser("verify", help="Verify plan, protected files, and optional signature.")
    p_verify.add_argument("--require-signature", action="store_true")
    p_verify.set_defaults(func=command_verify)

    p_status = sub.add_parser("status", help="Show the current stage and recommended model.")
    p_status.set_defaults(func=command_status)

    p_scope = sub.add_parser("check-scope", help="Check all changes against the active stage paths.")
    p_scope.set_defaults(func=command_check_scope)

    p_request = sub.add_parser(
        "request-completion",
        help="Create an unsigned completion request without advancing the stage.",
    )
    p_request.add_argument("--stage", required=True)
    p_request.add_argument("--report", required=True)
    p_request.add_argument("--test", action="append")
    p_request.set_defaults(func=command_request_completion)

    p_advance = sub.add_parser("advance", help="Advance to the exact next stage (user only).")
    p_advance.add_argument("--to", required=True)
    p_advance.add_argument("--approved-by", default="USER")
    p_advance.set_defaults(func=command_advance)

    p_close = sub.add_parser("close", help="Close the final stage (user only).")
    p_close.add_argument("--approved-by", default="USER")
    p_close.set_defaults(func=command_close)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    root = repo_root()
    try:
        args.func(args, root)
        return 0
    except GateError as exc:
        print(f"STAGE_GATE_ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # defensive: never silently pass a gate error
        print(f"STAGE_GATE_UNEXPECTED_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
