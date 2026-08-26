from pathlib import Path

import yaml

from d2a.core.message import DiscordThread, Message
from d2a.d2o.obsidian_destination import ObsidianDestination, write_note


def config(target_folder="Raw"):
    return {
        "obsidian": {
            "target_folder": target_folder,
            "frontmatter": {"tags": [], "ingestion": "Pending"},
            "callout": "> [!info] Status\n> Downloaded, pending review",
        }
    }


def parent_message():
    return Message(
        id="thread-1",
        content="read https://example.com/source",
        author="owner",
        timestamp="2026-08-25T10:00:00+09:00",
        attachments=[],
        jump_url="https://discord.com/channels/guild/parent/thread-1",
        channel_id="parent",
    )


def reply():
    return Message(
        id="reply-1",
        content="full original transcript",
        author="owner",
        timestamp="2026-08-25T10:01:00+09:00",
        attachments=[],
        jump_url="https://discord.com/channels/guild/thread-1/reply-1",
        channel_id="thread-1",
    )


def read_frontmatter(note: Path):
    text = note.read_text(encoding="utf-8")
    return yaml.safe_load(text.split("---", 2)[1]), text


def test_parent_note_preserves_external_and_discord_provenance(workspace_tmp):
    write_note(parent_message(), config(), str(workspace_tmp), existing_names=set(), title_fetcher=lambda _url: "Source")
    note = workspace_tmp / "Raw/Source.md"
    frontmatter, _ = read_frontmatter(note)

    assert frontmatter["source"] == "https://example.com/source"
    assert frontmatter["discord_source"] == "https://discord.com/channels/guild/parent/thread-1"
    assert frontmatter["discord_message_id"] == "thread-1"
    assert frontmatter["discord_channel_id"] == "parent"


def test_thread_transcript_is_appended_idempotently_to_parent_note(workspace_tmp):
    write_note(parent_message(), config(), str(workspace_tmp), existing_names=set(), title_fetcher=lambda _url: "Source")
    destination = ObsidianDestination(config(), str(workspace_tmp))
    thread = DiscordThread(id="thread-1", name="source script", parent_id="parent", archived=False)

    destination.download_thread(thread, [reply()])
    destination.download_thread(thread, [reply()])

    note = workspace_tmp / "Raw/Source.md"
    frontmatter, text = read_frontmatter(note)
    assert frontmatter["discord_thread_id"] == "thread-1"
    assert frontmatter["discord_thread"] == "source script"
    assert "## Discord 원문 스크립트" in text
    assert "full original transcript" in text
    assert text.count("d2o-message:reply-1") == 1


def test_legacy_note_is_matched_by_starter_external_url_before_creating_duplicate(workspace_tmp):
    target = workspace_tmp / "Raw"
    target.mkdir()
    legacy = target / "legacy.md"
    legacy.write_text(
        "---\ntags: []\ningestion: Blocked\nsource: https://example.com/source\n---\n\nold capture\n",
        encoding="utf-8",
    )
    destination = ObsidianDestination(config(), str(workspace_tmp))
    thread = DiscordThread(id="thread-1", name="source script", parent_id="parent", archived=True)

    destination.download_thread(thread, [reply()], starter=parent_message())

    frontmatter, text = read_frontmatter(legacy)
    assert frontmatter["discord_message_id"] == "thread-1"
    assert frontmatter["discord_source"] == parent_message().jump_url
    assert "full original transcript" in text
    assert list(target.glob("*.md")) == [legacy]
