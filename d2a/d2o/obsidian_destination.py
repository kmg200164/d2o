"""Adapter that turns messages into Obsidian notes."""

import html
import os
import re
import shutil
import tempfile
from datetime import date
from uuid import uuid4

import requests
import yaml

from d2a.destinations.base import Destination

FORBIDDEN_CHARS = '/\\:*?"<>|'
URL_PATTERN = re.compile(r"https?://\S+")
YOUTUBE_HOSTS = ("youtube.com", "youtu.be")
MAX_FILENAME_LENGTH = 100  # some sites' titles arrive hundreds of chars long with newlines
# and HTML entities, which triggered an OSError (filename too long)
TEXT_EXTENSIONS = {".txt", ".md"}  # inlined into the note body, not saved as files --
# Obsidian renders no embed for these, so a ![[foo.txt]] link leaves the note an empty
# shell with its actual content stranded in Attachments/ (found with Clova meeting transcripts)


class AttachmentDownloadError(RuntimeError):
    """Raised when a note would be incomplete because an attachment was not fetched."""


def sanitize_filename(name: str) -> str:
    """Strips OS-forbidden filename characters, unescapes HTML entities, collapses
    newlines/runs of whitespace, and truncates to a safe length."""
    name = html.unescape(name)
    name = "".join(c for c in name if c not in FORBIDDEN_CHARS)
    name = " ".join(name.split())  # collapse all whitespace (newlines, tabs, ...) to a single space
    return name[:MAX_FILENAME_LENGTH].strip()


def find_first_url(content: str) -> str | None:
    match = URL_PATTERN.search(content)
    return match.group(0) if match else None


