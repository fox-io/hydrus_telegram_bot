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

## Developer workflows & common commands

- Setup (recommended in a venv):

```bash
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

If any area is unclear or you want the instructions to emphasize other workflows (CI, tests, or deployment containers), tell me which parts and I'll iterate. 
