# Preflight Check

Run these checks before starting the bot in a new environment.

- [ ] Virtualenv created and activated: `python3 -m venv .venv` + `source .venv/bin/activate`.
- [ ] Python deps installed: `pip install -r requirements.txt`.
- [ ] `config/config.json` exists and has required fields (copy from `config/config.json.example`).
- [ ] `ffmpeg` is in `PATH` (used to convert webm and extract video thumbnails).
- [ ] ImageMagick is installed. It is loaded as a shared library by Wand, not run from `PATH`, so the
      preflight check verifies it by importing `wand.image` rather than looking for a binary.
- [ ] Run automated preflight: `python3 scripts/preflight_check.py` and resolve any warnings/errors.
- [ ] Start bot: `python3 bot.py` and monitor `logs/log.log`.
