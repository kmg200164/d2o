from pathlib import Path
from unittest.mock import patch

import pytest

from d2a.d2o import main


@pytest.mark.parametrize("git_marker", ["directory", "file"])
def test_find_vault_root_walks_up_and_accepts_worktree_git_marker(workspace_tmp, git_marker):
    root = workspace_tmp / "caller_repo"
    nested = root / "3-Output/Projects/d2a/d2o"
    nested.mkdir(parents=True)
    (root / "CLAUDE.md").write_text("adapter", encoding="utf-8")
    if git_marker == "directory":
        (root / ".git").mkdir()
    else:
        (root / ".git").write_text("gitdir: ../worktrees/example\n", encoding="utf-8")

    assert main.find_vault_root(nested / "main.py") == root


def test_find_vault_root_rejects_unsupported_git_marker_type(workspace_tmp):
    root = workspace_tmp / "caller_repo"
    nested = root / "3-Output/Projects/d2a/d2o"
    nested.mkdir(parents=True)
    (root / "CLAUDE.md").write_text("adapter", encoding="utf-8")
    marker = root / ".git"
    marker.write_text("unsupported marker", encoding="utf-8")
    real_is_file = Path.is_file
    real_is_dir = Path.is_dir

    def marker_is_not_file(path):
        if path == marker:
            return False
        if path.name == "CLAUDE.md" and path.parent != root:
            return False
        return real_is_file(path)

    def marker_is_not_directory(path):
        return False if path == marker else real_is_dir(path)

    with (
        patch.object(Path, "is_file", marker_is_not_file),
        patch.object(Path, "is_dir", marker_is_not_directory),
        pytest.raises(RuntimeError, match="vault root not found"),
    ):
        main.find_vault_root(nested / "main.py")
