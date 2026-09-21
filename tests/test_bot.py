import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock wand before importing bot, which pulls in telegram_manager.
sys.modules.setdefault('wand', MagicMock())
sys.modules.setdefault('wand.image', MagicMock())
sys.modules.setdefault('wand.resource', MagicMock())

import bot  # noqa: E402
from modules.instance_lock import InstanceLock  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

HOLDER = """
import sys, time
sys.path.insert(0, {root!r})
from modules.instance_lock import InstanceLock
lock = InstanceLock({path!r})
if not lock.acquire():
    print("FAILED", flush=True)
    raise SystemExit(1)
print("HELD", flush=True)
time.sleep(60)
"""


class TestParseArgs(unittest.TestCase):
    """Tests for bot.parse_args()"""

    def test_force_defaults_off(self):
        """Taking over a running instance must be opt-in."""
        self.assertFalse(bot.parse_args([]).force)

    def test_force_flag(self):
        self.assertTrue(bot.parse_args(['--force']).force)


class TestAcquireInstanceLock(unittest.TestCase):
    """
    Tests for bot.acquire_instance_lock().

    The behaviour this replaces read a pid out of bot.pid and signalled it without
    checking what it belonged to, so a recycled pid meant killing a bystander.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, 'bot.lock')

    def _start_holder(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", HOLDER.format(root=str(REPO_ROOT), path=self.path)],
            stdout=subprocess.PIPE, text=True,
        )
        self.addCleanup(lambda: (proc.poll() is None) and (proc.kill(), proc.wait()))
        self.assertEqual("HELD", proc.stdout.readline().strip())
        return proc

    def test_starts_when_no_other_instance(self):
        lock = InstanceLock(self.path)
        self.addCleanup(lock.release)
        self.assertTrue(bot.acquire_instance_lock(False, lock))

    def test_refuses_when_another_instance_holds_it(self):
        self._start_holder()
        self.assertFalse(bot.acquire_instance_lock(False, InstanceLock(self.path)))

    def test_refusal_does_not_signal_the_holder(self):
        """Refusing must be inert: the running instance keeps running."""
        proc = self._start_holder()
        bot.acquire_instance_lock(False, InstanceLock(self.path))
        self.assertIsNone(proc.poll(), "the running instance must not be terminated")

    @unittest.skipIf(os.name == 'nt', "SIGTERM is not deliverable to an unrelated process on Windows")
    def test_force_takes_over(self):
        self._start_holder()
        lock = InstanceLock(self.path)
        self.addCleanup(lock.release)
        self.assertTrue(bot.acquire_instance_lock(True, lock))
        self.assertEqual(os.getpid(), lock.holder_pid())


class TestGracefulShutdownReleasesLock(unittest.TestCase):
    """The lock must be released on shutdown so a restart is not blocked."""

    def test_shutdown_releases_the_lock(self):
        app = bot.HydrusTelegramBot.__new__(bot.HydrusTelegramBot)
        app.logger = MagicMock()
        app.is_shutting_down = False
        app.instance_lock = MagicMock()
        app.queue = MagicMock()
        app.queue.queue_loaded = False
        app.telegram = MagicMock()

        with patch.object(bot.sys, 'exit') as exit_:
            app.graceful_shutdown(15, None)

        app.instance_lock.release.assert_called_once()
        exit_.assert_called_once_with(0)

    def test_shutdown_without_a_lock_does_not_crash(self):
        app = bot.HydrusTelegramBot.__new__(bot.HydrusTelegramBot)
        app.logger = MagicMock()
        app.is_shutting_down = False
        app.instance_lock = None
        app.queue = MagicMock()
        app.queue.queue_loaded = False
        app.telegram = MagicMock()

        with patch.object(bot.sys, 'exit'):
            app.graceful_shutdown(15, None)


class TestNoProcessScanningRemains(unittest.TestCase):
    """
    The Windows process scan is gone.

    It shelled out with mangled quoting, matched any command line merely containing
    'bot.py', and used os.kill(pid, 0) as an existence probe, which on Windows
    terminates the process rather than testing for it.
    """

    def test_bot_module_has_no_process_scanning(self):
        source = (REPO_ROOT / 'bot.py').read_text()
        for marker in ('manage_pid_lock', 'Win32_Process', 'taskkill', 'powershell', 'os.kill'):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, source)


if __name__ == "__main__":
    unittest.main()


class TestConfigManagerRequiresAFile(unittest.TestCase):
    """The same half-built-object defect existed in ConfigManager."""

    def test_missing_config_file_argument_raises(self):
        from modules.config_manager import ConfigManager
        with self.assertRaises(ValueError):
            ConfigManager('')


class TestConfigModelRejectsEmptyCredentials(unittest.TestCase):
    """
    Empty credentials are never valid and should fail validation, not later.

    Catching it here means one clear message from the config layer instead of a
    ValueError from TelegramManager or an opaque API rejection from Hydrus.
    """

    @staticmethod
    def _valid():
        return {
            'telegram_access_token': '123:abc', 'telegram_channel': -100,
            'telegram_bot_id': 1, 'hydrus_api_key': 'key', 'queue_tag': 'q',
            'posted_tag': 'p', 'admins': [1], 'delay': 60, 'timezone': 0,
            'max_image_dimension': 10000, 'max_file_size': 10000000, 'log_level': 20,
        }

    def test_valid_config_still_passes(self):
        from modules.config_manager import ConfigModel
        self.assertEqual('123:abc', ConfigModel(**self._valid()).telegram_access_token)

    def test_empty_required_strings_are_rejected(self):
        from pydantic import ValidationError

        from modules.config_manager import ConfigModel
        for field in ('telegram_access_token', 'hydrus_api_key', 'queue_tag', 'posted_tag'):
            with self.subTest(field=field):
                data = self._valid() | {field: ''}
                with self.assertRaises(ValidationError):
                    ConfigModel(**data)


class TestEnvOverrides(unittest.TestCase):
    """
    Tests for apply_env_overrides().

    Lets the Telegram token and Hydrus API key be supplied without ever being
    written to disk, so config/config.json can hold no credentials at all.
    """

    @staticmethod
    def _apply(data, env):
        from modules.config_manager import apply_env_overrides
        return apply_env_overrides(data, env)

    def test_token_is_taken_from_the_environment(self):
        data, applied = self._apply({'telegram_access_token': 'from-file'},
                                    {'HYDRUS_TELEGRAM_BOT_TOKEN': 'from-env'})
        self.assertEqual('from-env', data['telegram_access_token'])
        self.assertEqual(['HYDRUS_TELEGRAM_BOT_TOKEN'], applied)

    def test_hydrus_key_is_taken_from_the_environment(self):
        data, applied = self._apply({}, {'HYDRUS_TELEGRAM_BOT_HYDRUS_API_KEY': 'k'})
        self.assertEqual('k', data['hydrus_api_key'])
        self.assertIn('HYDRUS_TELEGRAM_BOT_HYDRUS_API_KEY', applied)

    def test_file_value_is_kept_when_no_variable_is_set(self):
        data, applied = self._apply({'telegram_access_token': 'from-file'}, {})
        self.assertEqual('from-file', data['telegram_access_token'])
        self.assertEqual([], applied)

    def test_empty_variable_does_not_override(self):
        """An empty variable is a mistake, not an instruction to blank the token."""
        data, _ = self._apply({'telegram_access_token': 'from-file'},
                              {'HYDRUS_TELEGRAM_BOT_TOKEN': ''})
        self.assertEqual('from-file', data['telegram_access_token'])

    def test_only_credentials_are_overridable(self):
        from modules.config_manager import ENV_OVERRIDES
        self.assertEqual({'telegram_access_token', 'hydrus_api_key'}, set(ENV_OVERRIDES))

    def test_config_without_credentials_validates_from_env(self):
        from modules.config_manager import ConfigModel
        base = {
            'telegram_channel': -100, 'telegram_bot_id': 1, 'queue_tag': 'q',
            'posted_tag': 'p', 'admins': [1], 'delay': 60, 'timezone': 0,
            'max_image_dimension': 10000, 'max_file_size': 10000000, 'log_level': 20,
        }
        merged, _ = self._apply(dict(base), {
            'HYDRUS_TELEGRAM_BOT_TOKEN': 'tok',
            'HYDRUS_TELEGRAM_BOT_HYDRUS_API_KEY': 'key',
        })
        self.assertEqual('tok', ConfigModel(**merged).telegram_access_token)


class TestConfigPermissionCheck(unittest.TestCase):
    """The config file holds credentials in plain text, so 0644 exposes them."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, 'config.json')
        Path(self.path).write_text('{}')

    @staticmethod
    def _check(path):
        from modules.config_manager import config_is_readable_by_others
        return config_is_readable_by_others(path)

    @unittest.skipIf(os.name == 'nt', "POSIX mode bits do not describe Windows permissions")
    def test_world_readable_is_flagged(self):
        os.chmod(self.path, 0o644)
        self.assertTrue(self._check(self.path))

    @unittest.skipIf(os.name == 'nt', "POSIX mode bits do not describe Windows permissions")
    def test_group_readable_is_flagged(self):
        os.chmod(self.path, 0o640)
        self.assertTrue(self._check(self.path))

    @unittest.skipIf(os.name == 'nt', "POSIX mode bits do not describe Windows permissions")
    def test_owner_only_is_not_flagged(self):
        os.chmod(self.path, 0o600)
        self.assertFalse(self._check(self.path))

    def test_missing_file_is_not_flagged(self):
        self.assertFalse(self._check(os.path.join(self.tmp, 'nope.json')))
