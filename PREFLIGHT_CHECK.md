# Preflight Check

Run these checks before starting the bot in a new environment.

- [ ] Virtualenv created and activated: `python3 -m venv .venv` + `source .venv/bin/activate`.
- [ ] Python deps installed: `pip install -r requirements.txt`.
- [ ] `config/config.json` exists and has required fields (copy from `config/config.json.example`).
- [ ] `ffmpeg` and ImageMagick (`convert`, `magick`, `wand`) are in `PATH` if you plan to process webm/images.
- [ ] Run automated preflight: `python3 scripts/preflight_check.py` and resolve any warnings/errors.
- [ ] Start bot: `python3 bot.py` and monitor `logs/log.log`.
