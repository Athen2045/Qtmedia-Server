# Telegram bot integration research

Date: 2026-08-18

## Conclusion

Integrating this Python project with a Telegram bot is technically viable. The
existing search and download engines can remain the core service; a Telegram
adapter would translate messages into search/download jobs and send completed
files back to the requesting chat.

The first version should use private-chat URL downloads, long polling, a bounded
job queue, and an explicit supported-domain allowlist. A production deployment
should not expose the current arbitrary-URL downloader directly to untrusted
Telegram users.

## Official Telegram findings

- Create the bot through `@BotFather` with `/newbot`. Telegram asks for a display
  name and a username; the username must be 5–32 characters, use Latin letters,
  numbers, or underscores, and normally end in `bot`. The generated token is a
  bearer credential: anyone who obtains it can control the bot. Sources:
  [Bot Features](https://core.telegram.org/bots/features) and
  [Bots introduction](https://core.telegram.org/bots).
- Telegram provides two mutually exclusive update mechanisms: `getUpdates`
  long polling and HTTPS webhooks. Updates are retained for no more than 24
  hours. Polling is the simplest choice for a Windows-first local deployment;
  webhooks are appropriate when the service has a stable public HTTPS endpoint.
  Source: [Bot API](https://core.telegram.org/bots/api#getting-updates).
- On Telegram's hosted Bot API, a bot can currently send video or document files
  up to 50 MB. The hosted `getFile` path supports downloading files sent to the
  bot up to 20 MB. A local Bot API server removes the download-size limit and
  raises upload support to 2,000 MB. Sources: [sendDocument and sendVideo](https://core.telegram.org/bots/api#sending-files),
  [getFile](https://core.telegram.org/bots/api#getfile), and
  [Using a Local Bot API Server](https://core.telegram.org/bots/api#using-a-local-bot-api-server).
- Sending an already-uploaded file by its Telegram `file_id` avoids re-uploading
  it. For a newly downloaded local file, the bot should upload it as a document
  or video. Source: [Sending Files](https://core.telegram.org/bots/api#sending-files).
- Operational limits include about one message per second in a private chat,
  20 messages per minute in a group, and about 30 broadcast messages per second
  unless paid broadcasts are enabled. A download bot should therefore send a
  small number of status updates and queue work instead of sending progress on
  every download hook. Source: [Bots FAQ](https://core.telegram.org/bots/faq#my-bot-is-hitting-limits-how-do-i-avoid-this).
- Telegram's Bot Platform developer terms require protecting received data,
  minimizing retained data, handling user data securely, avoiding unsolicited
  spam, and keeping hosted content compliant with Telegram's Terms of Service.
  They also prohibit facilitating illegal, pirated, regulated, or questionable
  goods/services and distributing media belonging to unconsenting third parties.
  Source: [Bot Platform Developer Terms](https://telegram.org/tos/bot-developers).
- Telegram's content-licensing terms require legitimate bot operation and
  compliance with copyright restrictions imposed by rightsholders. Telegram's
  general Terms of Service prohibit illegal pornographic content on publicly
  viewable bots and other public surfaces. Sources: [Content Licensing Terms](https://telegram.org/tos/content-licensing)
  and [Telegram Terms of Service](https://telegram.org/tos).

## Fit with this repository

- `Qtmedia/src/qtmedia/search/engine.py` already exposes reusable `search()` and
  `inspect_direct_url()` functions.
- `Qtmedia/src/qtmedia/download/engine.py` exposes `download_video()`, but it
  currently writes to the global `var/downloads/` directory, prints status to
  stdout, and returns only a boolean. A bot adapter needs a structured result
  containing the output path, title, size, and error reason.
- `download_video()` currently relies on `ffmpeg` being on `PATH`, uses yt-dlp,
  and merges to MP4. The bot process must run on a machine with FFmpeg, yt-dlp
  dependencies, source-site network access, and enough temporary disk space.
- The current direct-URL validation accepts unknown HTTP(S) hosts. Before making
  it public, restrict downloads to explicitly supported domains and reject
  private/link-local destinations to reduce SSRF and abuse risk.
- Existing search/download functions are synchronous and include blocking
  network and yt-dlp work. Telegram handlers should run them in a worker thread
  or bounded executor so the bot's update loop remains responsive.

## Recommended implementation stages

1. **Create and configure the bot in Telegram.** In `@BotFather`, run
   `/newbot`, choose the name and username, and store the token in a secret
   environment variable such as `TELEGRAM_BOT_TOKEN`. Never commit it or put it
   in a chat. Set `/setdescription`, `/setabouttext`, and `/setcommands`; use a
   clear command list such as `/start`, `/help`, `/download`, `/search`, and
   `/cancel`. For the first release, keep the bot in private chats and do not
   enable group use unless group behavior and privacy mode are deliberately
   designed.

2. **Add a Telegram dependency and adapter.** For this Python project,
   `python-telegram-bot` is a reasonable maintained wrapper. Its current
   official example uses `ApplicationBuilder().token(...).build()` and
   `run_polling()`. Add a small `telegram_bot` module that registers command and
   text handlers and calls the existing domain services rather than the CLI.
   Source: [python-telegram-bot](https://python-telegram-bot.org/) and
   [Application documentation](https://docs.python-telegram-bot.org/en/latest/telegram.ext.application.html).

3. **Define the first user flow.** A safe MVP flow is:

   - `/start` explains accepted URLs, content-rights responsibility, size
     limits, and retention behavior.
   - User sends one URL in a private chat.
   - Bot validates the URL and supported domain, creates a job, and replies
     "queued".
   - Worker runs metadata inspection/download in a bounded executor.
   - Bot sends one completion message and the file, or a concise failure.
   - Worker deletes temporary/local files after successful upload or after a
     defined failure-retention window.

   Search can be added after direct URL download is reliable. Search results
   should use numbered or inline-keyboard choices rather than the CLI's terminal
   prompts.

4. **Refactor the download boundary.** Add a service-level function that accepts
   a per-job output directory and returns a result object. Keep Rich/terminal
   progress in the CLI layer. The Telegram layer should receive callbacks only
   at coarse milestones (`queued`, `downloading`, `uploading`, `complete`) to
   avoid Telegram rate limits.

5. **Handle Telegram file limits explicitly.** Check the completed file size
   before upload. With the hosted Bot API, reject or offer an external
   authorized link for files over 50 MB; do not silently leave large files on
   disk. If large-file delivery is essential, evaluate operating Telegram's
   local Bot API server and the extra infrastructure/maintenance it requires.
   Sending as a document is the general fallback; send as a video only when the
   resulting MP4 is suitable for Telegram playback.

6. **Add abuse and privacy controls.** Start with an allowlist of source domains,
   per-user cooldowns, a maximum concurrent job count, a maximum download
   duration/size, cancellation, logging without URLs/tokens where possible, and
   an admin-only diagnostic command. Do not store user IDs or URLs longer than
   needed. Add a privacy notice and a deletion policy. Treat every downloaded
   URL and filename as untrusted input.

7. **Choose deployment.** For local testing, run the bot with long polling on
   the same Windows machine as the CLI. For an always-on service, use a VPS or
   server with FFmpeg, persistent disk, process supervision, and outbound
   access to the configured source sites. Move to webhooks only when a public
   HTTPS endpoint and TLS certificate are available; set a webhook secret token
   and verify the `X-Telegram-Bot-Api-Secret-Token` header.

8. **Test before public access.** Test token validation, `/start`, malformed and
   unsupported URLs, concurrent requests, cancellation, yt-dlp failures,
   missing FFmpeg, files below/above Telegram's size limit, cleanup after both
   success and failure, and restart behavior. Keep the bot private until the
   legal/policy review and abuse controls are complete.

## Minimal Telegram setup checklist

1. Open Telegram and message `@BotFather`.
2. Send `/newbot`.
3. Choose a display name.
4. Choose a unique username ending in `bot`.
5. Copy the token into the server's secret environment/configuration store.
6. Configure description, about text, and commands with BotFather.
7. Start the Python bot with long polling.
8. Open `https://t.me/<your_bot_username>` and send `/start`.
9. Confirm the bot can reply, then test one permitted small URL.
10. Only after that choose a hosted deployment and webhook or a local Bot API
    server for larger files.

## Reference repository: `telegram_youtube_downloader`

The referenced project confirms the large-file explanation. Its README links
to an API-server guide and its `docs/API_SERVER.md` says to run a separate
`telegram-bot-api` container, then configure the downloader to use
`http://telegram-bot-api:8081/bot` as its Bot API base URL. The guide states
that this supports uploads up to 2,000 MB and obtains a Telegram `api_id` and
`api_hash` for the local server:
[reference API_SERVER.md](https://github.com/cccaaannn/telegram_youtube_downloader/blob/master/docs/API_SERVER.md).

The reference project also demonstrates several useful product ideas for this
repository:

- It sends `/video <format> <url>` and `/audio <format> <url>` commands and has
  a `/formats` command.
- It supports a default command for bare URL messages.
- Its optional search flow presents YouTube results as buttons.
- It has configurable per-user authorization and claims.
- It passes explicit yt-dlp format selectors and uses FFmpeg postprocessors for
  MP3 and MP4.
- Its configuration includes download duration limits and allowed URL patterns.
  See [CONFIGURATIONS.md](https://github.com/cccaaannn/telegram_youtube_downloader/blob/master/docs/CONFIGURATIONS.md)
  and [SETUP.md](https://github.com/cccaaannn/telegram_youtube_downloader/blob/master/docs/SETUP.md).

This means our proposed quality picker can support large files if we deploy the
bot and local Bot API server together. The relevant architecture is:

```text
Telegram clients
       |
       v
Telegram Bot API datacenters
       |
       v
Local telegram-bot-api container  <--- api_id + api_hash
       |
       v
Our bot process + yt-dlp + FFmpeg
```

The official Bot API still documents the local-server upload limit as 2,000 MB,
not 3 GB. A bot observed sending 3 GB may be using a custom/forked server,
splitting the file, sending a link rather than uploading the file, or using a
user-account/MTProto client rather than the ordinary Bot API. The reference
repository itself documents 2,000 MB, so we should design around 2 GB unless a
separate implementation is deliberately chosen.

For this project, large-file support should be an explicit deployment option:

- **Standard mode:** Telegram-hosted Bot API; enforce a 50 MB upload cap.
- **Large-file mode:** run the official/local `telegram-bot-api` server, provide
  `api_id` and `api_hash`, point the bot library at the local base URL, and
  enforce a conservative application limit below 2 GB based on available disk,
  RAM, bandwidth, and timeout.

The quality buttons should therefore be generated after inspection with a
per-format size estimate, and the bot should reject any selected format that
exceeds the active deployment limit before starting the download.

## Reference repository: `telegram-download-daemon`

This repository uses a different Telegram interface entirely. Its README
explicitly describes it as a “Telegram Daemon (not a bot)”. It uses the
Telethon `TelegramClient`, requires a Telegram `api_id` and `api_hash`, and
performs an interactive phone-number/security-code login that creates a user
session:
[repository README](https://github.com/alfem/telegram-download-daemon).

The script listens to a configured channel and calls Telethon's
`client.download_media(...)` to save incoming Telegram media to local storage.
It is therefore solving the opposite direction from our project: Telegram
channel -> local disk. Its code does not demonstrate a bot uploading a 3 GB
yt-dlp result back to a user; there is no `send_file` upload path in the
download worker. Source:
[telegram-download-daemon.py](https://github.com/alfem/telegram-download-daemon/blob/master/telegram-download-daemon.py).

The important distinction is:

```text
Bot API bot:       receives messages and sends files as a bot
Telethon user:     acts as a logged-in human Telegram account
Local Bot API:     keeps bot identity but moves Bot API processing local
```

A Telethon user account can access Telegram's MTProto file-transfer behavior,
which is why this project can download files larger than the hosted Bot API's
20 MB `getFile` limit. It requires storing a user session and handling phone
login, 2FA, account security, flood limits, and the risk that Telegram may
restrict the account. It is not a drop-in replacement for BotFather-based bot
interaction.

For our URL-downloader use case, there are three possible delivery designs:

1. **Bot API + local Bot API server (recommended):** users interact with a bot;
   yt-dlp downloads locally; the bot uploads up to the documented 2,000 MB local
   server limit.
2. **Hybrid bot + Telethon user account:** the bot receives the request, but a
   separate logged-in user account uploads the result. This may support larger
   transfers, but files appear from the user account, not cleanly from the bot,
   and it creates substantial account-security and policy complexity.
3. **Telethon-only user service:** users interact with a normal Telegram user
   account rather than a BotFather bot. This follows the second repository's
   model but does not meet the desired bot UX as cleanly.

The second repository is useful as evidence that MTProto/user-account
automation is a different path, but it does not invalidate the 50 MB hosted
Bot API limit or the local Bot API server approach. We should not use a personal
Telegram account as an upload workaround unless the user explicitly accepts
that security, identity, and policy trade-off.

## How the recommended large-file deployment works

1. Create the bot with `@BotFather` and keep its bot token as a secret.
2. Create a Telegram API application at
   [`my.telegram.org` → API development tools](https://my.telegram.org/apps).
   This supplies the `api_id` and `api_hash` used by the local Bot API server;
   these credentials are for the API server application and are distinct from
   the bot token. See Telegram's [official API ID instructions](https://core.telegram.org/api/obtaining_api_id).
3. Start the official/local `telegram-bot-api` service with the `api_id` and
   `api_hash`, normally on an internal Docker network and port 8081.
4. Configure the bot library to call the local base URL, for example
   `http://telegram-bot-api:8081/bot`, rather than
   `https://api.telegram.org/bot`.
5. Run the application that receives updates, inspects URLs, downloads with
   yt-dlp/FFmpeg, and calls `sendDocument` or `sendVideo` through the local
   server. The local server handles the Telegram-side upload and raises the
   documented upload capacity to 2,000 MB.
6. Keep both services running and share only the bot username with users. The
   local API server should not be exposed publicly; only the bot process should
   access it over the private network.

The local server does not make yt-dlp downloads faster or eliminate the need for
local disk. A 1.8 GB result may temporarily require several gigabytes of free
space for the source streams, merged output, and upload handling. The bot must
also enforce its own maximum size, duration, concurrency, and timeout limits.
