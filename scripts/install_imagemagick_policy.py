#!/usr/bin/env python3
"""
Installs the bundled ImageMagick policy.xml system-wide.

This is optional. The bot already loads config/magick/policy.xml itself by setting
MAGICK_CONFIGURE_PATH, so its own ImageMagick usage is covered with no install.
Running this additionally hardens `magick` invoked by hand, by anything else on the
machine, and by the bot if MAGICK_CONFIGURE_PATH is ever overridden.

Note that a system-wide copy lives inside the ImageMagick installation. On Homebrew
that path is version-pinned, so `brew upgrade imagemagick` discards it and this
script must be run again. The bundled copy the bot uses is unaffected by upgrades.

Usage:
    python3 scripts/install_imagemagick_policy.py            # report, change nothing
    python3 scripts/install_imagemagick_policy.py --apply    # install, keeping a backup
    python3 scripts/install_imagemagick_policy.py --revert   # restore the backup
    python3 scripts/install_imagemagick_policy.py --verify   # check what is in force

Exit codes:
    0 - success, or dry run completed
    1 - failed (ImageMagick not found, permission denied, verification failed)
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BUNDLED_POLICY = REPO_ROOT / "config" / "magick" / "policy.xml"
BACKUP_SUFFIX = ".hydrus-bot-backup"

# ImageMagick 7 ships `magick`; 6 only ships `identify`/`convert`.
MAGICK_CANDIDATES = ("magick", "identify")


def find_magick() -> str | None:
    """Returns the name of an ImageMagick CLI on PATH, or None."""
    for name in MAGICK_CANDIDATES:
        path = shutil.which(name)
        if not path:
            continue
        # Windows ships its own convert.exe (FAT to NTFS), so never trust a bare
        # name. Confirm the binary actually identifies itself as ImageMagick.
        try:
            out = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            continue
        if "ImageMagick" in (out.stdout or "") + (out.stderr or ""):
            return path
    return None


def find_system_policy(magick: str) -> Path | None:
    """
    Returns the policy.xml path ImageMagick actually reads.

    `magick -list policy` prints the files it loaded, most specific first. A
    built-in-only install prints no real path, in which case we fall back to the
    configure path so a policy can be installed where it will be picked up.
    """
    try:
        out = subprocess.run([magick, "-list", "policy"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"FAIL: could not run '{magick} -list policy': {e}")
        return None

    for line in (out.stdout or "").splitlines():
        if line.strip().startswith("Path:"):
            value = line.split("Path:", 1)[1].strip()
            if value and value != "[built-in]":
                return Path(value)

    # No policy file loaded yet. Ask where configuration is read from.
    try:
        out = subprocess.run([magick, "-list", "configure"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    for line in (out.stdout or "").splitlines():
        if line.strip().startswith("CONFIGURE_PATH"):
            value = line.split(None, 1)[1].strip()
            if value:
                return Path(value) / "policy.xml"
    return None


def verify(magick: str) -> bool:
    """
    Checks that a denied coder is actually refused.

    Reading the file back is not proof; ImageMagick has to be the one enforcing it.
    """
    try:
        out = subprocess.run(
            [magick, "https://example.invalid/probe.png", "null:"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as e:
        print(f"  could not run the check: {e}")
        return False

    message = (out.stderr or "") + (out.stdout or "")
    if "security policy" in message:
        print("  HTTPS coder is refused by policy. Hardening is in force.")
        return True
    print("  HTTPS coder was NOT refused. The policy is not in force.")
    print(f"  ImageMagick said: {message.strip().splitlines()[0][:120] if message.strip() else '(no output)'}")
    return False


def do_apply(target: Path) -> int:
    backup = target.with_name(target.name + BACKUP_SUFFIX)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not backup.exists():
            shutil.copy2(target, backup)
            print(f"  backed up existing policy to {backup}")
        elif backup.exists():
            print(f"  keeping the original backup already at {backup}")
        shutil.copy2(BUNDLED_POLICY, target)
    except PermissionError:
        print(f"FAIL: permission denied writing {target}")
        if os.name == "nt":
            print("  Re-run from an Administrator PowerShell.")
        else:
            print(f"  Try: sudo {sys.executable} {' '.join(sys.argv)}")
        return 1
    except OSError as e:
        print(f"FAIL: could not write {target}: {e}")
        return 1
    print(f"  installed {BUNDLED_POLICY.name} to {target}")
    return 0


def do_revert(target: Path) -> int:
    backup = target.with_name(target.name + BACKUP_SUFFIX)
    if not backup.exists():
        print(f"FAIL: no backup found at {backup}; nothing to restore.")
        return 1
    try:
        shutil.copy2(backup, target)
        backup.unlink()
    except PermissionError:
        print(f"FAIL: permission denied writing {target}. Re-run elevated.")
        return 1
    except OSError as e:
        print(f"FAIL: could not restore {target}: {e}")
        return 1
    print(f"  restored the original policy to {target}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--apply", action="store_true", help="install the bundled policy, keeping a backup")
    group.add_argument("--revert", action="store_true", help="restore the backed-up policy")
    group.add_argument("--verify", action="store_true", help="only check whether hardening is in force")
    args = parser.parse_args()

    if not BUNDLED_POLICY.is_file():
        print(f"FAIL: bundled policy missing at {BUNDLED_POLICY}")
        return 1

    magick = find_magick()
    if not magick:
        print("FAIL: no ImageMagick CLI found on PATH.")
        print("  Looked for: " + ", ".join(MAGICK_CANDIDATES))
        return 1
    print(f"ImageMagick CLI: {magick}")

    if args.verify:
        print("Checking whether the hardening is in force:")
        return 0 if verify(magick) else 1

    target = find_system_policy(magick)
    if target is None:
        print("FAIL: could not determine where ImageMagick reads policy.xml.")
        print(f"  Check '{magick} -list policy' output manually.")
        return 1
    print(f"System policy path: {target}")

    if args.revert:
        return do_revert(target)

    if not args.apply:
        backup = target.with_name(target.name + BACKUP_SUFFIX)
        print("\nDry run. Nothing was changed. With --apply this would:")
        if target.exists():
            print(f"  1. copy {target}")
            print(f"     to    {backup}")
            print(f"  2. overwrite {target}")
        else:
            print(f"  1. create {target}")
        print(f"     with  {BUNDLED_POLICY}")
        print("\nThe bot does not need this. It already loads the bundled policy itself.")
        return 0

    result = do_apply(target)
    if result != 0:
        return result
    print("Verifying:")
    return 0 if verify(magick) else 1


if __name__ == "__main__":
    sys.exit(main())
