# Telegram Media Downloader Bot — Design and Setup Plan

**Status:** Design draft for review  
**Date:** 2026-08-18  
**Audience:** Project owner and developer maintaining this repository  
**Primary goal:** Turn the existing `qtmedia` Python downloader into a privacy-conscious Telegram bot that accepts direct media links, shows only downloadable qualities, uploads the selected media to the requesting chat, and removes temporary local media afterward.

## 1. Executive decision

The recommended first deployment is:

```text
Telegram user
    |
    | long polling over HTTPS
    v
qtmedia bot process (Python 3.11+, Docker container)
    |
    | metadata inspection / download / FFmpeg
    v
temporary per-job media directory
    |
    | local file path, not a multi-gigabyte Python memory buffer
    v
Telegram Local Bot API server (private Docker network)
    |
    v
Telegram cloud chat
```

Run the two services through Docker Desktop integrated with the existing `ws1` Ubuntu/WSL2 distro. Use polling rather than webhooks, so the laptop does not need a public domain or inbound port.

The bot will use:

- `python-telegram-bot` for Telegram updates, commands, inline keyboards, and uploads.
- Telegram's official Local Bot API server for local-file uploads beyond the hosted Bot API's normal limits.
- The repository's existing `yt-dlp` and FFmpeg pipeline for source inspection, downloading, conversion, and audio extraction.
- SQLite only for short-lived, metadata-only job state and rate-limit data; raw URLs, titles, and media metadata are not persisted.
- Per-job temporary directories, deterministic cleanup, disk-space checks, and a startup janitor.

This is a bot-account design. The `telegram-download-daemon` project is not the base architecture because it uses a Telethon user account to monitor Telegram channels; it is not a BotFather bot that receives arbitrary user links and replies in private chats.

## 2. Scope and non-goals

### Included

- `/start`, `/help`, `/cancel`, and a privacy notice.
- A “Download link” action and direct pasted-link handling.
- Direct URL inspection before downloading.
- Quality buttons generated from formats actually available for that source.
- Only showing options that pass source and configured deployment checks.
- Video qualities such as 1440p, 1080p, 720p, 480p, 240p, and 144p when available.
- Audio extraction when an audio stream is available and FFmpeg can process it:
  MP3 at 192 kbps and M4A/AAC at 256 kbps for Telegram music-player playback,
  plus FLAC and ALAC as lossless documents. Converted audio sizes are estimates where
  applicable; every final output is checked against the configured cap.
- A status message with real, byte-based download progress and an honest
  indeterminate Local Bot API upload-confirmation state.
- One active job per user in the initial laptop deployment.
- Maximum duration, maximum output size, source allowlist, rate limits, and an optional Telegram-user allowlist.
- Deleting local media after successful upload, cancellation, failure, or expiry.
- Docker/WSL setup instructions and a later path to VPS deployment.

### Excluded from this first design

- A Telethon user session, channel scraping, or downloading all media from Telegram channels.
- Public hosting or a production multi-region queue.
- Permanent media storage, a download history, user analytics, or raw URL logging.
- Bypassing authentication, paywalls, DRM, geo-restrictions, or source terms.
- Automatic retry behavior that could create duplicate uploads.
- Group-chat operation before private-chat behavior is stable.
- Payments, quotas, a web dashboard, or a public API.
- Search inside the Telegram bot. The existing CLI search remains a separate,
  supported interface.

## 3. User experience

### `/start`

The bot sends a short explanation:

```text
Paste a supported media link to inspect and download it.

Media is processed temporarily and deleted from this service after delivery or expiry.
Please download only content you are allowed to access and redistribute.
```

The reply keyboard contains:

- `Download link`
- `Cancel`

Telegram cannot force-open a user's clipboard. “Download link” is therefore a mode button that tells the user to paste the URL in the next message.

### Link flow

1. User chooses `Download link` or sends a URL directly.
2. Bot validates the message and URL.
3. Bot rejects unsupported, malformed, unsafe, private-network, or disallowed domains before invoking a downloader.
4. Bot inspects metadata without downloading the final file.
5. Bot derives a format catalog from the source's actual formats.
6. Bot shows only available options, for example:

   ```text
   1080p — 182 MB
   720p — 91 MB
   480p — 48 MB
   MP3 (192 kbps) — ~7 MB
   M4A (AAC 256 kbps) — ~9 MB
   FLAC (lossless) — size unknown
   ALAC (lossless) — size unknown
   ```

   If the source has no 1440p stream, 1440p is not shown. If a known output exceeds the configured Telegram/deployment cap, it is not shown.
   MP3 and M4A are delivered through Telegram's audio player; FLAC and ALAC
   are sent as documents so their lossless files are preserved and can be
   opened in a local music player. A lossless conversion cannot restore detail
   already absent from a lossy source stream.

   If strict normalization produces no selectable qualities, the bot may show
   one `Best available` option only when inspection exposes a policy-approved
   direct video URL with an exact positive byte length at or below the
   configured cap. Unknown or approximate sizes, redirects, non-video
   responses, unsafe provider media, and over-cap files do not qualify.

7. User clicks a quality button.
8. Bot authorizes the callback against the requesting user and job ID.
9. Bot downloads and post-processes the selected format into a per-job directory,
   with an in-memory, throttled byte-progress status message.
10. Bot checks the resulting file, disk state, duration, and size.
11. Bot shows preparation, then uploads by local file path through the Local Bot
    API server with an indeterminate confirmation status. It does not invent
    upload bytes or speed that the path-based handoff cannot observe.
