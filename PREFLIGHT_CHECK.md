# Preflight Check

Run these checks before starting the bot in a new environment.

- [ ] Virtualenv created and activated: `python3 -m venv .venv` + `source .venv/bin/activate`.
- [ ] Python deps installed: `pip install -r requirements.txt`.
- [ ] `config/config.json` exists and has required fields (copy from `config/config.json.example`).
- [ ] Credentials are protected: either `chmod 600 config/config.json`, or supply
      `HYDRUS_TELEGRAM_BOT_TOKEN` and `HYDRUS_TELEGRAM_BOT_HYDRUS_API_KEY` from the
      environment and leave them out of the file. Preflight warns if the file is
      readable by other accounts.
- [ ] `ffmpeg` is in `PATH` (used to convert webm and extract video thumbnails).
- [ ] ImageMagick is installed. It is loaded as a shared library by Wand, not run from `PATH`, so the
      preflight check verifies it by importing `wand.image` rather than looking for a binary.
- [ ] Run automated preflight: `python3 scripts/preflight_check.py` and resolve any warnings/errors.
- [ ] Start bot: `python3 bot.py` and monitor `logs/log.log`.
- [ ] ImageMagick hardening needs no action: the bot loads `config/magick/policy.xml`
      itself, on every machine, with nothing to install.
- [ ] Optional, only if you also run `magick` by hand on this machine:
      `python3 scripts/install_imagemagick_policy.py` to preview, then `--apply` to
      install the same policy system-wide. See the Hardening section of README.md.
