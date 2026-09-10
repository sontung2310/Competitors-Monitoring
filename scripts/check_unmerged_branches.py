#!/usr/bin/env python3
"""Audit feature branches for work missing from their relevant base branch.

This is intentionally a small, read-only git/roadmap check. It understands
that squash merges leave the original branch commits unreachable from main,
so it reports patch-equivalent history separately from genuinely unmerged
work. The production track is allowed to diverge from main, so the default
audit evaluates both long-lived bases and uses the best matching base for each
feature branch. A checked-off roadmap item only fails the check when the
branch still contains a unique patch and its final tree is not already
represented on its relevant base.
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
DEFAULT_BASES = ("main", "production")
ROADMAP_KEY_PATTERN = re.compile(
    rf"(?:^|/)"
    + re.escape(BRANCH_PREFIX)
    + r"(?P<key>(?:\d+\.\d+[a-z]?|[pP](?:(?:\.\d+)+|\d+(?:\.\d+)*)))"
    + r"(?=[^A-Za-z0-9.]|$)"
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
    base: str = "main"
    base_statuses: tuple[tuple[str, str], ...] = ()

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
    if match is None:
        return None
    key = match.group("key")
    if key.lower().startswith("p"):
        suffix = key[1:]
        return f"P{suffix}" if suffix.startswith(".") else f"P.{suffix}"
    return key


def roadmap_item_checked(roadmap_text: str, key: str | None) -> bool | None:
    """Return True/False for an item or roll-up, None if unmapped.

    Dev branches map directly to items such as ``1.13``. Production feature
    branches commonly use the shorter ``p1`` form, which maps to the ``P.1``
    group whose status is the conjunction of its checked sub-items.
    """

    if key is None:
        return None
    pattern = re.compile(
        rf"^\s*-\s*\[([ xX])\]\s*{re.escape(key)}(?:\s|$)",
        re.MULTILINE,
    )
    match = pattern.search(roadmap_text)
    if match is not None:
        return match.group(1).lower() == "x"

    if key.startswith("P.") and key.count(".") == 1:
        child_pattern = re.compile(
            rf"^\s*-\s*\[([ xX])\]\s*{re.escape(key)}\.\d+(?:\s|$)",
            re.MULTILINE,
        )
        children = child_pattern.findall(roadmap_text)
        if children:
            return all(child.lower() == "x" for child in children)
    return None


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


@dataclass(frozen=True)
class _BaseComparison:
    base: str
    commits_not_reachable: int
    unique_patches: int
    status: str


_STATUS_PRIORITY = {
    "MERGED": 0,
    "PATCH_EQUIVALENT": 1,
    "HISTORY_ONLY_TREE_ALREADY_ON_BASE": 2,
    "UNMERGED": 3,
}


def _normalise_bases(base: str | Sequence[str]) -> tuple[str, ...]:
    if isinstance(base, str):
        return (base,)
    bases = tuple(base)
    if not bases:
        raise ValueError("at least one base branch is required")
    return bases


def _roadmap_texts(
    repo_root: Path,
    bases: Sequence[str],
    roadmap_path: Path | None,
) -> dict[str, str]:
    """Read each default roadmap from the base branch it describes."""

    if roadmap_path is not None:
        return {"custom": roadmap_path.read_text(encoding="utf-8")}

    dev_base = "main" if "main" in bases else bases[0]
    production_base = "production" if "production" in bases else bases[0]
    return {
        "dev": _run_git(repo_root, "show", f"{dev_base}:docs/roadmap.md"),
        "production": _run_git(
            repo_root,
            "show",
            f"{production_base}:docs/production-roadmap.md",
        ),
    }


def _select_base_comparison(
    comparisons: Sequence[_BaseComparison],
    roadmap_key: str | None,
) -> _BaseComparison:
    """Select the branch's relevant base, preferring production roadmap work."""

    if roadmap_key is not None and roadmap_key.startswith("P."):
        for comparison in comparisons:
            if comparison.base == "production":
                return comparison
    return min(
        comparisons,
        key=lambda comparison: _STATUS_PRIORITY.get(comparison.status, 99),
    )


