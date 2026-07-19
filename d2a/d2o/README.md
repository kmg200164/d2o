# D2A — Discord to Anywhere (Discord to Obsidian)

A tool that polls a Discord channel for new messages and saves them as Obsidian notes under `01_Perception/Sources/DB_Sources/`.

## 1. Create a Discord bot (no programming needed, just clicking)

1. Go to https://discord.com/developers/applications, log in
2. "New Application" → any name (e.g. d2a-download) → create
3. Left menu "Bot" → "Reset Token" → copy the token somewhere safe. **Never share this token with anyone, never commit it to GitHub — it only goes into Secrets**
4. On the same Bot page, enable "MESSAGE CONTENT INTENT" (without it, the bot can't read message content)
5. Left menu "OAuth2" → "URL Generator" → check scope `bot`, permissions: **View Channel**, **Read Message History** only → use the generated link to invite it to your server
6. Right-click the channel → "Copy Channel ID" (if not visible, enable Discord Settings → Advanced → Developer Mode)
7. Right-click the server icon → "Copy Server ID" (this is the guild ID)

**Note**: this bot doesn't stay connected via a gateway -- it briefly connects on a schedule and disconnects, so it always shows offline (gray) in the member list. That's normal.

## 2. Register GitHub Secrets

repo (the GitHub repository this project lives in) → Settings → Secrets and variables → Actions → New repository secret, add three:

- `DISCORD_BOT_TOKEN` — the token copied in step 3 above
- `DISCORD_CHANNEL_ID` — the channel ID copied in step 6 above
- `DISCORD_GUILD_ID` — the server ID copied in step 7 above

## 3. Test run locally

```bash
pip install -r d2a/requirements.txt
export DISCORD_BOT_TOKEN=your_token_here
export DISCORD_CHANNEL_ID=your_channel_id_here
export DISCORD_GUILD_ID=your_guild_id_here
python -m d2a.d2o.main
```

## 4. Change settings (`d2a/d2o/config.yaml`)

This repo ships `d2a/d2o/config.example.yaml` as a template (no real `config.yaml`/`state.json` — those are gitignored, since they'd otherwise leak your personal vault path). Copy it before first run:

```bash
cp d2a/d2o/config.example.yaml d2a/d2o/config.yaml
echo '{}' > d2a/d2o/state.json
```

- `target_folder`: where notes get saved
- `frontmatter`: frontmatter fields automatically added to every new note (if you use a different vault, just adjust this to match your own conventions)
- `callout`: the callout text placed at the top of every note

## 5. How it works

- GitHub Actions wakes up hourly (`.github/workflows/d2o-download.yml`) and checks whether it's actually time to download yet, based on the interval configured via `!interval`/`config.yaml`; manual runs are also possible (Actions tab → workflow_dispatch)
- The last processed message ID is stored in `d2a/d2o/state.json`, so each run picks up from there
- Bot/system messages and empty messages are automatically excluded. Thread messages live in a separate channel ID, so they never come in to begin with

## 6. Adding permissions (re-invite)

As of v1.1 the bot needs more permissions -- **Manage Channels**, **Manage Roles** (for auto-creating the dedicated channel), **Add Reactions** (for the ✅ marker). No need to create a new bot, just add the permissions.

1. Discord Developer Portal → your application → OAuth2 → URL Generator
2. Check scope `bot`, and check both the existing permissions (**View Channel**, **Read Message History**) and the new ones (**Manage Channels**, **Manage Roles**, **Add Reactions**)
3. Use the generated link to re-invite (re-authorize) the bot to the same server -- only the new permissions get added, existing settings are untouched

## 7. Creating the dedicated channel (`setup_channel.py`)

Automatically creates a dedicated D2O channel on your Discord server, and locks it so nobody but you can post there.

```bash
export DISCORD_BOT_TOKEN=your_token_here
export DISCORD_GUILD_ID=your_guild_id_here
python -m d2a.setup_channel
```

Running it prints a channel ID -- register that value in the `DISCORD_CHANNEL_ID` GitHub Secret (overwriting the old value). Pass a different name as an argument if you want, e.g. `python -m d2a.setup_channel my-channel-name`.

If a channel with that name already exists, it won't create a duplicate -- it just returns that channel's ID. Safe to re-run any time. **Permissions and the channel description are also re-applied on every run** -- if the lockdown rules changed (@everyone denied from sending messages/creating threads/posting in threads, bot explicitly allowed to view/read history/react) or the bot can't see the channel anymore, just re-run it.

The channel description (topic) is automatically set to `Discord To Obsidian Downloader`, so it's obvious what the channel is for just from the channel list.

## 8. Changing the download interval/timezone

Just post these as plain messages in the dedicated channel (the bot never replies -- check `d2a/d2o/state.json` to confirm they took effect):

- `!interval 12` — download every 12 hours. Only values that evenly divide 24 are valid: `1, 2, 3, 4, 6, 8, 12, 24`. Other values (e.g. 5, 7, 20) are ignored since they'd make the interval uneven
- `!timezone Asia/Seoul` — calculates the interval anchored to local midnight in this timezone (standard IANA timezone name, e.g. `America/New_York`, `Europe/London`)

These command messages themselves never get turned into notes.

## 9. Security notes

- This bot copies whatever's posted in the configured channel straight into your vault (a git repository) -- treat anything posted there as **permanently recorded** the moment it's downloaded
- The dedicated channel created by `setup_channel.py` blocks everyone but you from posting, but that doesn't mean anything goes -- don't post passwords, ID numbers, account numbers, or other sensitive info there either
- Never share the bot token; it only lives in GitHub Secrets (already covered in step 1)
