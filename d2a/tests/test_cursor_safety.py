from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from d2a.core.message import Message
from d2a.d2o import main


class FailingDestination:
    def download(self, _messages):
        raise RuntimeError("attachment download failed")


def test_destination_failure_does_not_advance_cursor_or_react():
    state = {
        "channel": {
            "last_message_id": "100",
            "interval_hours": 1,
            "timezone": "Asia/Seoul",
        }
    }
    messages = [
        Message(
            id="101",
            content="meeting",
            author="user",
            timestamp="2026-08-10T12:00:00+09:00",
            attachments=[],
            jump_url="jump",
        )
    ]
    saved = []
    reactions = []

    with pytest.raises(RuntimeError, match="attachment download failed"):
        main.run_download(
            config={
                "destination": "obsidian",
                "default_interval_hours": 1,
                "default_timezone": "Asia/Seoul",
            },
            state=state,
            channel_id="channel",
            guild_id="guild",
            token="token",
            vault_root="unused",
            fetch_fn=lambda **_kwargs: messages,
            adapter=FailingDestination(),
            state_saver=lambda snapshot: saved.append(snapshot),
            mark_fn=lambda *args: reactions.append(args),
            now=datetime(2026, 8, 10, 12, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        )

    assert state["channel"]["last_message_id"] == "100"
    assert saved == []
    assert reactions == []
