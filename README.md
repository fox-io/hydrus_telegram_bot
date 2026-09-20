# Hydrus Telegram Bot

## About

Posts images to a Telegram channel from Hydrus Network client based on a target tag. This is a personal project that started as a forked repository. Not much left of the original. It has come a long way! 

I am personally running this bot from a Windows 11 system (For better Hydrus support/performance). Changing the platform may require modifying things.

Currently supports image formats such as jpg and png. webp is partially supported. Video support is currently limited to webm (you need ffmpeg binaries installed) and mp4. Some other media formats may be supported as well. YMMV.

## Quick Context

- Entrypoint: `bot.py` — constructs `HydrusTelegramBot` and starts scheduler + Telegram polling thread.
- Managers live in `modules/` and follow a `*manager.py` pattern: `ConfigManager`, `QueueManager`, `HydrusManager`, `TelegramManager`, `ScheduleManager`, `FileManager`, `LogManager`.
- Configuration is a Pydantic model in `modules/config_manager.py` and loaded from `config/config.json` (copy `config.json.example`).
- Queue persistence: `queue/queue.json` and files stored under `queue/` (binary blobs named by hash+ext).

## High-level architecture (how pieces fit)

- `HydrusManager` talks to Hydrus via `hydrus-api` and discovers files by `queue_tag` (configured). It downloads file content and metadata and hands items to `QueueManager`.
- `QueueManager` stores file blobs in `queue/` and JSON references in `queue/queue.json`. It selects a random queued item and coordinates posting and cleanup.
- `TelegramManager` composes captions/buttons, resizes images (via Wand/ImageMagick), uploads photos/videos to Telegram, and sends admin messages.
- `ScheduleManager` schedules periodic runs (uses `sched`). `bot.py` calls `on_scheduler()` which loads the queue, asks Hydrus for new files, processes queue and re-schedules.
- `LogManager` sets up colored console output and a rotating file `logs/log.log` for troubleshooting.

## Important project-specific conventions

- Module naming: each major component is a `*manager.py` and exposes methods used by `bot.py` — keep changes contained to the relevant manager.
- Config validation: use `ConfigModel` in `modules/config_manager.py`. Invalid or missing `config/config.json` causes the process to `exit(1)` — update carefully.
- Queue JSON shape: `{'queue': [ { 'path': '<hash><ext>', 'file_id': <int>, 'sauce': '...', 'creator': '...', 'title': '...', 'character': '...', 'failures': <int> }, ... ]}`. Only `path` and `file_id` are always present; the metadata keys are omitted when the tag is absent, and `failures` appears once a send has failed. Use `FileManager.operation(filename, mode, payload)` for safe read/write.
- Hydrus tags: code expects a nested downloader-tags structure: `downloader_tags -> storage_tags -> '0' -> [tags]`. Tag parsing looks for `creator:`, `title:`, `character:` prefixes — changes to Hydrus downloader tagging can break metadata extraction.
- File naming: saved as `<hash><ext>` in `queue/`. WebM handling converts to MP4 using `ffmpeg` and generates a thumbnail `<file>.jpg`.

## External dependencies & integration points

- Hydrus: enable Hydrus Client API and provide `hydrus_api_key` in `config/config.json`.
- Telegram: `telegram_access_token`, `telegram_channel`, and `admins` are required.
- Binary deps: `ffmpeg` for webm→mp4 conversion must be on `PATH`. ImageMagick must be installed for image transforms, but is loaded as a shared library by Wand rather than invoked from `PATH`.
- Python packages: listed in `requirements.txt` (install via `pip install -r requirements.txt`). Key packages: `hydrus-api`, `Wand`, `requests`, `pydantic`.

## Hardening

Queued files are downloaded from the internet, so ImageMagick and `ffmpeg` decode
attacker-influenced input. Two layers guard that:

- **Resource limits, applied automatically.** The bot bounds ImageMagick's memory,
  map, disk, area, time and maximum source dimensions at startup, and bounds every
  `ffmpeg` invocation with a timeout. ImageMagick ships with `time` and `disk`
  effectively unlimited, which makes decompression bombs cheap. Tunable via
  `imagemagick_memory_limit_mb`, `imagemagick_time_limit_seconds`,
  `imagemagick_max_source_dimension` and `ffmpeg_timeout_seconds`.
- **A bundled `policy.xml`, loaded automatically.** Resource limits do nothing about
  ImageMagick's coder and delegate handling, which is the class with a history of
  remote code execution and SSRF. Without a policy, ImageMagick will genuinely make
  an outbound HTTP request for an image that asks it to. The bot points
  `MAGICK_CONFIGURE_PATH` at `config/magick/` before loading Wand, so
  `config/magick/policy.xml` applies on every machine with nothing to install and
  nothing to redo after an ImageMagick upgrade. Set `MAGICK_CONFIGURE_PATH`
  yourself to override it.

