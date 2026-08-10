from pathlib import Path

import pytest

from d2a.core.message import Attachment, Message
from d2a.d2o import obsidian_destination


def make_config(target_folder: str) -> dict:
    return {
        "obsidian": {
            "target_folder": target_folder,
            "frontmatter": {"tags": []},
            "callout": "> [!warning] 원문 그대로",
        }
    }


def make_message(attachment: Attachment) -> Message:
    return Message(
        id="1535989293116301444",
        content="2026-08-10 회의록",
        author="user",
        timestamp="2026-08-10T12:00:00+09:00",
        attachments=[attachment],
        jump_url="https://discord.com/channels/guild/channel/message",
    )


def test_failed_text_attachment_does_not_create_note(workspace_tmp):
    target = "회의록"
    message = make_message(
        Attachment(url="https://cdn.discordapp.com/gone.txt", filename="회의록.txt")
    )

    with pytest.raises(obsidian_destination.AttachmentDownloadError, match="회의록.txt"):
        obsidian_destination.write_note(
            message,
            make_config(target),
            str(workspace_tmp),
            existing_names=set(),
            text_fetcher=lambda _url: None,
        )

    assert not (workspace_tmp / target).exists()


def test_empty_text_attachment_does_not_create_note(workspace_tmp):
    target = "회의록"
    message = make_message(
        Attachment(url="https://cdn.discordapp.com/empty.txt", filename="회의록.txt")
    )

    with pytest.raises(obsidian_destination.AttachmentDownloadError, match="empty"):
        obsidian_destination.write_note(
            message,
            make_config(target),
            str(workspace_tmp),
            existing_names=set(),
            text_fetcher=lambda _url: "   \n",
        )

    assert not (workspace_tmp / target).exists()


def test_failed_binary_attachment_leaves_no_partial_note(workspace_tmp):
    target = "회의록"
    message = make_message(
        Attachment(url="https://cdn.discordapp.com/gone.png", filename="graph.png")
    )

    def failed_downloader(_url: str, destination: str) -> bool:
        Path(destination).write_bytes(b"partial")
        return False

    with pytest.raises(obsidian_destination.AttachmentDownloadError, match="graph.png"):
        obsidian_destination.write_note(
            message,
            make_config(target),
            str(workspace_tmp),
            existing_names=set(),
            downloader=failed_downloader,
        )

    assert list((workspace_tmp / target).glob("**/*")) == []
