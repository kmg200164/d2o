import json
from pathlib import Path

import pytest

from d2a.d2o import main


def test_resolve_repo_path_rejects_parent_traversal(workspace_tmp):
    with pytest.raises(ValueError, match="inside destination root"):
        main.resolve_repo_path(workspace_tmp, "../outside.json", "state path")


def test_resolve_repo_path_rejects_absolute_path(workspace_tmp):
    outside = (workspace_tmp.parent / "outside.json").resolve()

    with pytest.raises(ValueError, match="relative path"):
        main.resolve_repo_path(workspace_tmp, outside, "state path")


def test_load_runtime_from_env_builds_repo_owned_paths(workspace_tmp):
    env = {
        "D2O_DESTINATION_ROOT": str(workspace_tmp),
        "D2O_TARGET_FOLDER": "회의록",
        "D2O_STATE_PATH": ".d2o/meeting-state.json",
        "D2O_FRONTMATTER_JSON": json.dumps(
            {"tags": [], "duration": "", "attendees": []}, ensure_ascii=False
        ),
        "D2O_CALLOUT": "> [!warning] 원문 그대로",
        "D2O_DEFAULT_INTERVAL_HOURS": "1",
        "D2O_DEFAULT_TIMEZONE": "Asia/Seoul",
    }

    config, destination_root, state_path = main.load_runtime_from_env(env)

    assert destination_root == workspace_tmp.resolve()
    assert state_path == workspace_tmp.resolve() / ".d2o" / "meeting-state.json"
    assert config == {
        "destination": "obsidian",
        "default_interval_hours": 1,
        "default_timezone": "Asia/Seoul",
        "obsidian": {
            "target_folder": "회의록",
            "frontmatter": {"tags": [], "duration": "", "attendees": []},
            "callout": "> [!warning] 원문 그대로",
        },
    }


def test_load_runtime_from_env_rejects_non_object_frontmatter(workspace_tmp):
    env = {
        "D2O_DESTINATION_ROOT": str(workspace_tmp),
        "D2O_TARGET_FOLDER": "회의록",
        "D2O_STATE_PATH": ".d2o/meeting-state.json",
        "D2O_FRONTMATTER_JSON": "[]",
        "D2O_CALLOUT": "",
    }

    with pytest.raises(ValueError, match="JSON object"):
        main.load_runtime_from_env(env)
