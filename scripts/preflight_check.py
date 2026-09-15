#!/usr/bin/env python3
"""
Preflight checks for hydrus_telegram_bot.

Run this before starting the bot to validate environment, config, binaries and imports.

Usage:
    python3 scripts/preflight_check.py

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""
import json
import os
import sys
import shutil
import subprocess

REQ_KEYS = [
    'admins', 'telegram_access_token', 'telegram_channel', 'telegram_bot_id',
    'hydrus_api_key', 'queue_tag', 'posted_tag', 'delay', 'timezone',
    'max_image_dimension', 'max_file_size', 'log_level'
]

PY_MODULES = [
    ('hydrus_api', 'hydrus_api'),
    ('wand', 'wand'),
    ('requests', 'requests'),
    ('pydantic', 'pydantic'),
]

# Only ffmpeg is invoked as a binary. ImageMagick is used through Wand, which loads
# the shared library directly, so it is checked by check_imagemagick() instead.
BINARIES = ['ffmpeg']

IMAGEMAGICK_HELP = {
    'darwin': "brew install imagemagick",
    'win32': "https://imagemagick.org/script/download.php#windows "
             "(tick 'Install development headers and libraries for C and C++')",
    'linux': "apt install libmagickwand-dev  (or your distro's equivalent)",
}


def check_python_version():
    # requests and urllib3 both declare Requires-Python >= 3.10, and neither is optional.
    ok = sys.version_info >= (3, 10)
    print(f"Python >= 3.10: {'OK' if ok else 'FAIL ('+sys.version.split()[0]+')'}")
    return ok


def check_imagemagick():
    """
    Verifies that Wand can load the ImageMagick shared library.

    The bot never shells out to the ImageMagick CLI, it uses Wand, which loads the
    library through ctypes. Looking for a binary on PATH is therefore the wrong test,
    and on Windows it is actively misleading: C:\\Windows\\System32\\convert.exe is a
    built-in FAT-to-NTFS utility, so checking for 'convert' passes even when
    ImageMagick is not installed at all.

    Importing wand.image is the real test, since that is what triggers the library
    load. Note that wand.version cannot be used for this, as it wraps its own library
    import in try/except and stays importable when ImageMagick is missing.
    """
    try:
        import wand  # noqa: F401
    except ImportError:
        print("ImageMagick: FAIL - the Wand package is not installed.")
        return False

    try:
        import wand.image  # noqa: F401
    except Exception as e:
        print("ImageMagick: FAIL - Wand could not load the ImageMagick library.")
        print(f"  {e}")
        print(f"  Install: {IMAGEMAGICK_HELP.get(sys.platform, 'install ImageMagick for your platform')}")
        return False

    try:
        from wand.version import MAGICK_VERSION
        detail = MAGICK_VERSION.split('https')[0].strip()
    except ImportError:
        detail = 'version unavailable'
    print(f"ImageMagick: OK ({detail})")
    return True


def check_config():
    path = os.path.join('config', 'config.json')
    if not os.path.exists(path):
        print(f"FAIL: Missing config file at {path}. Copy config/config.json.example and edit it.")
        return False
    try:
        with open(path, encoding='utf-8') as f:
            cfg = json.load(f)
    except Exception as e:
        print(f"FAIL: Could not parse {path}: {e}")
        return False

    missing = [k for k in REQ_KEYS if k not in cfg]
    if missing:
        print(f"FAIL: Missing config keys: {missing}")
        return False

    # Basic sanity
    if not isinstance(cfg.get('admins'), list):
        print("FAIL: 'admins' should be a list of Telegram user ids.")
        return False

    print("Config: OK")
    return True


def check_binaries():
    ok = True
    for b in BINARIES:
        path = shutil.which(b)
        if path:
            print(f"Binary '{b}': found at {path}")
        else:
            print(f"Binary '{b}': NOT FOUND in PATH")
            ok = False
    return ok


def check_imports():
    ok = True
    for mod, name in PY_MODULES:
        try:
            __import__(mod)
            print(f"Python package '{name}': OK")
        except Exception as e:
            print(f"Python package '{name}': MISSING or failed to import ({e})")
            ok = False
    return ok


def main():
    print("Running preflight checks...\n")
    checks = []
    checks.append(('python_version', check_python_version()))
    checks.append(('config', check_config()))
    checks.append(('binaries', check_binaries()))
    checks.append(('python_imports', check_imports()))
    checks.append(('imagemagick', check_imagemagick()))

    failed = [name for name, ok in checks if not ok]
    print('\nSummary:')
    if not failed:
        print('All checks passed ✅')
        sys.exit(0)
    else:
        print('Failed checks: ' + ', '.join(failed))
        sys.exit(1)


if __name__ == '__main__':
    main()
