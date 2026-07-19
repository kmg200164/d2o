"""Creates a dedicated D2O channel and locks it so only the owner can post.
Separate from the recurring download (main.py) -- run this locally, once."""

import os
import sys

import requests

DISCORD_API = "https://discord.com/api/v10"
ADD_REACTIONS = 0x40
VIEW_CHANNEL = 0x400
SEND_MESSAGES = 0x800
READ_MESSAGE_HISTORY = 0x10000
CREATE_PUBLIC_THREADS = 0x800000000
CREATE_PRIVATE_THREADS = 0x1000000000
SEND_MESSAGES_IN_THREADS = 0x4000000000
ROLE_TYPE = 0
MEMBER_TYPE = 1
CHANNEL_TOPIC = "Discord To Obsidian Downloader"


def get_owner_id(token: str) -> str:
    """Gets the bot application's owner (human) user ID, so the user never has
    to type it in manually."""
    resp = requests.get(
        f"{DISCORD_API}/oauth2/applications/@me",
        headers={"Authorization": f"Bot {token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["owner"]["id"]


def get_bot_id(token: str) -> str:
    """Gets the bot's own user ID. Explicitly granting the bot its own channel
    permission means it can always access this channel even if the server-wide
    permission grant gets tangled up (e.g. a re-invite that dropped a base
    permission)."""
    resp = requests.get(
        f"{DISCORD_API}/users/@me",
        headers={"Authorization": f"Bot {token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def find_existing_channel(token: str, guild_id: str, name: str) -> str | None:
    """Returns the ID of a channel with this name if one already exists, else
    None (so re-running never creates a duplicate)."""
    resp = requests.get(
        f"{DISCORD_API}/guilds/{guild_id}/channels",
        headers={"Authorization": f"Bot {token}"},
        timeout=10,
    )
    resp.raise_for_status()
    for channel in resp.json():
        if channel["name"] == name:
            return channel["id"]
    return None


def build_permission_overwrites(guild_id: str, owner_id: str, bot_id: str) -> list[dict]:
    """Builds the permission_overwrites payload: deny @everyone from sending
    messages AND creating/posting in threads, allow the owner to send messages
    (+ threads), and explicitly allow the bot to view the channel, read history,
    and add reactions. Leaving thread permissions open would let @everyone create
    a thread and post inside it (a separate permission from sending messages in
    the channel itself), defeating the lock."""
    everyone_deny = SEND_MESSAGES | CREATE_PUBLIC_THREADS | CREATE_PRIVATE_THREADS | SEND_MESSAGES_IN_THREADS
    owner_allow = SEND_MESSAGES | VIEW_CHANNEL | CREATE_PUBLIC_THREADS | CREATE_PRIVATE_THREADS | SEND_MESSAGES_IN_THREADS
    bot_allow = VIEW_CHANNEL | READ_MESSAGE_HISTORY | ADD_REACTIONS

    return [
        {"id": guild_id, "type": ROLE_TYPE, "deny": str(everyone_deny), "allow": "0"},
        {"id": owner_id, "type": MEMBER_TYPE, "allow": str(owner_allow), "deny": "0"},
        {"id": bot_id, "type": MEMBER_TYPE, "allow": str(bot_allow), "deny": "0"},
    ]


def create_private_channel(token: str, guild_id: str, name: str, overwrites: list[dict]) -> str:
    """Creates the dedicated channel and returns its ID. Sets CHANNEL_TOPIC as
    the channel description, so it's obvious what this channel is for from the
    channel list alone."""
    payload = {
        "name": name,
        "type": 0,  # text channel
        "topic": CHANNEL_TOPIC,
        "permission_overwrites": overwrites,
    }
    resp = requests.post(
        f"{DISCORD_API}/guilds/{guild_id}/channels",
        headers={"Authorization": f"Bot {token}"},
        json=payload,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def apply_permission_overwrites(token: str, channel_id: str, overwrites: list[dict]) -> None:
    """Re-applies permissions to an already-existing channel, so re-running this
    script always brings a channel up to the latest rules (thread lockdown, bot
    access, etc.) rather than only setting them once at creation time."""
    headers = {"Authorization": f"Bot {token}"}
    for overwrite in overwrites:
        resp = requests.put(
            f"{DISCORD_API}/channels/{channel_id}/permissions/{overwrite['id']}",
            headers=headers,
            json={"type": overwrite["type"], "allow": overwrite["allow"], "deny": overwrite["deny"]},
            timeout=10,
        )
        resp.raise_for_status()


def set_channel_topic(token: str, channel_id: str, topic: str = CHANNEL_TOPIC) -> None:
    """Re-applies the channel topic on an existing channel -- always in effect
    even on re-runs after creation."""
    resp = requests.patch(
        f"{DISCORD_API}/channels/{channel_id}",
        headers={"Authorization": f"Bot {token}"},
        json={"topic": topic},
        timeout=10,
    )
    resp.raise_for_status()


def setup_channel(token: str, guild_id: str, name: str = "d2o") -> str:
    """Prepares the dedicated channel and returns its ID. Won't create a
    duplicate if one already exists, but always re-applies permissions/topic
    (safe to re-run, including just to refresh settings)."""
    owner_id = get_owner_id(token)
    bot_id = get_bot_id(token)
    overwrites = build_permission_overwrites(guild_id, owner_id, bot_id)

    existing_id = find_existing_channel(token, guild_id, name)
    if existing_id:
        apply_permission_overwrites(token, existing_id, overwrites)
        set_channel_topic(token, existing_id)
        return existing_id

    return create_private_channel(token, guild_id, name, overwrites)


if __name__ == "__main__":
    overwrites = build_permission_overwrites(guild_id="1111", owner_id="2222", bot_id="3333")
    assert overwrites == [
        {"id": "1111", "type": 0, "deny": "377957124096", "allow": "0"},
        {"id": "2222", "type": 1, "allow": "377957125120", "deny": "0"},
        {"id": "3333", "type": 1, "allow": "66624", "deny": "0"},
    ], overwrites

    assert CHANNEL_TOPIC == "Discord To Obsidian Downloader", CHANNEL_TOPIC

    print("setup_channel.py self-check OK")

    if os.environ.get("DISCORD_BOT_TOKEN"):
        real_token = os.environ["DISCORD_BOT_TOKEN"]
        real_guild_id = os.environ["DISCORD_GUILD_ID"]
        channel_name = sys.argv[1] if len(sys.argv) > 1 else "d2o"

        created_id = setup_channel(real_token, real_guild_id, channel_name)
        print(f"channel ready: #{channel_name} (ID: {created_id})")
        print("add this ID to the DISCORD_CHANNEL_ID secret in your GitHub repo.")
