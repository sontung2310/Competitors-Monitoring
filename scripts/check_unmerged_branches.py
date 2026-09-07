#!/usr/bin/env python3
"""Audit feature branches for work missing from the base branch.

This is intentionally a small, read-only git/roadmap check. It understands
that squash merges leave the original branch commits unreachable from main,
so it reports patch-equivalent history separately from genuinely unmerged
work. A checked-off roadmap item only fails the check when the branch still
contains a unique patch and its final tree is not already represented on main.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


BRANCH_PREFIX = "feature/"
ROADMAP_KEY_PATTERN = re.compile(
    rf"(?:^|/)" + re.escape(BRANCH_PREFIX) + r"(?P<key>\d+\.\d+[a-z]?)"
)


@dataclass(frozen=True)
class BranchAudit:
    name: str
    ref: str
    commits_not_reachable: int
    unique_patches: int
    roadmap_key: str | None
    roadmap_checked: bool | None
    status: str

    @property
    def is_actionable_warning(self) -> bool:
        """Whether this branch is completed-by-roadmap but still unmerged."""

        return self.status == "UNMERGED" and self.roadmap_checked is True


def _run_git(repo_root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout.strip()


def _git_succeeds(repo_root: Path, *args: str) -> bool:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _resolve_branch_ref(repo_root: Path, name: str) -> str:
    for ref in (name, f"origin/{name}"):
        if _git_succeeds(repo_root, "rev-parse", "--verify", ref):
            return ref
    raise RuntimeError(f"could not resolve feature branch {name!r}")


def feature_branch_names(repo_root: Path) -> list[str]:
    """Return deduplicated local/origin feature branch names."""

    refs = _run_git(
        repo_root,
        "for-each-ref",
        "--format=%(refname:short)",
        "refs/heads/feature",
        "refs/remotes/origin/feature",
    ).splitlines()
    names = set()
    for ref in refs:
        if ref.startswith("origin/"):
            ref = ref.removeprefix("origin/")
        if ref.startswith(BRANCH_PREFIX):
            names.add(ref)
    return sorted(names)


def roadmap_item_key(branch_name: str) -> str | None:
    match = ROADMAP_KEY_PATTERN.search(branch_name)
    return match.group("key") if match else None


def roadmap_item_checked(roadmap_text: str, key: str | None) -> bool | None:
    """Return True/False for a top-level roadmap item, None if unmapped."""

    if key is None:
        return None
    pattern = re.compile(
        rf"^\s*-\s*\[([ xX])\]\s*{re.escape(key)}(?:\s|$)",
        re.MULTILINE,
    )
    match = pattern.search(roadmap_text)
    if match is None:
        return None
    return match.group(1).lower() == "x"


def classify_branch(
    *,
    reachable_from_base: bool,
    unique_patches: int,
    tip_tree: str,
    base_tree_hashes: set[str],
) -> str:
    """Classify ancestry while accounting for squash merges and stale refs."""

    if reachable_from_base:
        return "MERGED"
    if unique_patches == 0:
        return "PATCH_EQUIVALENT"
    if tip_tree in base_tree_hashes:
        return "HISTORY_ONLY_TREE_ALREADY_ON_BASE"
    return "UNMERGED"


def _count_unique_patches(repo_root: Path, base: str, ref: str) -> int:
    lines = _run_git(repo_root, "cherry", base, ref).splitlines()
    return sum(line.startswith("+") for line in lines)


def audit_branches(
    repo_root: Path,
    *,
    base: str = "main",
    roadmap_path: Path | None = None,
) -> list[BranchAudit]:
    """Audit all feature refs against ``base`` without changing repository state."""

    roadmap_file = roadmap_path or repo_root / "docs" / "roadmap.md"
    roadmap_text = roadmap_file.read_text(encoding="utf-8")
    base_tree_hashes = set(
        _run_git(repo_root, "log", "--format=%T", base).splitlines()
    )
    audits: list[BranchAudit] = []
    for name in feature_branch_names(repo_root):
        ref = _resolve_branch_ref(repo_root, name)
        commits_not_reachable = int(
            _run_git(repo_root, "rev-list", "--count", f"{base}..{ref}")
        )
        unique_patches = _count_unique_patches(repo_root, base, ref)
        reachable = _git_succeeds(
            repo_root,
            "merge-base",
            "--is-ancestor",
            ref,
            base,
        )
        tip_tree = _run_git(repo_root, "rev-parse", f"{ref}^{{tree}}")
        key = roadmap_item_key(name)
        audits.append(
            BranchAudit(
                name=name,
                ref=ref,
                commits_not_reachable=commits_not_reachable,
                unique_patches=unique_patches,
                roadmap_key=key,
                roadmap_checked=roadmap_item_checked(roadmap_text, key),
                status=classify_branch(
                    reachable_from_base=reachable,
                    unique_patches=unique_patches,
                    tip_tree=tip_tree,
                    base_tree_hashes=base_tree_hashes,
                ),
            )
        )
    return audits


def _roadmap_label(value: bool | None) -> str:
    if value is None:
        return "UNKNOWN"
    return "CHECKED" if value else "UNCHECKED"


def format_audit(audits: Sequence[BranchAudit], base: str) -> str:
    lines = [f"base={base}", f"feature_branches={len(audits)}"]
    warnings = [audit for audit in audits if audit.is_actionable_warning]
    for audit in audits:
        warning = " WARNING=CHECKED_OFF_BUT_UNMERGED" if audit.is_actionable_warning else ""
        lines.append(
            f"{audit.name}: status={audit.status} "
            f"commits_not_reachable={audit.commits_not_reachable} "
            f"unique_patches={audit.unique_patches} "
            f"roadmap={audit.roadmap_key or 'UNKNOWN'} "
            f"roadmap_state={_roadmap_label(audit.roadmap_checked)}{warning}"
        )
    if warnings:
        lines.append(f"FAIL: {len(warnings)} checked-off roadmap branch(es) have unique unmerged work")
    else:
        lines.append("PASS: no checked-off roadmap branch has unique unmerged work")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit feature branches for unique work missing from main."
    )
    parser.add_argument("--base", default="main", help="base branch to audit against")
    parser.add_argument(
        "--roadmap",
        type=Path,
        default=None,
        help="roadmap file (defaults to docs/roadmap.md)",
    )
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    roadmap_path = args.roadmap
    if roadmap_path is not None and not roadmap_path.is_absolute():
        roadmap_path = repo_root / roadmap_path
    try:
        audits = audit_branches(
            repo_root,
            base=args.base,
            roadmap_path=roadmap_path,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(format_audit(audits, args.base))
    return 1 if any(audit.is_actionable_warning for audit in audits) else 0


if __name__ == "__main__":
    raise SystemExit(main())
