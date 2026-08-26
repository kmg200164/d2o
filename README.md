# D2O — Discord collector for repository-owned notes

D2O polls one Discord channel and writes new messages into the repository that called it. Callers can also opt into active and archived public thread collection; each thread keeps its own cursor so late replies are appended without duplication.

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
    uses: kmg200164/d2o/.github/workflows/collect.yml@v1.1
    with:
      profile: example
      target_folder: notes
      frontmatter_json: '{"tags":[]}'
      callout: ''
      include_threads: 'true'
    secrets:
      discord_bot_token: ${{ secrets.DISCORD_BOT_TOKEN }}
      discord_channel_id: ${{ secrets.DISCORD_CHANNEL_ID }}
      discord_guild_id: ${{ secrets.DISCORD_GUILD_ID }}
```

Seed `.d2o/example-state.json` before activation when an existing channel already has messages.

An empty state downloads the channel history visible to the bot. With `include_threads: 'true'`, the first run also enumerates active and archived public threads. New parent notes preserve both the external `source` and Discord provenance; legacy notes are matched by the starter message's external URL before thread transcripts are appended.

## Failure contract

- A failed or empty text attachment does not create a note.
- A failed binary attachment leaves no completed note.
- A failed destination does not advance the cursor.
- A failed destination does not add the success reaction.
- A failed thread append does not advance that thread's cursor.
- Re-running the same thread reply does not duplicate transcript text.
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

Thread collection also needs permission to view the thread and read its message history. Archived private threads are not enumerated; active private threads are included only when Discord exposes them to the bot through the guild active-thread endpoint.

`MESSAGE CONTENT INTENT` must be enabled in the Discord application.

Secrets belong only in the caller repository.
