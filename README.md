# Google Keep -> Apple Reminders Sync

A small Python service that every 5 minutes:
- Reads unchecked items from a Google Keep list
- Adds missing items to an Apple Reminders list
- Avoids duplicates by checking existing uncompleted reminders

Runs in Docker with persistent iCloud session cookies to minimize repeated 2FA prompts.

## Components
- Python schedule for periodic execution
- gkeepapi for Google Keep access
- pyicloud-ipd for Apple Reminders (iCloud) access

## Directory layout
- main.py — scheduler + sync logic
- requirements.txt — Python deps
- Dockerfile — container image
- .dockerignore — build context cleanup
- docker-compose.yml — convenience for local run
- data/ — volume mount to persist iCloud cookies (created by compose at runtime)

## Environment variables
Required:
- GKEEP_EMAIL — Google account email for Keep
- (One of)
  - GKEEP_PASSWORD — Google password
  - GKEEP_MASTER_TOKEN — Keep master token if you prefer token-based login (recommended)
- APPLE_ID — Apple ID (email)
- APPLE_PASSWORD — Apple account password (use an app-specific password if applicable)
- APPLE_2FA_CODE — Only needed on first run if 2FA/2SA is required; set to the code you receive, then remove it after the session is trusted

Optional:
- GKEEP_LIST_TITLE — Google Keep list title to read (default: Groceries)
- REMINDERS_LIST_NAME — Apple Reminders list to add to (used if SYNC_LIST_NAMES is not set; default: Groceries)
- SYNC_LIST_NAMES — Comma-separated list names to sync; names must match in Keep and Reminders (e.g., Groceries,Hardware,Pharmacy)
- ICLOUD_COOKIE_DIR — Path in container for iCloud cookies (default: /data/icloud)
- SCHEDULE_INTERVAL_MINUTES — Sync interval in minutes (default: 5)
- LOG_LEVEL — INFO, DEBUG, etc. (default: INFO)
- TZ — Container timezone (e.g. America/Chicago), can be set via compose

## Quick start with Docker Compose
1) Copy env template and fill in values:
   cp .env.example .env
   - Fill GKEEP_* and APPLE_* values
   - Optionally set SYNC_LIST_NAMES=Groceries,Hardware,Pharmacy to sync multiple lists; otherwise single-list variables GKEEP_LIST_TITLE and REMINDERS_LIST_NAME are used
   - For first run with 2FA, provide APPLE_2FA_CODE from your Apple device (then remove after the session is trusted)

2) Build and start:
   docker compose build
   docker compose up -d

3) Inspect logs:
   docker compose logs -f

Notes:
- On the first run, if 2FA is required and APPLE_2FA_CODE is not set, the app will log an error. Set APPLE_2FA_CODE in .env and restart once. After “session trusted” appears in logs, remove APPLE_2FA_CODE from .env and restart to avoid reuse.
- Ensure the target Apple Reminders list exists (default: “Groceries”).

## Run with plain Docker
Build:
  docker build -t gkeep-reminders-sync .

Run:
  docker run -d --name gkeep-reminders-sync \
    --restart unless-stopped \
    --env-file ./.env \
    -v "$(pwd)/data:/data" \
    gkeep-reminders-sync

## Local run (without Docker)
- Python 3.11+
- Create virtualenv and install deps:
  python -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
- Export env vars (see .env.example) and run:
  python main.py

## How it avoids duplicates
- Reads existing uncompleted tasks from the target Reminders list
- Normalizes titles (lowercase, trim internal whitespace)
- Only adds items from Keep that don’t already exist in that list

## Syncing multiple lists
- Provide SYNC_LIST_NAMES as a comma-separated list. For each name N, the app reads unchecked items from the Google Keep list titled N and adds missing items to the Apple Reminders list also titled N.
- If SYNC_LIST_NAMES is not set, the app runs in single-list mode using GKEEP_LIST_TITLE -> REMINDERS_LIST_NAME.

## Troubleshooting
- Google Keep auth errors:
  - If using password login, you may need an “App Password” or master token (GKEEP_MASTER_TOKEN). Token-based login is often more reliable with gkeepapi.
- Reminders list not found:
  - Create the list in Apple Reminders with the exact name (case-insensitive match).
- 2FA keeps prompting:
  - Ensure the container’s /data volume persists across restarts so iCloud cookies are saved. After trusting the session on first run, remove APPLE_2FA_CODE from .env and restart.
- Timezone differences:
  - Optionally set TZ in the compose file.

## Security
- Store secrets in .env (not committed). The included .dockerignore excludes .env from the build context.
- Consider using app-specific passwords where possible.