12. After a successful API response, bot deletes the local media and temporary sidecars.
13. After Telegram confirms delivery, the bot removes its temporary inspection
    and downloading status messages and expires short-lived job metadata.

### Error messages

The user-facing messages should distinguish these cases without exposing internals:

- “That link is not supported by this bot.”
- “The link is valid, but no downloadable media formats were found.”
- “The source did not expose the requested quality anymore. Please inspect the link again.”
- “This media is longer or larger than the bot's configured limit.”
- “The download failed at the source. Please try another link.”
- “The upload failed; the temporary file has been removed.”
- “The bot is busy. Please try again shortly.”

Internal logs use stable error codes and sanitized exception summaries, never raw URLs, bot tokens, cookies, filenames containing user data, or user names.

## 4. Architecture decisions

### Telegram transport

Use long polling with `getUpdates` for the laptop deployment. It avoids a public inbound endpoint and is simpler to operate behind a home router. The bot process should remove or acknowledge updates only after it has accepted them into its bounded work queue.

Do not run both polling and webhooks for the same bot token. If a webhook was previously configured, clear it before starting polling.

### Local Bot API server

The hosted Bot API has file-size restrictions. Telegram's Local Bot API server supports local-file paths, removes the hosted download-size restriction, and supports uploads up to the server's documented 2000 MB limit. It does not make the laptop's disk, CPU, network, or electricity free; it only removes the hosted API bottleneck.

Run the Local Bot API server with local mode enabled, on an internal Docker network. Do not publish its port to the LAN. If a diagnostic port is temporarily published, bind it to `127.0.0.1` only.

The bot and API containers must mount the job volume at the same path, for example:

```text
bot container:       /var/lib/qtmedia/telegram_jobs
local API container: /var/lib/qtmedia/telegram_jobs
```

This allows the bot library to pass a local file path without reading a multi-gigabyte file into Python memory.

