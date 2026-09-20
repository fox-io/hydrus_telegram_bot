import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.instance_lock import InstanceLock

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


class TestInstanceLock(unittest.TestCase):
    """
    Tests for InstanceLock.

    This replaces a PID file that could not distinguish a live instance from a
    recycled process id, and so could signal an unrelated process.
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
        self.addCleanup(self._stop, proc)
        self.assertEqual("HELD", proc.stdout.readline().strip(), "holder failed to take the lock")
        return proc

    @staticmethod
    def _stop(proc):
        if proc.poll() is None:
            proc.kill()
            proc.wait()

    def test_acquire_succeeds_when_free(self):
        lock = InstanceLock(self.path)
        self.assertTrue(lock.acquire())
        lock.release()

    def test_second_instance_is_refused(self):
        """The whole point: a second bot must not start alongside the first."""
        self._start_holder()
        self.assertFalse(InstanceLock(self.path).acquire())

    def test_holder_pid_is_readable(self):
        proc = self._start_holder()
        self.assertEqual(proc.pid, InstanceLock(self.path).holder_pid())

    def test_killed_holder_leaves_no_stale_lock(self):
        """
        A crash must not block the next start.

        This is the property the PID file could not provide: a leftover file was
        indistinguishable from a live instance, which is what drove the process
        scanning and killing this replaces.
        """
        proc = self._start_holder()
        proc.kill()
        proc.wait()

        lock = InstanceLock(self.path)
        for _ in range(25):
            if lock.acquire():
                break
            time.sleep(0.1)
        else:
            self.fail("lock was still held after the owning process was killed")
        lock.release()

    def test_release_removes_the_lock_file(self):
        lock = InstanceLock(self.path)
        lock.acquire()
        lock.release()
        self.assertFalse(os.path.exists(self.path))

    def test_acquire_is_reentrant_for_the_owner(self):
        """Calling acquire twice in one process must not deadlock or fail."""
        lock = InstanceLock(self.path)
        self.assertTrue(lock.acquire())
        self.assertTrue(lock.acquire())
        lock.release()

    def test_reuses_a_file_left_behind_by_a_dead_process(self):
        Path(self.path).write_text("99999")
        lock = InstanceLock(self.path)
        self.assertTrue(lock.acquire(), "a stale file carries no lock and must not block")
        self.assertEqual(os.getpid(), lock.holder_pid())
        lock.release()

    def test_holder_pid_handles_a_corrupt_file(self):
        Path(self.path).write_text("not-a-pid")
        self.assertIsNone(InstanceLock(self.path).holder_pid())

    def test_holder_pid_handles_a_missing_file(self):
        self.assertIsNone(InstanceLock(self.path).holder_pid())

    def test_release_without_acquire_is_harmless(self):
        InstanceLock(self.path).release()

    def test_context_manager_releases(self):
        with InstanceLock(self.path) as lock:
            self.assertTrue(lock.acquire())
        self.assertFalse(os.path.exists(self.path))

    @unittest.skipIf(os.name == 'nt', "SIGTERM is not deliverable to an unrelated process on Windows")
    def test_terminate_holder_takes_over(self):
        self._start_holder()
        taker = InstanceLock(self.path)
        self.assertFalse(taker.acquire(), "precondition: lock is held")

        self.assertTrue(taker.terminate_holder(signal.SIGTERM, wait_seconds=10))
        self.assertEqual(os.getpid(), taker.holder_pid())
        taker.release()

    def test_terminate_holder_without_a_holder(self):
        self.assertFalse(InstanceLock(self.path).terminate_holder(signal.SIGTERM, wait_seconds=1))


if __name__ == "__main__":
    unittest.main()
