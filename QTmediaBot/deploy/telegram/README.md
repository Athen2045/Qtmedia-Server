# Local Bot API deployment

This stack runs the bot and Telegram's Local Bot API server inside Docker
Desktop's WSL2 engine. It is the Milestone 4 laptop deployment and does not
publish a port to the LAN.

The API service builds Telegram's official Bot API 10.2 source at the commit
pinned in `compose.yaml`. The final runtime layer retains the digest-pinned
`aiogram/telegram-bot-api:10.2` container wrapper, but replaces its server
binary with the pinned build. The build raises the source server's fixed
500-second HTTP idle timeout to 7200 seconds so large path-based uploads can
return a confirmed response. Review both the source commit and base-image
digest when updating the service.

## Prerequisites

- Docker Desktop with the WSL2 engine and the Ubuntu distro integrated.
- Telegram `api_id` and `api_hash` from [Telegram API development tools](https://my.telegram.org/).
- The bot token, numeric allowlisted user ID, and allowed source domains in the
  ignored project `.env`.
- Firefox installed and signed in if the current YouTube browser-cookie mode
  is enabled.

While Firefox cookie mode is enabled, add this Windows directory to `.env`:

```dotenv
TELEGRAM_FIREFOX_PROFILE_ROOT=C:/Users/<your-user>/AppData/Roaming/Mozilla/Firefox/Profiles
```

The directory must contain Firefox profile directories with `cookies.sqlite`.
Close Firefox completely before starting the stack. The directory is mounted
read-only into only the bot container; it is not mounted into the Local Bot
API container.

The bot also uses these privacy defaults (the committed `.env.example` shows
the same values):

```dotenv
TELEGRAM_METADATA_DB=var/telegram_state/metadata.sqlite3
TELEGRAM_METADATA_TTL_SECONDS=900
TELEGRAM_ORPHAN_JOB_TTL_SECONDS=900
TELEGRAM_UNCONFIRMED_UPLOAD_RETENTION_SECONDS=900
TELEGRAM_RATE_LIMIT_REQUESTS=5
TELEGRAM_RATE_LIMIT_WINDOW_SECONDS=60
TELEGRAM_MAX_QUEUED_JOBS=2
```

This SQLite file is bot-container-local and short-lived. It records only
terminal operational facts—IDs, status, timestamps, temporary directory,
output size, and stable error code—and never URLs, titles, cookies, or media
filenames. Startup removes expired rows and stale job directories from the
shared job volume. Keep the container and Docker Desktop account private.
Rate-limit timestamps and opaque queued job IDs are memory-only and disappear
on restart. The Telegram bot accepts direct media links only and does not
retain search queries or search-result state.

## Start from PowerShell

Run these commands from the repository root:

```powershell
$dockerBin = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin'
$env:Path = "$dockerBin;$env:Path"

docker compose --env-file QTmediaBot/.env -f QTmediaBot/deploy/telegram/compose.yaml config --quiet
docker compose --env-file QTmediaBot/.env -f QTmediaBot/deploy/telegram/compose.yaml build
docker compose --env-file QTmediaBot/.env -f QTmediaBot/deploy/telegram/compose.yaml up -d
docker compose --env-file QTmediaBot/.env -f QTmediaBot/deploy/telegram/compose.yaml ps
```

The first Bot API build compiles the pinned C++ source and can take several
minutes. Docker caches that stage for later bot-only rebuilds.

`config --quiet` validates interpolation without printing the token or API
credentials. Do not paste normalised Compose configuration or unfiltered logs
into chat because environment values can appear in them.

To follow the bot application log:

```powershell
docker compose --env-file QTmediaBot/.env -f QTmediaBot/deploy/telegram/compose.yaml logs -f telegram-bot
```

The first test should be `/start`, then a small permitted media link. Confirm
that the delivered media is removed from the shared job volume after the
upload. The selected quality message will show real download bytes, total, and
speed at a controlled interval (`TELEGRAM_PROGRESS_UPDATE_SECONDS=10` by
default), then `Preparing for upload…` and `Uploading to Telegram…`. The
upload state is deliberately indeterminate: the Local Bot API reads the shared
file path and does not expose onward-upload byte progress to the Python bot.
If Telegram still returns an ambiguous timeout or network result, the bot does
not retry. It marks the job directory without recording the URL or filename,
keeps the shared path for 900 seconds so the API server can finish reading it,
then deletes it. Confirmed success and confirmed failure still clean
immediately.
Confirm that the temporary inspection/status messages disappear only after
delivery. Large-file testing comes only after the small-file path works.

## Stop and inspect

```powershell
docker compose --env-file QTmediaBot/.env -f QTmediaBot/deploy/telegram/compose.yaml ps
docker compose --env-file QTmediaBot/.env -f QTmediaBot/deploy/telegram/compose.yaml logs --tail=100 telegram-bot-api
docker compose --env-file QTmediaBot/.env -f QTmediaBot/deploy/telegram/compose.yaml down
```

`down` stops and removes the containers but preserves named volumes. Do not use
`down -v` during normal operation because it removes the API state and shared
job volume.

The bot continues to require the laptop, Docker Desktop, WSL2, and an active
network connection while it is serving users.

## Milestone 6 benchmark

Use the [Milestone 6 benchmark and acceptance runbook](../../docs/benchmarks/telegram-milestone-6.md)
for privacy-safe phase metrics, resource snapshots, cleanup checks, disruptive
reliability cases, and one-variable fragment comparisons. Compose passes
`PRIVATE_SEARCH_CONCURRENT_FRAGMENTS` and `PRIVATE_SEARCH_HTTP_CHUNK_SIZE` from
the ignored `.env` into the bot container. Milestone 6 currently runs the
user-requested eight-fragment candidate and an empty chunk-size setting; the
standalone CLI retains its four-fragment default when the environment variable
is unset. Compare the Telegram candidate against four fragments with repeated
runs before treating it as a proven throughput improvement.
