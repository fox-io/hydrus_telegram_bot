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
