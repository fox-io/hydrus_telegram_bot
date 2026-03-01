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
    ('wand.image', 'wand'),
    ('requests', 'requests'),
    ('pydantic', 'pydantic'),
]

BINARIES = ['ffmpeg', 'convert']


def check_python_version():
    ok = sys.version_info >= (3, 8)
    print(f"Python >= 3.8: {'OK' if ok else 'FAIL ('+sys.version.split()[0]+')'}")
    return ok


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
