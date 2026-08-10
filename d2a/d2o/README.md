# D2O engine

`main.py` reads an explicit caller-repository runtime contract from environment variables.

- `D2O_DESTINATION_ROOT`
- `D2O_TARGET_FOLDER`
- `D2O_STATE_PATH`
- `D2O_FRONTMATTER_JSON`
- `D2O_CALLOUT`
- `D2O_DEFAULT_INTERVAL_HOURS`
- `D2O_DEFAULT_TIMEZONE`
- `DISCORD_BOT_TOKEN`
- `DISCORD_CHANNEL_ID`
- `DISCORD_GUILD_ID`

Production callers should use the root reusable workflow instead of invoking the module directly.

Project-specific config and state do not belong in this repository.
