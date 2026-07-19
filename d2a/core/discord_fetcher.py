"""Polls the Discord REST API for new messages in a specific channel."""

import requests

from d2a.core.message import Attachment, Message

DISCORD_API = "https://discord.com/api/v10"
CONTENT_EMOJI = "%E2%9C%85"  # ✅ -- message downloaded as a note
COMMAND_EMOJI = "%E2%9A%99"  # ⚙ -- message recognized as a command (!interval/!timezone)


def fetch_new_messages(channel_id: str, guild_id: str, token: str, after_id: str | None) -> list[Message]:
    """Fetches messages after after_id in the given channel, oldest first.
    Excludes bot messages and empty messages (no text and no attachments)."""
    headers = {"Authorization": f"Bot {token}"}
    collected: list[Message] = []
    cursor = after_id

    while True:
        params: dict = {"limit": 100}
        if cursor:
            params["after"] = cursor
        resp = requests.get(
            f"{DISCORD_API}/channels/{channel_id}/messages",
            headers=headers,
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        page = resp.json()
        if not page:
            break

        # Discord always responds newest-first, so reverse to process oldest-first.
        for raw in reversed(page):
            if raw["author"].get("bot"):
                continue
            content = raw.get("content", "")
            raw_attachments = raw.get("attachments", [])
            if not content and not raw_attachments:
                continue
            collected.append(
                Message(
                    id=raw["id"],
                    content=content,
                    author=raw["author"]["username"],
                    timestamp=raw["timestamp"],
                    attachments=[
                        Attachment(url=a["url"], filename=a["filename"]) for a in raw_attachments
                    ],
                    jump_url=f"https://discord.com/channels/{guild_id}/{channel_id}/{raw['id']}",
                )
            )

        # Discord returns at most 100 per page -> fewer than 100 means no more messages.
        # Exactly 100 means another page may exist -> advance cursor to page[0]["id"] and keep polling.
        if len(page) < 100:
            break
        cursor = page[0]["id"]

    return collected


def mark_processed(channel_id: str, message_id: str, token: str, emoji: str = CONTENT_EMOJI) -> bool:
    """Leaves a reaction on a processed message. Defaults to ✅ (content downloaded);
    callers pass COMMAND_EMOJI (⚙) for command messages to tell them apart --
    can't give instant feedback like a slash command would (a REST-polling
    architecture limitation), but at least confirms after the fact whether a
    message was read as a setting change. Never raises on failure (missing
    permission, etc.) -- returns False only, since this is a nice-to-have that
    must not block the batch."""
    headers = {"Authorization": f"Bot {token}"}
    try:
        resp = requests.put(
            f"{DISCORD_API}/channels/{channel_id}/messages/{message_id}/reactions/{emoji}/@me",
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"[warning] failed to react to message {message_id}: {e}")
        return False


if __name__ == "__main__":
    from unittest.mock import patch, MagicMock

    fake_page = [
        {
            "id": "301",
            "content": "",
            "author": {"username": "sysbot", "bot": True},
            "timestamp": "2026-07-18T12:01:00+00:00",
            "attachments": [],
        },
        {
            "id": "300",
            "content": "hi",
            "author": {"username": "user", "bot": False},
            "timestamp": "2026-07-18T12:00:00+00:00",
            "attachments": [],
        },
    ]

    with patch("requests.get") as mock_get:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = [fake_page, []]
        mock_get.return_value = resp

        messages = fetch_new_messages(channel_id="999", guild_id="1", token="fake-token", after_id="299")

    assert len(messages) == 1, f"bot message wasn't excluded: {messages}"
    assert messages[0].id == "300"
    assert messages[0].jump_url == "https://discord.com/channels/1/999/300"

    # multi-page pagination test: 100-item first page + 10-item second page
    first_page = [
        {
            "id": str(1099 - i),
            "content": f"msg{i}",
            "author": {"username": "user", "bot": False},
            "timestamp": "2026-07-18T12:00:00+00:00",
            "attachments": [],
        }
        for i in range(100)
    ]
    second_page = [
        {
            "id": str(1199 - i),
            "content": f"msg{100+i}",
            "author": {"username": "user", "bot": False},
            "timestamp": "2026-07-18T12:00:00+00:00",
            "attachments": [],
        }
        for i in range(10)
    ]

    with patch("requests.get") as mock_get:
        resp = MagicMock()
        resp.json.side_effect = [first_page, second_page]
        mock_get.return_value = resp

        messages = fetch_new_messages(
            channel_id="999", guild_id="1", token="fake-token", after_id="999"
        )

    # confirm 2 requests happened (pagination continued)
    assert (
        mock_get.call_count == 2
    ), f"expected requests.get to be called 2 times, got {mock_get.call_count}"

    # confirm the second request's after param matches the first page's newest message id
    second_call_params = mock_get.call_args_list[1][1]["params"]
    assert (
        second_call_params["after"] == first_page[0]["id"]
    ), f"second request's after={second_call_params['after']}, expected: {first_page[0]['id']}"

    # confirm total message count (100 + 10 = 110)
    assert len(messages) == 110, f"expected 110 messages, got {len(messages)}"

    # confirm messages from the first page are included
    first_page_ids = {msg["id"] for msg in first_page}
    second_page_ids = {msg["id"] for msg in second_page}
    result_ids = {msg.id for msg in messages}
    assert (
        first_page_ids.issubset(result_ids)
    ), "first page's messages are missing from the result"
    assert (
        second_page_ids.issubset(result_ids)
    ), "second page's messages are missing from the result"

    from unittest.mock import MagicMock, patch

    with patch("requests.put") as mock_put_ok:
        resp_ok = MagicMock()
        resp_ok.raise_for_status = lambda: None
        mock_put_ok.return_value = resp_ok
        result_ok = mark_processed(channel_id="999", message_id="300", token="fake-token")
    assert result_ok is True
    mock_put_ok.assert_called_once()
    called_url = mock_put_ok.call_args[0][0]
    assert "999" in called_url and "300" in called_url, called_url
    assert CONTENT_EMOJI in called_url, called_url  # default (✅) used when emoji arg is omitted

    with patch("requests.put") as mock_put_command:
        resp_cmd = MagicMock()
        resp_cmd.raise_for_status = lambda: None
        mock_put_command.return_value = resp_cmd
        result_cmd = mark_processed(channel_id="999", message_id="301", token="fake-token", emoji=COMMAND_EMOJI)
    assert result_cmd is True
    command_url = mock_put_command.call_args[0][0]
    assert COMMAND_EMOJI in command_url, command_url  # commands use a different emoji (⚙)

    with patch("requests.put") as mock_put_fail:
        resp_fail = MagicMock()
        resp_fail.raise_for_status.side_effect = Exception("403 Forbidden")
        mock_put_fail.return_value = resp_fail
        result_fail = mark_processed(channel_id="999", message_id="300", token="fake-token")
    assert result_fail is False

    print("discord_fetcher.py self-check OK")
