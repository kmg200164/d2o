"""D2A orchestrator: load config/state -> fetch -> adapter.download() -> update state."""

import json
import os

import yaml

from d2a.d2o.obsidian_destination import ObsidianDestination
from d2a.core.commands import extract_commands
from d2a.core.discord_fetcher import COMMAND_EMOJI, CONTENT_EMOJI, fetch_new_messages, mark_processed
from d2a.core.message import Message
from d2a.core.scheduler import should_download_now

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")
STATE_PATH = os.path.join(os.path.dirname(__file__), "state.json")


def load_config(path: str = CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_state(path: str = STATE_PATH) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def normalize_channel_state(raw, config: dict) -> dict:
    """Normalizes a channel's state.json value into the new dict format.
    Also supports v1's plain-string format ({"<channel_id>": "<id>"}) for migration.
    Fills in config.yaml defaults for any missing interval_hours/timezone."""
    if isinstance(raw, str):
        raw = {"last_message_id": raw}
    elif raw is None:
        raw = {}

    return {
        "last_message_id": raw.get("last_message_id"),
        "interval_hours": raw.get("interval_hours") or config["default_interval_hours"],
        "timezone": raw.get("timezone") or config["default_timezone"],
    }


def save_state(state: dict, path: str = STATE_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def run_download(config: dict, state: dict, channel_id: str, guild_id: str, token: str,
             vault_root: str, fetch_fn=fetch_new_messages, adapter=None,
             state_saver=save_state, mark_fn=mark_processed, now=None) -> dict:
    """Checks the channel's interval/timezone and exits immediately (no API call)
    if it's not time yet. If it is, fetches -> splits out commands (!interval/
    !timezone) -> only content messages go to adapter.download() -> every message
    (commands included) updates state immediately and gets a reaction (✅ for
    content, ⚙ for commands -- can't give instant feedback, but at least
    distinguishable after the fact)."""
    channel_state = normalize_channel_state(state.get(channel_id), config)

    if not should_download_now(channel_state["interval_hours"], channel_state["timezone"], now=now):
        print(
            f"[{channel_id}] not time to download yet "
            f"(interval {channel_state['interval_hours']}h, timezone {channel_state['timezone']}) -- skipping"
        )
        return state

    if adapter is None:
        destination = config.get("destination")
        if destination == "obsidian":
            adapter = ObsidianDestination(config, vault_root)
        else:
            raise ValueError(f"unsupported destination: {destination}")

    messages = fetch_fn(
        channel_id=channel_id, guild_id=guild_id, token=token,
        after_id=channel_state["last_message_id"],
    )

    config_updates, content_messages = extract_commands(messages)
    channel_state.update(config_updates)
    content_ids = {m.id for m in content_messages}

    for message in messages:
        if message.id in content_ids:
            adapter.download([message])
            emoji = CONTENT_EMOJI
        else:
            emoji = COMMAND_EMOJI
        channel_state["last_message_id"] = message.id
        state[channel_id] = channel_state
        state_saver(state)
        mark_fn(channel_id, message.id, token, emoji)

    return state


def _main() -> None:
    config = load_config()
    state = load_state()

    token = os.environ["DISCORD_BOT_TOKEN"]
    channel_id = os.environ["DISCORD_CHANNEL_ID"]
    guild_id = os.environ["DISCORD_GUILD_ID"]
    vault_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    run_download(config, state, channel_id, guild_id, token, vault_root)
    print("download complete")


if __name__ == "__main__":
    if os.environ.get("DISCORD_BOT_TOKEN"):
        _main()
    else:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        fake_config = {
            "destination": "obsidian",
            "default_interval_hours": 6,
            "default_timezone": "Asia/Seoul",
        }

        class FakeAdapter:
            def __init__(self):
                self.calls = []

            def download(self, messages):
                self.calls.append(messages)

        # 1) if should_download_now is False, fetch itself must never be called
        def fetch_should_not_be_called(**kwargs):
            raise AssertionError("fetch was called even though should_download_now was False")

        off_hour = datetime(2026, 7, 18, 1, 0, tzinfo=ZoneInfo("Asia/Seoul"))  # default interval 6h, hour 1 isn't a multiple
        result_skipped = run_download(
            config=fake_config, state={}, channel_id="c1", guild_id="g1", token="t",
            vault_root="/tmp/unused", fetch_fn=fetch_should_not_be_called, adapter=FakeAdapter(),
            now=off_hour,
        )
        assert result_skipped == {}, result_skipped

        # 2) if should_download_now is True: split out commands, content-only to adapter,
        #    cursor advances through everything, reactions get marked
        on_hour = datetime(2026, 7, 18, 0, 0, tzinfo=ZoneInfo("Asia/Seoul"))

        fake_messages = [
            Message(id="100", content="!interval 12", author="u", timestamp="2026-07-18T00:00:00", attachments=[], jump_url="x"),
            Message(id="101", content="real content", author="u", timestamp="2026-07-18T00:01:00", attachments=[], jump_url="y"),
        ]

        def fake_fetch(channel_id, guild_id, token, after_id):
            assert after_id is None, after_id
            return fake_messages

        saved_states = []

        def fake_saver(state):
            saved_states.append({k: dict(v) for k, v in state.items()})

        marked = []

        def fake_mark(channel_id, message_id, token, emoji):
            marked.append((message_id, emoji))
            return True

        fake_adapter = FakeAdapter()
        result_state = run_download(
            config=fake_config, state={}, channel_id="c1", guild_id="g1", token="t",
            vault_root="/tmp/unused", fetch_fn=fake_fetch, adapter=fake_adapter,
            state_saver=fake_saver, mark_fn=fake_mark, now=on_hour,
        )

        assert result_state["c1"]["last_message_id"] == "101", result_state
        assert result_state["c1"]["interval_hours"] == 12, result_state
        assert len(fake_adapter.calls) == 1, fake_adapter.calls
        assert fake_adapter.calls[0][0].id == "101", fake_adapter.calls
        assert marked == [("100", COMMAND_EMOJI), ("101", CONTENT_EMOJI)], marked  # command vs content emoji
        assert len(saved_states) == 2, saved_states

        fake_config_for_normalize = {"default_interval_hours": 6, "default_timezone": "Asia/Seoul"}

        normalized_old = normalize_channel_state("12345", fake_config_for_normalize)
        assert normalized_old == {"last_message_id": "12345", "interval_hours": 6, "timezone": "Asia/Seoul"}, normalized_old

        normalized_new = normalize_channel_state(
            {"last_message_id": "999", "interval_hours": 12}, fake_config_for_normalize,
        )
        assert normalized_new == {"last_message_id": "999", "interval_hours": 12, "timezone": "Asia/Seoul"}, normalized_new

        normalized_missing = normalize_channel_state(None, fake_config_for_normalize)
        assert normalized_missing == {"last_message_id": None, "interval_hours": 6, "timezone": "Asia/Seoul"}, normalized_missing

        # _main()'s vault_root must resolve to the actual repo root (main.py sits 3
        # levels below it in this repo: repo_root/d2a/d2o/main.py), or notes silently
        # get written into a phantom folder that never gets git-committed.
        real_vault_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        assert os.path.isfile(os.path.join(real_vault_root, "LICENSE")), (
            f"vault_root miscalculated: {real_vault_root} has no LICENSE"
        )

        print("main.py self-check OK")