def extract_title(url: str) -> str | None:
    """Extracts a page title from a URL. Returns None on failure (timeout, network error, etc.)."""
    try:
        if any(host in url for host in YOUTUBE_HOSTS):
            resp = requests.get(
                "https://www.youtube.com/oembed",
                params={"url": url, "format": "json"},
                timeout=5,
            )
            resp.raise_for_status()
            return resp.json().get("title")

        resp = requests.get(url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        match = re.search(r"<title[^>]*>(.*?)</title>", resp.text, re.IGNORECASE | re.DOTALL)
        return match.group(1).strip() if match else None
    except Exception:
        return None


def generate_filename(message, existing_names: set[str], title_fetcher=extract_title) -> str:
    """Builds a note filename (without extension) from a message. Prefers the page
    title if a URL is present; falls back to date + first-30-chars-of-content if
    there's no URL or the title fetch fails. Appends the last 6 digits of the
    message ID as a suffix if the name collides with an existing one."""
    url = find_first_url(message.content)
    title = title_fetcher(url) if url else None

    if title:
        base_name = sanitize_filename(title)
    else:
        date_part = message.timestamp[:10]
        snippet = sanitize_filename(message.content[:30]) or "message"
        base_name = f"{date_part} {snippet}"

    if base_name not in existing_names:
        return base_name

    return f"{base_name} {message.id[-6:]}"


def build_frontmatter(message, obsidian_cfg: dict) -> str:
    """Builds YAML frontmatter by combining config['obsidian']['frontmatter'] with
    the message's created date/source URL (vault_rules.md Raw schema)."""
    fm = dict(obsidian_cfg["frontmatter"])
    fm["created"] = date.fromisoformat(message.timestamp[:10])
    fm["source"] = find_first_url(message.content) or message.jump_url
    fm["discord_source"] = message.jump_url
    fm["discord_message_id"] = message.id
    if message.channel_id:
        fm["discord_channel_id"] = message.channel_id
    body = yaml.dump(fm, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{body}\n---"


def download_attachment(url: str, dest_path: str) -> bool:
    """Downloads an attachment and reports whether the complete file was written."""
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        with open(dest_path, "wb") as f:
            f.write(resp.content)
        return True
    except Exception:
        return False


def is_text_attachment(filename: str) -> bool:
    return os.path.splitext(filename)[1].lower() in TEXT_EXTENSIONS


def fetch_attachment_text(url: str) -> str | None:
    """Fetches a text attachment's content instead of writing it to disk, so it can be
    inlined into the note body. Returns None on failure so the caller can stop before
    creating a partial note or advancing the Discord cursor."""
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        # ponytail: decode as UTF-8 outright instead of sniffing the charset. Discord
        # attachments from the tools we actually use are UTF-8; errors="replace" keeps a
        # stray non-UTF-8 file from killing the batch. Revisit if a real cp949 source shows up.
        return resp.content.decode("utf-8", errors="replace")
    except Exception:
        return None


def _write_note_with_name(message, obsidian_cfg: dict, target_folder: str, name: str,
                           downloader, file_opener, text_fetcher=fetch_attachment_text) -> str:
    """Actually writes the note file to disk. Returns the name that was used.
    Text attachments are inlined into the body; only non-text attachments trigger the
    note-folder + Attachments pattern, so a text-only message stays a flat .md."""
    frontmatter = build_frontmatter(message, obsidian_cfg)
    callout = obsidian_cfg["callout"].rstrip()
    body_parts = [frontmatter, "", callout, "", message.content]

    text_attachments = [a for a in message.attachments if is_text_attachment(a.filename)]
    file_attachments = [a for a in message.attachments if not is_text_attachment(a.filename)]

    for attachment in text_attachments:
        text = text_fetcher(attachment.url)
        if text is None:
            raise AttachmentDownloadError(
                f"failed to download text attachment: {attachment.filename}"
            )
        stripped = text.strip()
        if not stripped:
            raise AttachmentDownloadError(
                f"text attachment is empty: {attachment.filename}"
            )
        body_parts.append(stripped)

    if file_attachments:
        os.makedirs(target_folder, exist_ok=True)
        staging_root = os.path.join(
            target_folder, f".d2o-staging-{message.id}-{uuid4().hex}"
        )
        os.makedirs(staging_root, mode=0o777)
        try:
            note_dir = os.path.join(staging_root, name)
            media_dir = os.path.join(note_dir, "Attachments")
            os.makedirs(media_dir, exist_ok=True)
            for attachment in file_attachments:
                safe_filename = sanitize_filename(attachment.filename)
                dest = os.path.join(media_dir, safe_filename)
                if not downloader(attachment.url, dest):
                    raise AttachmentDownloadError(
                        f"failed to download attachment: {attachment.filename}"
                    )
                body_parts.append(f"![[{safe_filename}]]")
            note_path = os.path.join(note_dir, f"{name}.md")
            with file_opener(note_path, "w", encoding="utf-8") as f:
                f.write("\n".join(body_parts) + "\n")
            os.replace(note_dir, os.path.join(target_folder, name))
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)
        return name
    else:
        os.makedirs(target_folder, exist_ok=True)
        note_path = os.path.join(target_folder, f"{name}.md")

    with file_opener(note_path, "w", encoding="utf-8") as f:
        f.write("\n".join(body_parts) + "\n")

    return name


def write_note(message, config: dict, vault_root: str, existing_names: set[str],
                downloader=download_attachment, file_opener=open,
                text_fetcher=fetch_attachment_text, title_fetcher=extract_title) -> str:
    """Saves one message as an Obsidian note and returns the filename used
    (without extension). Uses the note-folder+Attachments pattern when there are
    attachments, a flat .md otherwise (vault_rules.md convention).
    If an unexpected OS error slips past sanitize_filename (e.g. a filename
    length limit), retries once with a guaranteed-safe, message-ID-based name --
    if that also fails, it's a real system problem (disk, etc.) and should
    propagate to stop the batch."""
    obsidian_cfg = config["obsidian"]
    target_folder = os.path.join(vault_root, obsidian_cfg["target_folder"])
    name = generate_filename(message, existing_names, title_fetcher=title_fetcher)

    try:
        return _write_note_with_name(
            message, obsidian_cfg, target_folder, name, downloader, file_opener, text_fetcher
        )
    except OSError as e:
        fallback_name = f"discord-{message.id}"
        print(f"[warning] failed to write note '{name}' ({e}) -- retrying as '{fallback_name}'")
        return _write_note_with_name(
            message, obsidian_cfg, target_folder, fallback_name, downloader, file_opener, text_fetcher
        )


class ObsidianDestination(Destination):
    """Destination that saves Discord messages as vault notes per config['obsidian']."""

    def __init__(self, config: dict, vault_root: str):
        self.config = config
        self.vault_root = vault_root

    def download(self, messages: list) -> None:
        target_folder = os.path.join(self.vault_root, self.config["obsidian"]["target_folder"])
        existing_names = self._scan_existing_names(target_folder)
        for message in messages:
            name = write_note(message, self.config, self.vault_root, existing_names)
            existing_names.add(name)

    @staticmethod
    def _note_paths(target_folder: str):
        if not os.path.isdir(target_folder):
            return []
        paths = []
        for current, directories, filenames in os.walk(target_folder):
            directories[:] = [name for name in directories if name != "Attachments"]
            paths.extend(
                os.path.join(current, filename)
                for filename in filenames
                if filename.endswith(".md")
            )
        return paths

    @staticmethod
    def _split_note(text: str) -> tuple[dict, str]:
        match = re.match(r"^---\n(.*?)\n---\n?", text, re.DOTALL)
        if not match:
            return {}, text
        return yaml.safe_load(match.group(1)) or {}, text[match.end():]

    @staticmethod
    def _serialize_note(frontmatter: dict, body: str) -> str:
        dumped = yaml.dump(frontmatter, allow_unicode=True, sort_keys=False).strip()
        return f"---\n{dumped}\n---\n{body.lstrip()}"

    @staticmethod
    def _atomic_write(path: str, text: str) -> None:
        directory = os.path.dirname(path)
        descriptor, staging = tempfile.mkstemp(prefix=".d2o-note-", dir=directory)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.replace(staging, path)
        finally:
            if os.path.exists(staging):
                os.unlink(staging)

    def _find_thread_note(self, target_folder: str, thread, starter=None) -> str | None:
        starter_source = find_first_url(starter.content) if starter else None
        source_match = None
        for note_path in self._note_paths(target_folder):
            with open(note_path, encoding="utf-8") as handle:
                frontmatter, _ = self._split_note(handle.read())
            if str(frontmatter.get("discord_message_id", "")) == thread.id:
                return note_path
            if starter_source and frontmatter.get("source") == starter_source:
                source_match = note_path
        return source_match

    @staticmethod
    def _render_reply(reply) -> str:
        attachments = "\n".join(
            f"- [{attachment.filename}]({attachment.url})" for attachment in reply.attachments
        )
        parts = [
            f"<!-- d2o-message:{reply.id} -->",
            f"**{reply.author} · {reply.timestamp}**",
            reply.content,
        ]
        if attachments:
            parts.append(attachments)
        return "\n\n".join(part for part in parts if part).rstrip()

    def download_thread(self, thread, messages: list, starter=None) -> None:
        """Adds new thread replies to the parent Raw note without duplication.

        New notes match by Discord starter ID. Legacy notes fall back to the
        starter's external source URL, which enables one-time backlog recovery.
        """
        target_folder = os.path.join(self.vault_root, self.config["obsidian"]["target_folder"])
        note_path = self._find_thread_note(target_folder, thread, starter=starter)
        if note_path is None:
            if starter is None:
                raise RuntimeError(f"parent note not found for Discord thread {thread.id}")
            existing_names = self._scan_existing_names(target_folder)
            name = write_note(starter, self.config, self.vault_root, existing_names)
            flat = os.path.join(target_folder, f"{name}.md")
            nested = os.path.join(target_folder, name, f"{name}.md")
            note_path = flat if os.path.isfile(flat) else nested

        with open(note_path, encoding="utf-8") as handle:
            frontmatter, body = self._split_note(handle.read())

        frontmatter["discord_message_id"] = thread.id
        if starter:
            frontmatter["discord_source"] = starter.jump_url
            if starter.channel_id:
                frontmatter["discord_channel_id"] = starter.channel_id
        frontmatter["discord_thread_id"] = thread.id
        frontmatter["discord_thread"] = thread.name
        if thread.jump_url:
            frontmatter["discord_thread_source"] = thread.jump_url

        start_marker = f"<!-- d2o-thread:{thread.id}:start -->"
        end_marker = f"<!-- d2o-thread:{thread.id}:end -->"
        if start_marker not in body:
            transcript = f"{start_marker}\n## Discord 원문 스크립트\n\n{end_marker}"
            body = f"{body.rstrip()}\n\n{transcript}\n"

        for message in messages:
            marker = f"<!-- d2o-message:{message.id} -->"
            if marker in body:
                continue
            rendered = self._render_reply(message)
            body = body.replace(end_marker, f"{rendered}\n\n{end_marker}", 1)

        self._atomic_write(note_path, self._serialize_note(frontmatter, body))

    @staticmethod
    def _scan_existing_names(target_folder: str) -> set:
        # ponytail: re-scans the directory on every message -- slow if a batch has
        # hundreds of messages. main.py calls download() one message at a time anyway,
        # so a re-scan is needed regardless; if this ever becomes slow, refactor to
        # keep existing_names alive outside this function.
        if not os.path.isdir(target_folder):
            return set()
        return {os.path.splitext(entry)[0] for entry in os.listdir(target_folder)}


if __name__ == "__main__":
    import tempfile

    from d2a.core.message import Attachment, Message

    assert sanitize_filename('title/special:chars*test') == "titlespecialcharstest"

    junk_title = "title\nwith a newline and &quot;quotes&quot; then " + "a" * 200
    cleaned = sanitize_filename(junk_title)
    assert "\n" not in cleaned, cleaned
    assert '"' not in cleaned, cleaned
    assert len(cleaned) <= MAX_FILENAME_LENGTH, len(cleaned)

    msg_with_title = Message(
        id="123456789012345678", content="video https://youtu.be/abc", author="u",
        timestamp="2026-07-18T10:00:00", attachments=[], jump_url="x",
    )
    name = generate_filename(msg_with_title, existing_names=set(), title_fetcher=lambda url: "Test Video Title")
    assert name == "Test Video Title", name

    msg_no_title = Message(
        id="123456789012345678", content="a" * 40, author="u",
        timestamp="2026-07-18T10:00:00", attachments=[], jump_url="x",
    )
    name2 = generate_filename(msg_no_title, existing_names=set(), title_fetcher=lambda url: None)
    assert name2 == "2026-07-18 " + "a" * 30, name2

    name3 = generate_filename(msg_no_title, existing_names={name2}, title_fetcher=lambda url: None)
    assert name3 == f"{name2} 345678", name3

    print("obsidian_destination.py filename self-check OK")

    fake_config = {
        "obsidian": {
            "target_folder": "1-Input/Sources",
            "frontmatter": {"base": "[[Sources.base]]", "tags": [], "ingestion": "Pending"},
            "callout": "> [!info] Status\n> Downloaded, pending review",
        }
    }

    def fake_downloader(url, dest_path):
        with open(dest_path, "wb") as f:
            f.write(b"fake-image-bytes")
        return True

    with tempfile.TemporaryDirectory() as vault_root:
        flat_msg = Message(
            id="200", content="a note with no attachment", author="u",
            timestamp="2026-07-18T09:00:00", attachments=[], jump_url="z",
        )
        flat_name = write_note(flat_msg, fake_config, vault_root, existing_names=set())
        flat_path = f"{vault_root}/1-Input/Sources/{flat_name}.md"
        with open(flat_path, encoding="utf-8") as f:
            flat_content = f.read()
        assert "a note with no attachment" in flat_content
        assert "base: '[[Sources.base]]'" in flat_content or "base: [[Sources.base]]" in flat_content

        media_msg = Message(
            id="201", content="a note with an image attached", author="u",
            timestamp="2026-07-18T09:05:00",
            attachments=[Attachment(url="https://cdn.discordapp.com/1.png", filename="1.png")],
            jump_url="w",
        )
        media_name = write_note(
            media_msg, fake_config, vault_root, existing_names={flat_name}, downloader=fake_downloader,
        )
        note_dir = f"{vault_root}/1-Input/Sources/{media_name}"
        with open(f"{note_dir}/{media_name}.md", encoding="utf-8") as f:
            media_content = f.read()
        assert "![[1.png]]" in media_content
        with open(f"{note_dir}/Attachments/1.png", "rb") as f:
            assert f.read() == b"fake-image-bytes"

    print("obsidian_destination.py write_note self-check OK")

    # Text attachments get inlined, so a text-only message must stay a flat .md and must
    # NOT leave a ![[...txt]] embed or an Attachments/ folder behind.
    with tempfile.TemporaryDirectory() as vault_root_text:
        transcript = "참석자 1 00:00\n회의 전사 원문\n"

        text_msg = Message(
            id="300", content="2026-08-07 16_05 회의록", author="u",
            timestamp="2026-08-07T16:05:00",
            attachments=[Attachment(url="https://cdn.discordapp.com/t.txt", filename="회의록.txt")],
            jump_url="t",
        )
        text_name = write_note(
            text_msg, fake_config, vault_root_text, existing_names=set(),
            text_fetcher=lambda url: transcript,
        )
        text_path = f"{vault_root_text}/1-Input/Sources/{text_name}.md"
        with open(text_path, encoding="utf-8") as f:
            text_content = f.read()
        assert "회의 전사 원문" in text_content, text_content
        assert "![[" not in text_content, text_content
        assert not os.path.exists(f"{vault_root_text}/1-Input/Sources/{text_name}"), "no note-folder expected"

        # Mixed: the text is inlined AND the binary still goes through the folder pattern.
        mixed_msg = Message(
            id="301", content="mixed", author="u", timestamp="2026-08-07T17:00:00",
            attachments=[
                Attachment(url="https://cdn.discordapp.com/t2.txt", filename="notes.txt"),
                Attachment(url="https://cdn.discordapp.com/2.png", filename="2.png"),
            ],
            jump_url="m",
        )
        mixed_name = write_note(
            mixed_msg, fake_config, vault_root_text, existing_names={text_name},
            downloader=fake_downloader, text_fetcher=lambda url: transcript,
        )
        with open(f"{vault_root_text}/1-Input/Sources/{mixed_name}/{mixed_name}.md", encoding="utf-8") as f:
            mixed_content = f.read()
        assert "회의 전사 원문" in mixed_content, mixed_content
        assert "![[2.png]]" in mixed_content, mixed_content
        assert not os.path.exists(
            f"{vault_root_text}/1-Input/Sources/{mixed_name}/Attachments/notes.txt"
        ), "text attachment must not be written to disk"

        # A failed text fetch must still produce a note, carrying the original link.
        failed_msg = Message(
            id="302", content="failed fetch", author="u", timestamp="2026-08-07T18:00:00",
            attachments=[Attachment(url="https://cdn.discordapp.com/gone.txt", filename="gone.txt")],
            jump_url="f",
        )
        failed_name = write_note(
            failed_msg, fake_config, vault_root_text, existing_names={text_name, mixed_name},
            text_fetcher=lambda url: None,
        )
        with open(f"{vault_root_text}/1-Input/Sources/{failed_name}.md", encoding="utf-8") as f:
            assert "gone.txt" in f.read()

    print("obsidian_destination.py text-attachment self-check OK")

    # Force the attempt with generate_filename's chosen name to fail, and succeed
    # with the discord-{id} fallback name, via a fake file_opener -- verifies the
    # fallback path.
    with tempfile.TemporaryDirectory() as vault_root_fallback:
        open_calls = []

        def flaky_opener(path, *args, **kwargs):
            open_calls.append(path)
            if len(open_calls) == 1:
                raise OSError("File name too long")
            return open(path, *args, **kwargs)

        risky_msg = Message(
            id="900000000000000123", content="a" * 40, author="u",
            timestamp="2026-07-18T09:20:00", attachments=[], jump_url="r",
        )
        fallback_name = write_note(
            risky_msg, fake_config, vault_root_fallback, existing_names=set(), file_opener=flaky_opener,
        )
        assert fallback_name == "discord-900000000000000123", fallback_name
        assert len(open_calls) == 2, open_calls
        fallback_path = f"{vault_root_fallback}/1-Input/Sources/{fallback_name}.md"
        with open(fallback_path, encoding="utf-8") as f:
            assert "a" * 40 in f.read()

    print("obsidian_destination.py write_note fallback self-check OK")

    with tempfile.TemporaryDirectory() as vault_root2:
        adapter2 = ObsidianDestination(fake_config, vault_root2)
        dup_msg1 = Message(
            id="300000000000000001", content="a" * 40, author="u",
            timestamp="2026-07-18T09:10:00", attachments=[], jump_url="p",
        )
        dup_msg2 = Message(
            id="300000000000000002", content="a" * 40, author="u",
            timestamp="2026-07-18T09:11:00", attachments=[], jump_url="q",
        )
        adapter2.download([dup_msg1])
        adapter2.download([dup_msg2])
        entries = os.listdir(f"{vault_root2}/1-Input/Sources")
        assert len(entries) == 2, f"name collision didn't produce 2 files: {entries}"

    print("obsidian_destination.py ObsidianDestination self-check OK")
