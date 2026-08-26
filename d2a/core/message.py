"""Common, destination-agnostic data type representing a Discord message."""

from dataclasses import dataclass


@dataclass
class Attachment:
    url: str
    filename: str


@dataclass
class DiscordThread:
    id: str
    name: str
    parent_id: str
    archived: bool
    jump_url: str | None = None


@dataclass
class Message:
    id: str
    content: str
    author: str
    timestamp: str  # ISO8601
    attachments: list[Attachment]
    jump_url: str
    channel_id: str | None = None


if __name__ == "__main__":
    msg = Message(
        id="123",
        content="hello",
        author="tester",
        timestamp="2026-07-18T12:00:00",
        attachments=[Attachment(url="https://example.com/a.png", filename="a.png")],
        jump_url="https://discord.com/channels/1/2/123",
    )
    assert msg.id == "123"
    assert msg.attachments[0].filename == "a.png"
    print("message.py self-check OK")