def audit_branches(
    repo_root: Path,
    *,
    base: str | Sequence[str] = DEFAULT_BASES,
    roadmap_path: Path | None = None,
) -> list[BranchAudit]:
    """Audit all feature refs against one or more bases without changing state.

    Passing a single string retains the original single-base behavior. The
    default evaluates both ``main`` and ``production``.
    """

    bases = _normalise_bases(base)
    roadmap_texts = _roadmap_texts(repo_root, bases, roadmap_path)
    base_tree_hashes = {
        base_name: set(
            _run_git(repo_root, "log", "--format=%T", base_name).splitlines()
        )
        for base_name in bases
    }
    audits: list[BranchAudit] = []
    for name in feature_branch_names(repo_root):
        ref = _resolve_branch_ref(repo_root, name)
        tip_tree = _run_git(repo_root, "rev-parse", f"{ref}^{{tree}}")
        key = roadmap_item_key(name)
        if roadmap_path is not None:
            roadmap_checked = roadmap_item_checked(roadmap_texts["custom"], key)
        elif key is not None and key.startswith("P."):
            roadmap_checked = roadmap_item_checked(roadmap_texts["production"], key)
        else:
            roadmap_checked = roadmap_item_checked(roadmap_texts["dev"], key)

        comparisons: list[_BaseComparison] = []
        for base_name in bases:
            commits_not_reachable = int(
                _run_git(repo_root, "rev-list", "--count", f"{base_name}..{ref}")
            )
            unique_patches = _count_unique_patches(repo_root, base_name, ref)
            reachable = _git_succeeds(
                repo_root,
                "merge-base",
                "--is-ancestor",
                ref,
                base_name,
            )
            comparisons.append(
                _BaseComparison(
                    base=base_name,
                    commits_not_reachable=commits_not_reachable,
                    unique_patches=unique_patches,
                    status=classify_branch(
                        reachable_from_base=reachable,
                        unique_patches=unique_patches,
                        tip_tree=tip_tree,
                        base_tree_hashes=base_tree_hashes[base_name],
                    ),
                )
            )

        selected = _select_base_comparison(comparisons, key)
        audits.append(
            BranchAudit(
                name=name,
                ref=ref,
                commits_not_reachable=selected.commits_not_reachable,
                unique_patches=selected.unique_patches,
                roadmap_key=key,
                roadmap_checked=roadmap_checked,
                status=selected.status,
                base=selected.base,
                base_statuses=tuple(
                    (comparison.base, comparison.status) for comparison in comparisons
                ),
            )
        )
    return audits


def _roadmap_label(value: bool | None) -> str:
    if value is None:
        return "UNKNOWN"
    return "CHECKED" if value else "UNCHECKED"


def format_audit(audits: Sequence[BranchAudit], base: str | Sequence[str]) -> str:
    bases = _normalise_bases(base)
    lines = [f"base={','.join(bases)}", f"feature_branches={len(audits)}"]
    warnings = [audit for audit in audits if audit.is_actionable_warning]
    for audit in audits:
        warning = " WARNING=CHECKED_OFF_BUT_UNMERGED" if audit.is_actionable_warning else ""
        base_detail = ""
        if audit.base_statuses:
            status_summary = ",".join(
                f"{base_name}:{status}" for base_name, status in audit.base_statuses
            )
            base_detail = f" selected_base={audit.base} base_statuses={status_summary}"
        lines.append(
            f"{audit.name}: status={audit.status} "
            f"commits_not_reachable={audit.commits_not_reachable} "
            f"unique_patches={audit.unique_patches} "
            f"roadmap={audit.roadmap_key or 'UNKNOWN'} "
            f"roadmap_state={_roadmap_label(audit.roadmap_checked)}"
            f"{base_detail}{warning}"
        )
    if warnings:
        lines.append(f"FAIL: {len(warnings)} checked-off roadmap branch(es) have unique unmerged work")
    else:
        lines.append("PASS: no checked-off roadmap branch has unique unmerged work")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit feature branches for unique work missing from main or production."
        )
    )
    parser.add_argument(
        "--base",
        default=None,
        help="single base branch to audit against (default: main and production)",
    )
    parser.add_argument(
        "--roadmap",
        type=Path,
        default=None,
        help="roadmap file (defaults to docs/roadmap.md)",
    )
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    bases = DEFAULT_BASES if args.base is None else (args.base,)
    roadmap_path = args.roadmap
    if roadmap_path is not None and not roadmap_path.is_absolute():
        roadmap_path = repo_root / roadmap_path
    try:
        audits = audit_branches(
            repo_root,
            base=bases,
            roadmap_path=roadmap_path,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(format_audit(audits, bases))
    return 1 if any(audit.is_actionable_warning for audit in audits) else 0


if __name__ == "__main__":
    raise SystemExit(main())
