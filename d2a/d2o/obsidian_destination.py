"""Adapter that turns messages into Obsidian notes."""

import html
import os
import re

import requests
import yaml

from d2a.destinations.base import Destination

FORBIDDEN_CHARS = '/\\:*?"<>|'
URL_PATTERN = re.compile(r"https?://\S+")
YOUTUBE_HOSTS = ("youtube.com", "youtu.be")
MAX_FILENAME_LENGTH = 100  # some sites' titles arrive hundreds of chars long with newlines
# and HTML entities, which triggered an OSError (filename too long)


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
    the message's Created Date/URL."""
    fm = dict(obsidian_cfg["frontmatter"])
    fm["Created Date"] = message.timestamp
    fm["URL"] = find_first_url(message.content) or message.jump_url
    body = yaml.dump(fm, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{body}\n---"


def download_attachment(url: str, dest_path: str) -> bool:
    """Downloads an attachment. Returns True/False only, on failure, so a failed
    download never blocks note creation itself."""
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        with open(dest_path, "wb") as f:
            f.write(resp.content)
        return True
    except Exception:
        return False


def _write_note_with_name(message, obsidian_cfg: dict, target_folder: str, name: str,
                           downloader, file_opener) -> str:
    """Actually writes the note file to disk. Returns the name that was used."""
    frontmatter = build_frontmatter(message, obsidian_cfg)
    callout = obsidian_cfg["callout"].rstrip()
    body_parts = [frontmatter, "", callout, "", message.content]

    if message.attachments:
        note_dir = os.path.join(target_folder, name)
        media_dir = os.path.join(note_dir, "Media")
        os.makedirs(media_dir, exist_ok=True)
        for attachment in message.attachments:
            safe_filename = sanitize_filename(attachment.filename)
            dest = os.path.join(media_dir, safe_filename)
            if downloader(attachment.url, dest):
                body_parts.append(f"![[{safe_filename}]]")
            else:
                body_parts.append(f"(download failed, original link: {attachment.url})")
        note_path = os.path.join(note_dir, f"{name}.md")
    else:
        os.makedirs(target_folder, exist_ok=True)
        note_path = os.path.join(target_folder, f"{name}.md")

    with file_opener(note_path, "w", encoding="utf-8") as f:
        f.write("\n".join(body_parts) + "\n")

    return name


def write_note(message, config: dict, vault_root: str, existing_names: set[str],
                downloader=download_attachment, file_opener=open) -> str:
    """Saves one message as an Obsidian note and returns the filename used
    (without extension). Uses the note-folder+Media pattern when there are
    attachments, a flat .md otherwise (vault_structure.md convention).
    If an unexpected OS error slips past sanitize_filename (e.g. a filename
    length limit), retries once with a guaranteed-safe, message-ID-based name --
    if that also fails, it's a real system problem (disk, etc.) and should
    propagate to stop the batch."""
    obsidian_cfg = config["obsidian"]
    target_folder = os.path.join(vault_root, obsidian_cfg["target_folder"])
    name = generate_filename(message, existing_names)

    try:
        return _write_note_with_name(message, obsidian_cfg, target_folder, name, downloader, file_opener)
    except OSError as e:
        fallback_name = f"discord-{message.id}"
        print(f"[warning] failed to write note '{name}' ({e}) -- retrying as '{fallback_name}'")
        return _write_note_with_name(
            message, obsidian_cfg, target_folder, fallback_name, downloader, file_opener
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
            "target_folder": "01_Perception/DB_Sources",
            "frontmatter": {"base": "[[DB_Sources.base]]", "tags": [], "Applied": "Pending"},
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
        flat_path = f"{vault_root}/01_Perception/DB_Sources/{flat_name}.md"
        with open(flat_path, encoding="utf-8") as f:
            flat_content = f.read()
        assert "a note with no attachment" in flat_content
        assert "base: '[[DB_Sources.base]]'" in flat_content or "base: [[DB_Sources.base]]" in flat_content

        media_msg = Message(
            id="201", content="a note with an image attached", author="u",
            timestamp="2026-07-18T09:05:00",
            attachments=[Attachment(url="https://cdn.discordapp.com/1.png", filename="1.png")],
            jump_url="w",
        )
        media_name = write_note(
            media_msg, fake_config, vault_root, existing_names={flat_name}, downloader=fake_downloader,
        )
        note_dir = f"{vault_root}/01_Perception/DB_Sources/{media_name}"
        with open(f"{note_dir}/{media_name}.md", encoding="utf-8") as f:
            media_content = f.read()
        assert "![[1.png]]" in media_content
        with open(f"{note_dir}/Media/1.png", "rb") as f:
            assert f.read() == b"fake-image-bytes"

    print("obsidian_destination.py write_note self-check OK")

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
        fallback_path = f"{vault_root_fallback}/01_Perception/DB_Sources/{fallback_name}.md"
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
        entries = os.listdir(f"{vault_root2}/01_Perception/DB_Sources")
        assert len(entries) == 2, f"name collision didn't produce 2 files: {entries}"

    print("obsidian_destination.py ObsidianDestination self-check OK")
