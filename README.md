# D2O — Discord collector for repository-owned notes

D2O polls one Discord channel and writes new messages into the repository that called it.

D2O does not store project data, Discord IDs, credentials, or project-specific policy.

## Ownership model

```text
Discord channel
  ↓
kmg200164/d2o reusable workflow and collector
  ↓
caller repository target folder and caller-owned state
```

Each caller owns:

- its Discord GitHub Secrets;
- its target folder;
- `.d2o/<profile>-state.json`;
- its note frontmatter and callout;
- its commit history.

## Caller workflow

```yaml
name: D2O Download

on:
  schedule:
    - cron: '7 * * * *'
  workflow_dispatch: {}

permissions:
  contents: write

jobs:
  collect:
    uses: kmg200164/d2o/.github/workflows/collect.yml@v1
    with:
      profile: example
      target_folder: notes
      frontmatter_json: '{"tags":[]}'
      callout: ''
    secrets:
      discord_bot_token: ${{ secrets.DISCORD_BOT_TOKEN }}
      discord_channel_id: ${{ secrets.DISCORD_CHANNEL_ID }}
      discord_guild_id: ${{ secrets.DISCORD_GUILD_ID }}
```

Seed `.d2o/example-state.json` before activation when an existing channel already has messages.

An empty state downloads the channel history visible to the bot.

## Failure contract

- A failed or empty text attachment does not create a note.
- A failed binary attachment leaves no completed note.
- A failed destination does not advance the cursor.
- A failed destination does not add the success reaction.
- The reusable workflow commits only after the collector exits successfully.

## Development

```bash
python -m pip install -r d2a/requirements.txt
python -m pytest d2a/tests -v
```

Python 3.12 is the GitHub Actions runtime.

## Discord bot permissions

Collection needs:

- View Channel
- Read Message History
- Add Reactions

`MESSAGE CONTENT INTENT` must be enabled in the Discord application.

Secrets belong only in the caller repository.
