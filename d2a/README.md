# D2A — Discord to Anywhere

A small framework for polling a Discord channel and saving new messages to some destination. `core/` fetches Discord messages and knows nothing about where they end up; anything in `destinations/` implements the `Destination` interface (`destinations/base.py`) to define one destination.

**D2O (Discord → Obsidian)** is the first concrete deployment built on this framework — see [`d2o/README.md`](d2o/README.md) for the full setup guide.

Adding a new destination (e.g. a future D2N for Notion) means adding one file under `destinations/` and one small config branch in that deployment's own `main.py` (e.g. `d2o/main.py`) — `core/` never needs to change.
