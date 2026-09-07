from __future__ import annotations

from scripts.check_unmerged_branches import (
    BranchAudit,
    classify_branch,
    format_audit,
    roadmap_item_checked,
    roadmap_item_key,
)


def test_roadmap_key_is_taken_from_feature_branch_number() -> None:
    assert roadmap_item_key("feature/1.13-diff-granularity-fix") == "1.13"
    assert roadmap_item_key("feature/1.14-simulated-change-verification") == "1.14"
    assert roadmap_item_key("chore/unmerged-branch-check") is None


def test_roadmap_item_checked_distinguishes_checked_unchecked_and_unknown() -> None:
    roadmap = """
- [x] 1.13 Product listing
- [ ] 1.14 Simulation
"""
    assert roadmap_item_checked(roadmap, "1.13") is True
    assert roadmap_item_checked(roadmap, "1.14") is False
    assert roadmap_item_checked(roadmap, "1.15") is None


def test_classification_does_not_flag_patch_equivalent_squash_history() -> None:
    assert classify_branch(
        reachable_from_base=False,
        unique_patches=0,
        tip_tree="tree-a",
        base_tree_hashes={"tree-a"},
    ) == "PATCH_EQUIVALENT"


def test_classification_recognizes_stale_history_with_tree_on_base() -> None:
    assert classify_branch(
        reachable_from_base=False,
        unique_patches=5,
        tip_tree="tree-a",
        base_tree_hashes={"tree-a", "tree-b"},
    ) == "HISTORY_ONLY_TREE_ALREADY_ON_BASE"


def test_classification_flags_unique_tree_not_on_base() -> None:
    assert classify_branch(
        reachable_from_base=False,
        unique_patches=1,
        tip_tree="tree-new",
        base_tree_hashes={"tree-a"},
    ) == "UNMERGED"


def test_format_audit_marks_checked_off_unique_work_as_a_warning() -> None:
    audit = BranchAudit(
        name="feature/1.14-simulated-change-verification",
        ref="feature/1.14-simulated-change-verification",
        commits_not_reachable=1,
        unique_patches=1,
        roadmap_key="1.14",
        roadmap_checked=True,
        status="UNMERGED",
    )
    report = format_audit([audit], "main")
    assert "WARNING=CHECKED_OFF_BUT_UNMERGED" in report
    assert "FAIL: 1 checked-off roadmap branch(es)" in report
    assert audit.is_actionable_warning is True
