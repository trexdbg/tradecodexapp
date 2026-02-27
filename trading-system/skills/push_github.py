from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def push_to_github(
    message: str,
    remote: str = "origin",
    branch: str | None = None,
    paths: list[str] | None = None,
    allow_empty: bool = False,
    dry_run: bool = False,
):
    _ensure_git_repo(REPO_ROOT)
    active_branch = branch or _current_branch(REPO_ROOT)

    plan = {
        "repo_root": str(REPO_ROOT),
        "remote": remote,
        "branch": active_branch,
        "paths": paths or ["<ALL>"],
        "message": message,
        "allow_empty": allow_empty,
    }
    if dry_run:
        return {
            "status": "dry_run",
            "plan": plan,
            "staged_files": [],
            "commit_sha": None,
            "pushed": False,
        }

    if paths:
        _run_git(["add", "--", *paths], REPO_ROOT)
    else:
        _run_git(["add", "-A"], REPO_ROOT)

    staged_files = _run_git(["diff", "--cached", "--name-only"], REPO_ROOT).stdout.splitlines()
    if not staged_files and not allow_empty:
        return {
            "status": "no_changes",
            "plan": plan,
            "staged_files": [],
            "commit_sha": None,
            "pushed": False,
        }

    commit_args = ["commit", "-m", message]
    if allow_empty:
        commit_args.insert(1, "--allow-empty")
    _run_git(commit_args, REPO_ROOT)

    commit_sha = _run_git(["rev-parse", "--short", "HEAD"], REPO_ROOT).stdout.strip()
    _run_git(["push", remote, active_branch], REPO_ROOT)

    return {
        "status": "pushed",
        "plan": plan,
        "staged_files": staged_files,
        "commit_sha": commit_sha,
        "pushed": True,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Stage, commit, and push repository changes to GitHub."
    )
    parser.add_argument(
        "--message",
        default="chore: update trading snapshot",
        help="Commit message",
    )
    parser.add_argument(
        "--remote",
        default="origin",
        help="Git remote name",
    )
    parser.add_argument(
        "--branch",
        default=None,
        help="Branch to push. Defaults to current branch.",
    )
    parser.add_argument(
        "--paths",
        nargs="*",
        default=None,
        help="Optional file paths to stage. Default: stage all changes.",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Allow creating an empty commit when no changes are staged.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show execution plan without running git add/commit/push.",
    )
    args = parser.parse_args()

    result = push_to_github(
        message=args.message,
        remote=args.remote,
        branch=args.branch,
        paths=args.paths,
        allow_empty=args.allow_empty,
        dry_run=args.dry_run,
    )

    print(f"Status: {result['status']}")
    print(f"Repo: {result['plan']['repo_root']}")
    print(f"Target: {result['plan']['remote']}/{result['plan']['branch']}")
    print(f"Commit message: {result['plan']['message']}")
    print(f"Paths: {', '.join(result['plan']['paths'])}")
    if result["commit_sha"]:
        print(f"Commit: {result['commit_sha']}")
    if result["status"] == "no_changes":
        print("No staged changes to commit.")


def _ensure_git_repo(repo_root: Path):
    probe = _run_git(["rev-parse", "--is-inside-work-tree"], repo_root)
    if probe.stdout.strip().lower() != "true":
        raise RuntimeError(f"Path is not a git repository: {repo_root}")


def _current_branch(repo_root: Path):
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_root).stdout.strip()
    if not branch or branch == "HEAD":
        raise RuntimeError("Detached HEAD is not supported. Please provide --branch.")
    return branch


def _run_git(args: list[str], cwd: Path):
    completed = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        stdout = completed.stdout.strip()
        detail = stderr or stdout or f"git {' '.join(args)} failed"
        raise RuntimeError(detail)
    return completed


if __name__ == "__main__":
    main()