### Optional: installing the policy system-wide

**You do not need to do this.** The bot loads `config/magick/policy.xml` itself, so
everything the bot decodes is already covered on every machine, including a fresh
clone by a new user. This section is about hardening ImageMagick *outside* the bot.

`scripts/install_imagemagick_policy.py` copies the bundled policy over your
ImageMagick installation's own `policy.xml`, keeping a backup.

**When it is worth running:**

- You also run `magick` or `convert` by hand on the same machine, on files from the
  internet. The bot's `MAGICK_CONFIGURE_PATH` only applies to the bot's own process.
- Other software on the machine uses ImageMagick and you want one hardened policy
  covering all of it.
- You want defence in depth, so the hardening still applies if
  `MAGICK_CONFIGURE_PATH` is ever overridden or the bundled file goes missing.

**When to skip it:** you only ever touch ImageMagick through this bot. That is the
common case, and the bundled policy already handles it.

```bash
python3 scripts/install_imagemagick_policy.py            # dry run, changes nothing
python3 scripts/install_imagemagick_policy.py --apply    # install, keeping a backup
python3 scripts/install_imagemagick_policy.py --verify   # is hardening actually in force?
python3 scripts/install_imagemagick_policy.py --revert   # restore the backup
```

The script finds the real `policy.xml` via `magick -list policy` rather than guessing
a path, and after installing it verifies the result by confirming ImageMagick
actually refuses a denied coder. Writing to the ImageMagick install usually needs
elevation: `sudo` on macOS and Linux, an Administrator PowerShell on Windows.

Two caveats worth knowing:

- A system-wide copy lives **inside the ImageMagick installation**, and on Homebrew
  that path is version-pinned (`.../Cellar/imagemagick/7.1.2-31/etc/...`). A
  `brew upgrade imagemagick` discards it and you must run the script again. The
  bundled copy the bot uses is in this repository and is never affected by upgrades.
- The policy denies the PDF, PostScript and scripting coders. That is correct for
  this bot, but if other software on the machine legitimately needs ImageMagick to
  read PDFs, installing it system-wide will break that. Use `--revert` if so.


## Developer workflows & common commands

- Setup (recommended in a venv):

```bash
git clone https://github.com/fox-io/hydrus_telegram_bot.git
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config/config.json.example config/config.json
# edit config/config.json
```

- Run the bot locally:

```bash
python3 bot.py
```

Only one instance may run per directory, enforced with an OS-level lock on
`bot.lock`. Starting a second one refuses rather than killing the first:

```bash
python3 bot.py --force   # ask the running instance to stop, then take over
```

The lock cannot go stale: the kernel releases it if the bot crashes or is killed,
so a leftover `bot.lock` never blocks a restart.

- Run unit tests:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

- Logs: `logs/log.log` (rotating) and colored console output from `LogManager`.

## Debugging tips & gotchas

- If `bot.py` exits immediately, check `config/config.json`. `ConfigManager` aborts on missing/invalid config.
- Hydrus connectivity: `HydrusManager.check_hydrus_permissions()` logs a warning if Hydrus isn't reachable — you can run the bot without Hydrus but no files will be queued.
- Queue troubleshooting: inspect `queue/queue.json` and `queue/` files directly. To simulate a queued image, drop a file in `queue/` and append an object to the JSON with `{'path': '<filename>'}`.
- Tag extraction is fragile: the code expects `downloader_tags['storage_tags']['0']` to exist. If downloader tool output changes, metadata extraction will produce empty `creator/title/character` fields.
- Media size/dimensions: `TelegramManager.reduce_image_size()` enforces `max_image_dimension` and `max_file_size` from `config.json`.

## Code change examples

- To change posting frequency: edit `config/config.json` -> `delay` (minutes). `ScheduleManager` will schedule next runs using that value.
- To tune failure handling: `max_send_failures` (default 3) is how many runs a file may fail to send before it is dropped from the queue and tagged `failed_tag` (default `failed:telegram`) in Hydrus. `max_post_attempts` (default 10) is how many different files a single run will try before giving up, so one unsendable file does not consume the run. All three are optional and defaulted.
- To add a new admin command handler: extend `TelegramManager.process_incoming_message()` and add logic guarded by `if user_id in self.config.admins:`.
- To alter queue selection strategy: modify `QueueManager.process_queue()` (currently chooses a random index via `random.randint`).

## Where to look for examples

- Entrypoint and orchestration: `bot.py`
- Telegram upload & caption logic: `modules/telegram_manager.py`
- Hydrus API integration and tag handling: `modules/hydrus_manager.py`
- Queue lifecycle and file management: `modules/queue_manager.py`, `modules/file_manager.py`
- Config model and validation: `modules/config_manager.py`
- Logging: `modules/log_manager.py`