from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from d2a.core.message import DiscordThread, Message
from d2a.core import discord_fetcher
from d2a.d2o import main


def test_fetch_threads_combines_active_and_archived_public_threads_for_parent():
    active = {
        "threads": [
            {"id": "thread-active", "name": "script", "parent_id": "parent", "thread_metadata": {"archived": False}},
            {"id": "other", "name": "other", "parent_id": "different", "thread_metadata": {"archived": False}},
        ]
    }
    archived = {
        "threads": [
            {"id": "thread-active", "name": "script", "parent_id": "parent", "thread_metadata": {"archived": True, "archive_timestamp": "2026-08-25T00:00:00+00:00"}},
            {"id": "thread-archived", "name": "old script", "parent_id": "parent", "thread_metadata": {"archived": True, "archive_timestamp": "2026-08-24T00:00:00+00:00"}},
        ],
        "has_more": False,
    }

    def response(payload):
        result = MagicMock()
        result.json.return_value = payload
        result.raise_for_status.return_value = None
        return result

    with patch("requests.get", side_effect=[response(active), response(archived)]) as get:
        threads = discord_fetcher.fetch_threads("parent", "guild", "token")

    assert [thread.id for thread in threads] == ["thread-active", "thread-archived"]
    assert threads[0].archived is False
    assert threads[1].archived is True
    assert get.call_count == 2


def test_run_download_uses_per_thread_cursor_for_late_replies():
    state = {
        "parent": {
            "last_message_id": "200",
            "interval_hours": 1,
            "timezone": "Asia/Seoul",
            "threads": {"thread-1": {"last_message_id": "301", "name": "source script", "archived": False}},
        }
    }
    thread = DiscordThread(id="thread-1", name="source script", parent_id="parent", archived=False)
    late_reply = Message(
        id="302",
        content="late transcript line",
        author="user",
        timestamp="2026-08-26T12:01:00+09:00",
        attachments=[],
        jump_url="https://discord.com/channels/guild/thread-1/302",
        channel_id="thread-1",
    )

    class RecordingDestination:
        def __init__(self):
            self.thread_calls = []

        def download(self, _messages):
            raise AssertionError("no new parent messages expected")

        def download_thread(self, thread, messages, starter=None):
            self.thread_calls.append((thread, messages, starter))

    destination = RecordingDestination()
    fetch_after = []
    saved = []
    marked = []

    def fetch_thread_messages(thread_id, guild_id, token, after_id):
        fetch_after.append(after_id)
        return [late_reply]

    result = main.run_download(
        config={
            "destination": "obsidian",
            "default_interval_hours": 1,
            "default_timezone": "Asia/Seoul",
            "include_threads": True,
        },
        state=state,
        channel_id="parent",
        guild_id="guild",
        token="token",
        vault_root="unused",
        fetch_fn=lambda **_kwargs: [],
        fetch_threads_fn=lambda **_kwargs: [thread],
        fetch_thread_messages_fn=fetch_thread_messages,
        fetch_message_fn=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("known thread must not refetch starter")),
        adapter=destination,
        state_saver=lambda snapshot: saved.append(snapshot["parent"]["threads"]["thread-1"]["last_message_id"]),
        mark_fn=lambda channel_id, message_id, token, emoji: marked.append((channel_id, message_id)),
        now=datetime(2026, 8, 26, 12, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    )

    assert fetch_after == ["301"]
    assert destination.thread_calls == [(thread, [late_reply], None)]
    assert result["parent"]["threads"]["thread-1"]["last_message_id"] == "302"
    assert saved == ["302"]
    assert marked == [("thread-1", "302")]


def test_new_archived_thread_fetches_starter_and_seeds_cursor_without_replies():
    thread = DiscordThread(id="thread-old", name="archived script", parent_id="parent", archived=True)
    starter = Message(
        id="thread-old",
        content="https://example.com/source",
        author="user",
        timestamp="2026-08-20T10:00:00+09:00",
        attachments=[],
        jump_url="https://discord.com/channels/guild/parent/thread-old",
        channel_id="parent",
    )

    class RecordingDestination:
        def __init__(self):
            self.thread_calls = []

        def download(self, _messages):
            pass

        def download_thread(self, thread, messages, starter=None):
            self.thread_calls.append((thread, messages, starter))

    destination = RecordingDestination()
    saved = []

    result = main.run_download(
        config={
            "destination": "obsidian",
            "default_interval_hours": 1,
            "default_timezone": "Asia/Seoul",
            "include_threads": True,
        },
        state={},
        channel_id="parent",
        guild_id="guild",
        token="token",
        vault_root="unused",
        fetch_fn=lambda **_kwargs: [],
        fetch_threads_fn=lambda **_kwargs: [thread],
        fetch_thread_messages_fn=lambda **_kwargs: [],
        fetch_message_fn=lambda **_kwargs: starter,
        adapter=destination,
        state_saver=lambda snapshot: saved.append(snapshot["parent"]["threads"]["thread-old"]["last_message_id"]),
        mark_fn=lambda *_args: True,
        now=datetime(2026, 8, 26, 12, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    )

    assert destination.thread_calls == [(thread, [], starter)]
    assert result["parent"]["threads"]["thread-old"] == {
        "last_message_id": "thread-old",
        "name": "archived script",
        "archived": True,
    }
    assert saved == ["thread-old"]
