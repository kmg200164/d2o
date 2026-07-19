"""Extracts setting commands (!interval, !timezone) out of a Discord message stream."""

import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

INTERVAL_PATTERN = re.compile(r"^!interval\s+(\d+)$")
TIMEZONE_PATTERN = re.compile(r"^!timezone\s+(\S+)$")

# scheduler.should_download_now decides download timing via now.hour % interval_hours == 0.
# If interval_hours isn't a divisor of 24 (e.g. 5, 7, 20), the download cadence becomes
# uneven -- only allow exact divisors of 24 so every cycle stays evenly spaced.
VALID_INTERVALS = {1, 2, 3, 4, 6, 8, 12, 24}


def extract_commands(messages):
    """Pulls !interval/!timezone commands out of a message list into config_updates,
    and returns everything else as remaining_messages. An interval that isn't a
    divisor of 24, or an invalid timezone name, is silently ignored (not applied,
    and not turned into a note either)."""
    config_updates = {}
    remaining_messages = []

    for message in messages:
        content = message.content.strip()

        interval_match = INTERVAL_PATTERN.match(content)
        if interval_match:
            hours = int(interval_match.group(1))
            if hours in VALID_INTERVALS:
                config_updates["interval_hours"] = hours
            continue

        timezone_match = TIMEZONE_PATTERN.match(content)
        if timezone_match:
            tz_name = timezone_match.group(1)
            try:
                ZoneInfo(tz_name)
                config_updates["timezone"] = tz_name
            except (ZoneInfoNotFoundError, ValueError):
                pass
            continue

        remaining_messages.append(message)

    return config_updates, remaining_messages


if __name__ == "__main__":
    from d2a.core.message import Message

    def msg(content, id_):
        return Message(
            id=id_, content=content, author="u",
            timestamp="2026-07-18T00:00:00", attachments=[], jump_url="x",
        )

    messages = [
        msg("!interval 12", "1"),
        msg("!timezone Asia/Seoul", "2"),
        msg("!interval 99", "3"),  # out of range (>24) -- ignored
        msg("!timezone Not/AZone", "4"),
        msg("!timezone ..", "6"),
        msg("!timezone /etc/passwd", "7"),
        msg("just a regular note", "5"),
        msg("!interval 20", "8"),  # not a divisor of 24 (20 doesn't divide 24) -- ignored
    ]

    config_updates, remaining = extract_commands(messages)

    assert config_updates == {"interval_hours": 12, "timezone": "Asia/Seoul"}, config_updates
    assert [m.id for m in remaining] == ["5"], [m.id for m in remaining]

    print("commands.py self-check OK")