The Local Bot API's HTTP server also has an implementation-level idle timeout
of 500 seconds in the current upstream source. A local-path upload can still
be unresolved at that boundary when the server is forwarding the file to
Telegram, so the client may observe an ambiguous request even though the
server-side operation has not necessarily stopped. The job lifecycle must not
delete the shared path immediately after such an ambiguous result unless the
server operation is known to have terminated; use a tested retention or
termination strategy instead. See the upstream [idle-timeout issue](https://github.com/tdlib/telegram-bot-api/issues/224)
and [`HttpServer.h`](https://github.com/tdlib/telegram-bot-api/blob/master/telegram-bot-api/HttpServer.h).

### Telegram Python library

Use `python-telegram-bot` as the first implementation because the repository is already Python-based and the library provides an async application model, handlers, inline keyboards, polling, and configurable Bot API base URLs.

The application builder will need the following conceptual settings:

```text
token:          TELEGRAM_BOT_TOKEN
base_url:       http://telegram-bot-api:8081/bot
base_file_url:  http://telegram-bot-api:8081/file/bot
local_mode:     true
```

Pin the tested library version in `pyproject.toml`; do not install an unpinned “latest” version in a repeatable deployment.

### Download engine boundary

The current CLI download function is user-facing and writes to the global
`Qtmedia/var/downloads` location. The bot should not call it unchanged.
Introduce a bot-oriented service boundary that accepts:

- a validated direct URL;
- an opaque job ID and private job directory;
- a selected format key;
- duration and output-size limits;
- a cancellation event;
- structured progress callbacks.

The service returns a structured result containing only the local output path, detected media type, size, duration, and a stable error code. The Telegram layer must not depend on printed CLI output.

## 5. Required accounts, software, and libraries

### Telegram setup

1. Open Telegram and message `@BotFather`.
2. Run `/newbot`.
3. Choose a display name and a unique username ending in `bot`.
4. Save the generated token in a secret store or local `.env` file that is excluded from Git.
5. During beta, restrict use to your own Telegram user ID or an explicit allowlist.
6. Obtain `api_id` and `api_hash` from `https://my.telegram.org` → **API development tools**. These are required by the Local Bot API server and are separate from the BotFather token.

Do not paste either credential into source code, issues, screenshots, public logs, or the repository.

### Host tooling

Recommended laptop path:

- Windows 10/11 with WSL2.
- The existing Ubuntu distribution, referred to here as `ws1`.
- Docker Desktop with the WSL2 engine and WSL integration enabled for `ws1`.
- Git.
- Docker Compose v2, supplied by Docker Desktop.
- At least 20 GB free working space for the initial deployment; more is required for concurrent or multi-gigabyte jobs.
- Stable outbound Internet access.

FFmpeg and Python dependencies should be installed in the bot image so the runtime is reproducible. Installing host copies is useful for native WSL development but is not required for the Docker deployment.

### Python runtime dependencies

Keep the existing dependencies:

- `yt-dlp`
- `beautifulsoup4`
- `requests`
- `rich`
- `rapidfuzz`
- `Pillow`
- `typer`
- optional `curl-cffi` for configured impersonation support

Add:

- `python-telegram-bot` at a pinned, tested 22.x version.

Use Python standard-library modules wherever possible: `asyncio`, `sqlite3`, `pathlib`, `tempfile`, `secrets`, `ipaddress`, `socket`, `shutil`, and `time`. Do not add a Dataverse SDK, Telethon, or a second database for this design.

Development and verification continue to use the existing `pytest`, `ruff`, and `pylint` tooling.

## 6. Privacy and data-retention design

Privacy is a system property, not just a deletion call after upload.

### Data minimization

The bot must not persist:

- raw user URLs;
- Telegram usernames, display names, or message text;
- media titles, descriptions, thumbnails, or source cookies;
- permanent download history;
- uploaded media after the job is complete.

Raw URLs and source metadata may exist in process memory while the job is active. The active-memory catalog expires after a short TTL and is discarded on restart.

The bot may support an operator-explicit YouTube authentication mode for sources
that reject the laptop's guest session. It is disabled by default. When enabled,
the operator selects one validated local browser; yt-dlp reads browser cookies
only for YouTube hosts, no cookie-file path is accepted, yt-dlp's persistent
cache is disabled for that request, and the Telegram bot must have a non-empty
user allowlist. Cookies must never enter job state, logs, uploads, or Git. The
operator accepts the account and platform risk before enabling this mode.

### Minimal SQLite records

SQLite may contain only short-lived operational metadata, such as:

```text
job_id, chat_id, user_id, status, temp_dir, created_at, updated_at,
expires_at, output_size, error_code
```

It must not contain the raw URL or media title. Treat chat and user IDs as personal data: protect the runtime directory with normal OS permissions, avoid copying the database to backups, and prune records promptly.

Suggested indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_jobs_status_expiry
    ON telegram_jobs(status, expires_at);

CREATE INDEX IF NOT EXISTS idx_jobs_user_status
    ON telegram_jobs(user_id, status);
```

Use parameterized statements, explicit column lists, short transactions, and bounded cleanup batches. Enable WAL only if it is useful for the selected single-process workload; do not assume WAL alone provides confidentiality.

The existing CLI search cache stores source URLs. The Telegram bot does not
invoke the search engine or its cache; direct-link source data remains only in
the active in-memory job catalog and is never added to persistent SQLite state.

### Temporary storage rules

Create one random directory per job below a fixed root:

```text
var/telegram_jobs/<random-job-id>/
```

The implementation must:

- generate IDs with `secrets`, not user input;
- sanitize output names;
- resolve paths before deletion and verify they remain below the job root;
- refuse symlink escapes;
- never delete a caller-supplied arbitrary path;
- remove media, sidecars, thumbnails, partial downloads, and FFmpeg intermediates;
- run a startup janitor for abandoned directories older than the configured recovery TTL;
- run a periodic janitor for expired jobs;
- keep a disk-reserve threshold so cleanup itself can complete.

On successful upload, delete the local output immediately after the Telegram API call returns success. On upload failure, cancel, timeout, or process crash, the janitor removes the directory after a short safety TTL. A successful Telegram upload does not delete the copy already delivered into the user's Telegram chat; it deletes only the local working copy.

The Local Bot API server may have its own data directory. Keep it on a protected volume, inspect its growth during testing, and clean only documented inactive temporary data. Never blindly delete the API server's live state while it is running.

### Privacy notice and legal boundary

The bot should explain that links and media are processed temporarily, that Telegram receives the selected file, and that local temporary files are removed after delivery or expiry. Users must be instructed to download only content they have permission to access. The operator remains responsible for source-site terms, copyright, privacy, and any age or jurisdiction requirements.

## 7. Job state and authorization

Each request receives an opaque random `job_id`. Callback data contains only a compact action, job ID, and format key; it must not contain a URL.

Recommended states:

```text
received → validating → inspecting → awaiting_format → queued
queued → downloading → uploading → completed
any active state → cancelled | failed | expired
```

For every callback, verify:

1. the job exists and is not expired;
2. the Telegram user and chat match the job owner;
3. the requested format key belongs to the job's in-memory format catalog;
4. the job is in `awaiting_format` state;
5. no competing active job exists for that user.

A restart invalidates in-memory format catalogs. Existing temporary directories are cleaned or marked failed; users must submit the link again. This is intentional: it avoids persisting sensitive source metadata merely to resume a job.

Initial limits should be conservative:

- one active job per user;
- one or two concurrent inspection tasks globally;
- one download/upload job globally on a laptop;
- maximum duration configured by environment variable;
- maximum output bytes below the tested Local Bot API limit, for example 1.8 GB initially;
- per-user cooldown and a global queue limit;
- optional Telegram-user allowlist during beta.

## 8. Format inspection and quality selection

The inspection layer should use `yt-dlp` metadata only, then normalize formats into an internal catalog. Each option should include:

- stable internal format key;
- video height, if present;
- whether video and audio are both present;
- container/extension;
- exact `filesize` when available;
- `filesize_approx` when exact size is unavailable;
- estimated output size for post-processing when possible;
- whether the option requires FFmpeg merging or extraction.

Quality selection rules:

- group video formats by the highest usable height at or below each requested label;
- prefer a compatible video-plus-audio result or a video/audio merge plan;
- include only heights exposed by the source;
- show an approximate-size marker when necessary;
- show `MP3` only when audio extraction is possible;
- omit formats known to exceed the configured output limit;
- never promise a quality that the source does not provide;
- revalidate the selected format immediately before download because URLs and availability can expire.
- preserve normal source quality choices when any are usable; do not append a
  generic best choice to that catalog;
- when no normal option survives, allow one exact-size `Best available`
  fallback using the CLI selector `bestvideo+bestaudio/best`, but only for a
  direct URL that passes the bot's configured allowed-source policy (or an
  exact provider-owned media-domain policy recorded by the adapter) and whose
  known size is less than or equal to the configured output cap;
- fail closed when the fallback size is missing, approximate, redirected, not
  video media, unsafe, or above the cap, and enforce the cap again during and
  after download.

The bot should not expose raw `yt-dlp` format IDs to users. Store them in the server-side job catalog keyed by the opaque format key.

Provider adapters may resolve an approved page URL to a provider-owned media
manifest only in active memory. The submitted URL must pass the normal source
allowlist first; the resolved URL must use HTTPS, match the adapter's exact
trusted media-domain policy, and resolve only to public addresses before
yt-dlp receives it. Both inspection and download must use the same transient
resolved URL so the offered format IDs remain valid. PMVHaven uses this path:
its fixed metadata endpoint resolves a recognized video ID to the approved
PMVHaven CDN, then yt-dlp inspects the returned HLS manifest. Resolved URLs,
titles, and manifests remain excluded from SQLite and normal logs.

For providers whose extractor accepts more than one page shape, a bot-specific
page-variant adapter may try only documented same-video forms before invoking
yt-dlp's generic extractor. Eporner and NoodleMagazine use this bounded strategy:
their adapters recognize only their approved page hosts, derive the same provider
video ID, and retain the selected alternate page only in active memory. The
download phase revalidates that alternate page against the normal HTTPS source
allowlist and same-video ownership rule. These adapters must not duplicate an
unstable provider API or use an external hosted downloader; yt-dlp remains the
canonical extractor and unknown hosts or IDs fail closed. A provider-specific
TLS impersonation profile may be selected only from the already-installed
curl-cffi profiles and must remain scoped to that adapter; it must not enable
browser cookies or alter the CLI's provider settings.

For the adaptive `Best available` path, the inspection record carries the
exact validation-domain set used for the direct candidate. This applies across
all configured allowed sources: same-domain or explicitly configured-source
media is validated against the bot source allowlist, while provider CDN media
is validated against that provider's exact adapter policy. The download phase
must reuse that recorded policy and re-probe the direct URL before transfer;
it must not infer trust from the submitted page URL alone.

## 9. Performance and resource controls

The Telegram handlers are asynchronous, but `yt-dlp`, FFmpeg, and parts of the existing network stack are blocking. Run those operations in bounded worker threads or subprocesses so the update loop remains responsive.

Required controls:

- `asyncio.Semaphore` for global inspection and download limits;
- cancellation events passed into the download service;
- bounded queues with a clear “busy” response;
- progress updates at coarse milestones or no more than every 10–15 seconds;
- no progress message for every download callback, which would hit Telegram rate limits;
- progress data remains transient and numeric-only; the Local Bot API upload
  state is indeterminate because Python passes it a shared local file path;
- file-path uploads and streaming subprocess output, never `read_bytes()` for large media;
- `shutil.disk_usage()` checks before download and before FFmpeg conversion;
- reserve-space checks accounting for temporary duplicate files during merging;
- timeouts for metadata inspection, download, FFmpeg, and upload;
- output validation after download: exists, regular file, expected size, and allowed extension/type.

Measure before optimizing. Add structured timings for inspection, download, FFmpeg, upload, and cleanup. For local tests, use `cProfile` for CPU-heavy paths, memory monitoring for upload handling, and repeatable small fixtures. Do not enable verbose profiling or full source metadata logging in normal operation.

## 10. Docker/WSL deployment layout

### Preferred topology

```text
Windows
└── Docker Desktop (WSL2 engine)
    ├── telegram-bot-api
    │   ├── internal port 8081
    │   └── protected API data volume
    └── qtmedia-bot
        ├── Python application
        ├── yt-dlp
        ├── FFmpeg
        └── shared temporary-job volume
```

No service needs a public inbound port for polling. Docker containers should share a private network. Publish the API port only to `127.0.0.1` when a local diagnostic is genuinely required.

### Compose implementation

`QTmediaBot/deploy/telegram/compose.yaml` defines two services with this topology. The
Local Bot API service uses the verified unofficial
`aiogram/telegram-bot-api:10.2` image pinned by digest. It is a container
wrapper around the official Telegram Bot API server source and remains on the
private Compose network; no API port is published to the LAN.

```yaml
services:
  telegram-bot-api:
    image: aiogram/telegram-bot-api:10.2@sha256:6706cc91b0d630b90e246567c1735e13c0cc152f5832e79db708d6c6de4dff3f
    environment:
      TELEGRAM_API_ID: ${TELEGRAM_API_ID}
      TELEGRAM_API_HASH: ${TELEGRAM_API_HASH}
    volumes:
      - telegram_api_data:/var/lib/telegram-bot-api
      - telegram_jobs:/var/lib/qtmedia/telegram_jobs
    networks: [private]

  telegram-bot:
    build:
      context: ../..
      dockerfile: deploy/telegram/Dockerfile
    environment:
      TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN}
      TELEGRAM_BASE_URL: http://telegram-bot-api:8081/bot
      TELEGRAM_FILE_BASE_URL: http://telegram-bot-api:8081/file/bot
      TELEGRAM_LOCAL_MODE: "1"
      TELEGRAM_JOB_ROOT: /var/lib/qtmedia/telegram_jobs
      TELEGRAM_MAX_UPLOAD_BYTES: ${TELEGRAM_MAX_UPLOAD_BYTES}
    volumes:
      - telegram_jobs:/var/lib/qtmedia/telegram_jobs
      - type: bind
        source: ${TELEGRAM_FIREFOX_PROFILE_ROOT}
        target: /home/qtmedia/.config/mozilla/firefox
        read_only: true
    depends_on:
      - telegram-bot-api
    networks: [private]

networks:
  private:

volumes:
  telegram_api_data:
  telegram_jobs:
```

The image environment names, data-directory paths, digest, and local-mode
behavior were verified against the selected image and the official Telegram
Local Bot API documentation. The bot's Firefox profile bind mount is required
only while browser-cookie mode is enabled and is intentionally absent from the
API service.

### Environment configuration

The local `.env` should contain placeholders like:

```dotenv
TELEGRAM_BOT_TOKEN=replace_me
TELEGRAM_API_ID=replace_me
TELEGRAM_API_HASH=replace_me
TELEGRAM_FIREFOX_PROFILE_ROOT=C:/Users/<your-user>/AppData/Roaming/Mozilla/Firefox/Profiles
TELEGRAM_MAX_UPLOAD_BYTES=1800000000
TELEGRAM_MAX_DURATION_SECONDS=3600
TELEGRAM_MAX_CONCURRENT_JOBS=1
TELEGRAM_ALLOWED_USER_IDS=
# Example only; keep the active list limited to sources you have reviewed.
TELEGRAM_ALLOWED_DOMAINS=youtube.com,youtu.be,xvideos.com,xhamster.com,spankbang.com,tnaflix.com,youjizz.com,youporn.com,pmvhaven.com,noodlemagazine.com,eporner.com,xnxx.com
TELEGRAM_JOB_TTL_SECONDS=3600
TELEGRAM_FAILED_JOB_RETENTION_SECONDS=900
# Optional, disabled by default; YouTube-only local browser-cookie access
PRIVATE_SEARCH_YTDLP_COOKIES_FROM_BROWSER=
# Optional browser profile name/path
PRIVATE_SEARCH_YTDLP_COOKIES_BROWSER_PROFILE=
```

The real file must be ignored by Git and protected by filesystem permissions. A committed `.env.example` may contain variable names and safe example values only.

## 11. Step-by-step laptop setup

These are the operator steps for the implemented Milestone 4 deployment.

### Step A — Verify WSL2

In PowerShell:

```powershell
wsl --status
wsl --update
wsl -l -v
```

Confirm that the Ubuntu distro you intend to use is version 2. If its registered name is exactly `ws1`, the command is:

```powershell
wsl --set-version ws1 2
```

Otherwise use the exact name shown by `wsl -l -v`.

Inside Ubuntu, update packages and install basic development tools:

```bash
sudo apt update
sudo apt install -y git ca-certificates curl
```

With the Docker deployment, FFmpeg and Python are installed in the image. Install them in WSL as well only if you plan to run the bot natively.

### Step B — Install and integrate Docker Desktop

Install Docker Desktop for Windows, enable the WSL2-based engine, and enable WSL integration for the chosen Ubuntu distro. Verify from Ubuntu:

```bash
docker version
docker compose version
```

Do not expose Docker's API socket or the Local Bot API server to the local network.

### Step C — Prepare the repository

Clone or open the repository from WSL. For high I/O workloads, a repository under the Linux filesystem such as `~/src/qtmedia` is generally preferable to a path under `/mnt/c`; keep the authoritative Git working tree where the project workflow expects it and benchmark before moving it.

The implementation phase will add:

- a bot application module;
- a bot-specific download service adapter;
- a privacy-aware job manager and cleanup worker;
- a Dockerfile;
- a Compose file;
- `.env.example` additions;
- unit and integration tests;
- operator documentation.

### Step D — Create Telegram credentials

Create the BotFather bot, retrieve `api_id` and `api_hash` from `my.telegram.org`, and place them only in the local `.env`. Restrict the beta bot to the operator's Telegram user ID before opening it to anyone else.

### Step E — Build and start the stack

From the repository root, after filling the ignored `QTmediaBot/.env`:

```bash
docker compose --env-file QTmediaBot/.env -f QTmediaBot/deploy/telegram/compose.yaml config --quiet
docker compose --env-file QTmediaBot/.env -f QTmediaBot/deploy/telegram/compose.yaml build
docker compose --env-file QTmediaBot/.env -f QTmediaBot/deploy/telegram/compose.yaml up -d
docker compose --env-file QTmediaBot/.env -f QTmediaBot/deploy/telegram/compose.yaml ps
docker compose --env-file QTmediaBot/.env -f QTmediaBot/deploy/telegram/compose.yaml logs -f telegram-bot
```

On Windows PowerShell, add Docker Desktop's bin directory to `PATH` first if
the `docker` command is not already available. Keep Firefox closed while the
bot is running so yt-dlp can read the read-only cookie database.

The bot should first pass a minimal health check, then handle `/start`, then inspect a small permitted test URL. Do not begin with a multi-gigabyte file.

### Step F — Verify deletion

During a test job, inspect only the job root and confirm:

1. a unique temporary directory is created;
2. the selected file is not held in Python memory as a full byte array;
3. the upload succeeds;
4. the local media and sidecars are gone;
5. a cancelled or failed job is removed by the failure TTL;
6. a forced restart removes stale abandoned directories on startup.

### Step G — Operate the laptop deployment

The laptop, Docker Desktop, WSL2, and network connection must remain available while the bot is serving users. Configure Docker Desktop to start with Windows only if the operator accepts that the bot will consume resources and network bandwidth automatically. Keep the beta user allowlist enabled until resource behavior is understood.

## 12. Native WSL fallback

A native Ubuntu process is possible but is not the primary recommendation. It requires installing and maintaining Python, FFmpeg, the Local Bot API server build or binary, service restart behavior, log rotation, and shared path conventions manually.

Use it when Docker Desktop is unavailable or when profiling shows a concrete container integration issue. The same application configuration, privacy rules, polling transport, and cleanup lifecycle must remain unchanged. Do not create a second architecture with different security behavior.

## 13. Security and abuse controls

The bot will fetch user-supplied URLs, so URL validation is a security boundary.

Implement all of the following before public use:

- HTTPS-only source URLs unless a narrowly documented exception is required;
- an explicit allowed-domain policy for supported providers;
- DNS resolution checks that reject loopback, private, link-local, multicast, reserved, and unspecified IP ranges;
- redirect revalidation so a permitted hostname cannot redirect into a private network;
- request and download timeouts;
- response-size and duration limits;
- safe output path handling;
- no shell command construction from user input;
- no source cookies or credentials from the host environment by default;
- optional browser-cookie mode is YouTube-only, allowlist-required, non-persistent,
  and explicitly disabled unless the operator enables it;
- Telegram-user allowlist for beta;
- per-user and global rate limits;
- queue length limits;
- sanitized logs and secret redaction;
- protected `.env`, Docker volumes, and runtime directories;
- dependency pinning and regular updates;
- a clear abuse/contact policy before public release.

Do not treat a Telegram URL as automatically safe. Do not allow the current CLI behavior of accepting arbitrary HTTPS hosts to become a public bot policy without adding the allowlist and SSRF checks.

## 14. Testing and acceptance criteria

### Unit tests

- URL parsing and supported-domain policy.
- DNS/private-IP rejection, including redirects.
- Format normalization and quality grouping.
- Exact versus approximate file-size display.
- Omission of unavailable qualities.
- Omission of known-over-limit outputs.
- Exact-size, under-cap `Best available` fallback when no normal quality is
  selectable, including omission for unknown/approximate and over-cap sizes.
- Provider fallback URL validation and selected-fallback download routing.
- MP3 availability rules.
- Callback ownership and expired-job rejection.
- Job state transitions and cancellation.
- Safe cleanup against normal files, missing files, symlinks, and path traversal attempts.
- SQLite parameterization, indexes, TTL cleanup, and absence of raw URL columns.

### Integration tests

- Fake Telegram API responses for polling, callback queries, and successful uploads.
- Fake downloader metadata with several format combinations.
- A small deterministic media fixture for FFmpeg conversion.
- Upload failure followed by cleanup.
- Process restart with an abandoned job directory.
- Bounded concurrency under multiple messages.

### Manual acceptance checklist

- `/start` displays guidance and privacy notice.
- Direct link produces only available quality buttons.
- Invalid and unsupported links receive safe, useful messages.
- Selecting a quality downloads and uploads the correct media type.
- MP3 appears only when available.
- A file above the configured cap is not offered or is rejected before upload.
- Local media disappears after success.
- Local media disappears after cancellation, failure, and restart recovery.
- No URL, token, cookie, title, or username appears in normal logs.
- The Local Bot API port is not reachable from another device on the LAN.
- The bot stops cleanly when Docker or WSL is stopped.

## 15. Implementation milestones

### Milestone 1 — Bot skeleton

Add BotFather token configuration, polling, `/start`, `/help`, `/cancel`, private-chat handling, a health log, and a user allowlist. No downloads yet.

### Milestone 2 — Inspection and quality catalog

Refactor the existing inspection path into a structured service. Add source policy, SSRF checks, format normalization, size display, and inline quality callbacks. Use fake metadata tests.

### Milestone 3 — Per-job downloads

Add job directories, bounded workers, cancellation, FFmpeg output validation, disk checks, and structured errors. Keep the existing CLI behavior intact.

### Milestone 4 — Local Bot API integration

Add the Dockerfile, Compose services, local-mode URLs, shared volume, and small-file end-to-end upload. Verify the same path is visible in both containers.

### Milestone 5 — Privacy hardening

Implemented: bot inspection remains separate from the CLI's persistent URL
cache; URL-free terminal SQLite metadata has TTL cleanup; startup removes stale
job directories; runtime logging redacts URLs and tokens; obvious token
placeholders are rejected; and deletion/recovery behavior is covered by tests.

### Milestone 6 — Transfer optimization, admission, and controlled beta

Add rate limits and global queue limits, test several direct-link sources, and
then allow only trusted users. Treat transfer optimization as a measured reliability exercise: do not
increase concurrency, move media to a Windows bind mount, or introduce an
external downloader without a benchmark showing a repeatable improvement.

#### Required optimization practices

- **Preserve the fast upload path.** In Local Bot API mode, pass the completed
  media `Path` directly through the shared Docker volume. Do not read the full
  file into Python memory and do not proxy the media through the bot process.
  Mount the job volume at the same absolute Linux path in both containers.
- **Use size-aware video delivery.** Route video files of 1,000,000,000 bytes
  or less through `sendVideo` so Telegram clients can play them inline. Route
  larger video files through `sendDocument` for the safer general-file path.
  This is a delivery-format policy, not a guaranteed network-speed increase;
  both paths must continue using the shared local `Path` and the same
  ambiguous-upload protection.
- **Use phase-specific deadlines.** Keep separate inspection, download,
  post-processing, and upload deadlines. The upload wrapper must use
  `TELEGRAM_UPLOAD_TIMEOUT_SECONDS`, not the download timeout. For a local-path
  request, configure ordinary request read/write timeouts as well as the outer
  job deadline; multipart-only media timeouts do not control this path.
- **Make upload outcomes idempotent.** Treat timeout or network loss after the
  send begins as `upload_unconfirmed`; never automatically retry the same media
  because that could create a duplicate Telegram message. Preserve the job's
  terminal state, and do not remove the shared path until the Local Bot API
  operation has terminated or a tested safety-retention policy makes removal
  safe.
- **Account for the Local Bot API idle boundary.** The current upstream server
  closes an idle HTTP request after 500 seconds. A large upload must either
  complete within that boundary or use a server-compatible strategy that
  prevents the client timeout and cleanup path from racing the server-side
  upload. Treat this as a required large-file acceptance case, not as a reason
  to raise the output cap or fragment concurrency.
- **Measure each phase without collecting private content.** Record only job
  ID, phase, duration, byte count, stable result/error code, and bounded resource
  samples. Do not record URLs, titles, filenames, cookies, tokens, usernames,
  or raw Telegram responses. At minimum measure inspection, source download,
  FFmpeg/post-processing, Local Bot API request duration, cleanup, CPU, memory,
  free disk, and Docker volume growth.
- **Keep download concurrency conservative.** Benchmark yt-dlp native fragment
  concurrency at 1, 2, 4, and—only if justified—8 for the same permitted
  source. Keep the best value per source class only when it improves throughput
  without increasing failures, throttling, CPU contention, or disk pressure.
  Do not apply a global concurrency increase based on one test.
- **Keep resumability and safe temporary files.** Retain yt-dlp continuation
  and `.part` behavior. Keep temporary fragments, merged output, and final
  output on the same fast Linux/Docker volume where possible; account for peak
  duplicate space before starting a merge.
- **Avoid unnecessary CPU work.** Prefer a compatible direct format or remux
  over re-encoding. Do not add FFmpeg thread or codec settings until profiling
  shows CPU-bound post-processing. Keep Node/EJS and browser-cookie behavior
  unchanged unless a source-specific benchmark or authentication failure
  requires a documented change.
- **Keep hot media I/O in Linux storage.** Continue using the Docker named
  volume for job media and protected API state. If host inspection is required,
  use Docker-aware inspection or a WSL/Linux filesystem bind mount; do not use a
  `C:\...` or `/mnt/c/...` bind mount as the performance baseline for large
  media.
- **Protect the update loop and Telegram limits.** Keep blocking yt-dlp and
  FFmpeg work off the async update loop, retain one active media job on the
  laptop, bound the queue, and register the long-running quality-transfer
  callback as non-blocking so `/cancel` and the Cancel button can be processed
  while that transfer is active. Keep command and ordinary message handlers
  serialized, and throttle progress edits to the configured interval. Download
  progress may show measured bytes and speed; Local Bot API upload progress
  must remain an honest indeterminate confirmation state.
- **Fail early and clean predictably.** Check source policy, duration, output
  cap, available disk, and reserve space before expensive work. Validate the
  final regular file before upload. Remove media after confirmed success and
  remove failed, cancelled, expired, or abandoned job directories through the
  bounded cleanup lifecycle.
- **Keep state minimal and queryable.** Active job details remain in memory
  with TTLs. SQLite may retain only the existing metadata-only
  terminal record and rate-limit state, using parameterized statements,
  short transactions, and indexes that match cleanup/status lookups. No URL or
  media metadata is added to the database for performance monitoring.

#### Milestone 6 benchmark and acceptance gate

Run repeatable tests with a permitted, non-secret source at small, medium, and
large sizes. For each run record the selected quality, output bytes, download
speed, post-processing duration, Local Bot API request duration, final outcome,
peak disk usage, CPU/RAM observations, and volume growth. Compare the current
defaults against only one changed variable at a time.

The executable operator procedure and privacy-safe result template are in
[`docs/benchmarks/telegram-milestone-6.md`](../../benchmarks/telegram-milestone-6.md).
The template explicitly excludes source URLs, titles, filenames, Telegram
identities, credentials, cookies, and raw API responses.

Milestone 6 is accepted only when:

1. Direct-link jobs do not persist raw URLs or titles.
2. Per-user limits, global queue limits, and one-active-job ownership work.
3. Download progress remains numeric and rate-limited; upload status does not
   invent byte counts or speed.
4. A successful local-path upload leaves only the delivered Telegram media and
   cleans the job directory.
5. An upload timeout or network interruption produces no automatic duplicate
   retry and leaves a safely cleaned or TTL-retained job as designed.
6. The bot remains responsive while downloading, post-processing, and waiting
   for Local Bot API confirmation.
7. No tested optimization reduces privacy controls, cleanup guarantees, source
   validation, or resource limits.
8. The benchmark report identifies the chosen concurrency, storage path,
   timeout values, and output cap with evidence; otherwise defaults remain
   unchanged.

### Milestone 7 — Larger-file validation

Test progressively larger permitted fixtures, monitor disk, RAM, CPU, upload time, Docker volume growth, and Telegram rate behavior. Only then raise the output cap.

## 16. Operational risks and mitigations

| Risk | Mitigation |
|---|---|
| Laptop sleeps or loses Internet | Treat local hosting as beta; later move the same containers to a VPS. |
| Disk fills during FFmpeg merge | Reserve-space checks, one active job, startup/periodic janitor, conservative cap. |
| A source URL targets an internal service | Domain allowlist, DNS/IP validation, redirect revalidation, timeouts. |
| Telegram API rejects a large file | Test Local Bot API local mode, shared local path, and a cap below the documented maximum. |
| Local Bot API upload takes minutes or becomes ambiguous | Build pinned official source with a 7200-second HTTP idle timeout, keep phase-specific deadlines, collect redacted phase timings, classify timeout/network loss as unconfirmed, retain a possibly active shared path until its short safety expiry, and never retry automatically. |
| Large-file merge temporarily doubles disk use | Keep temporary and final files on the same volume, reserve peak working space before FFmpeg, and retain one active media job on the laptop. |
| WSL2 media I/O is slow | Keep hot job data in a Docker named volume or Linux filesystem; benchmark before changing storage and avoid `/mnt/c` for the hot path. |
| Bot leaks URLs through cache or logs | Disable bot persistent cache, redact logs, keep URL only in memory. |
| Callback is replayed by another user | Opaque job IDs plus user/chat ownership checks and expiration. |
| Telegram rate limits are hit | Coarse progress updates, bounded concurrency, and message edit throttling. |
| A restart leaves media behind | Startup janitor with root-bound path validation and a short orphan TTL. |
| Third-party source terms change | Supported-domain policy, clear error handling, regular `yt-dlp` updates, legal review. |

## 17. Named skill applicability

- **Documentation writer:** this document is organized as an operator-facing how-to/design specification, with setup, reference decisions, testing, and rollout sections.
- **Research:** primary Telegram, WSL, Python Telegram library, and referenced-repository documentation informs the constraints and setup choices.
- **Python performance optimization:** bounded concurrency, non-blocking handlers, path-based uploads, disk checks, profiling before optimization, and memory-conscious media processing.
- **SQL optimization:** explicit metadata columns, parameterized queries, indexes for status/expiry and user/status lookups, short transactions, and bounded cleanup.
- **Telegram bot builder:** commands, reply keyboards, inline callback authorization, polling, rate limits, error handling, and configuration boundaries.
- **Dataverse Python advanced patterns:** no Dataverse service is present or needed. Its enterprise API patterns are deliberately not added to this local SQLite/Telegram application.

## 18. Research references

- [Telegram Bot API — Using a local Bot API server](https://core.telegram.org/bots/api#using-a-local-bot-api-server)
- [Telegram Bot API — Sending files](https://core.telegram.org/bots/api#sending-files)
- [Telegram Bot API — Getting updates](https://core.telegram.org/bots/api#getting-updates)
- [Telegram Bot API — `getFile`](https://core.telegram.org/bots/api#getfile)
- [Telegram Bot Features](https://core.telegram.org/bots/features)
- [Telegram API — Obtaining an API ID](https://core.telegram.org/api/obtaining_api_id)
- [Telegram Bot Developer Terms](https://telegram.org/tos/bot-developers)
- [python-telegram-bot](https://python-telegram-bot.org/)
- [python-telegram-bot `Bot` configuration](https://docs.python-telegram-bot.org/en/v22.6/telegram.bot.html)
- [Telegram upload performance research for qtmedia](../../research/2026-08-21-telegram-upload-performance.md)
- [yt-dlp supported-source review](../../research/2026-08-22-yt-dlp-supported-source-review.md)
- [Docker volumes](https://docs.docker.com/engine/storage/volumes/)
- [Docker Desktop WSL2 best practices](https://docs.docker.com/desktop/features/wsl/best-practices/)
- [yt-dlp 2026.07.04 download options](https://raw.githubusercontent.com/yt-dlp/yt-dlp/2026.07.04/README.md#download-options)
- [Microsoft WSL basic commands](https://learn.microsoft.com/en-us/windows/wsl/basic-commands)
- [Telegram Bot API server source](https://github.com/tdlib/telegram-bot-api)
- [Telegram Bot API server idle-timeout issue](https://github.com/tdlib/telegram-bot-api/issues/224)
- [Telegram Bot API `HttpServer.h`](https://github.com/tdlib/telegram-bot-api/blob/master/telegram-bot-api/HttpServer.h)
- [Reference repository: Local API server setup](https://github.com/cccaaannn/telegram_youtube_downloader/blob/master/docs/API_SERVER.md)
- [Reference repository: configuration](https://github.com/cccaaannn/telegram_youtube_downloader/blob/master/docs/CONFIGURATIONS.md)
- [Reference repository: setup](https://github.com/cccaaannn/telegram_youtube_downloader/blob/master/docs/SETUP.md)
- [Reference repository: Telegram download daemon](https://github.com/alfem/telegram-download-daemon)

## Review gate

Before implementation begins, confirm these decisions:

1. Docker Desktop + WSL2 is the chosen laptop deployment.
2. The bot is limited to private chats during the beta.
3. The Local Bot API server is used for large-file uploads.
4. `python-telegram-bot` is preferred over aiogram for the first implementation.
5. Raw URLs and media are not persisted; bot-originated persistent URL caching is disabled.
6. Successful and failed jobs delete local media through the per-job cleanup lifecycle.
7. The first implementation uses conservative concurrency and size limits.

Once these are accepted, the next artifact should be an implementation plan mapped to the existing repository modules. No production code should be added until that plan is approved.
