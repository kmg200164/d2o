# D2A — Discord to Anywhere

A small framework for polling a Discord channel and saving new messages to some destination. `d2a/core/` fetches Discord messages and knows nothing about where they end up; anything in `d2a/destinations/` implements the `Destination` interface (`d2a/destinations/base.py`) to define one destination.

**D2O (Discord → Obsidian)** is the first concrete deployment built on this framework — see [`d2a/d2o/README.md`](d2a/d2o/README.md) for the full setup guide. This repo is named `d2o` after that first MVP, but the code inside is the general D2A framework plus the D2O deployment on top of it.

Adding a new destination (e.g. a future D2N for Notion) means adding one file under `d2a/destinations/` and one small config branch in that deployment's own `main.py` (e.g. `d2a/d2o/main.py`) — `d2a/core/` never needs to change.
