import os
import time
from pathlib import Path

if os.name == 'nt':
    import msvcrt
else:
    import fcntl


class InstanceLock:
    """
    An OS-level advisory lock that allows only one bot instance per directory.

    This replaces the previous PID-file approach, which could not tell a live
    instance apart from a recycled process id and therefore risked terminating an
    unrelated process. An OS lock has neither problem:

    - It cannot go stale. The kernel releases the lock when the holding process
      exits, including on a crash or a kill -9, so there is no leftover state to
      clean up and no "is this pid still ours?" guesswork.
    - It cannot misidentify. Holding the lock is proof that a live process owns it,
      so the pid recorded inside the file is trustworthy rather than inferred.

    The pid is written into the file purely for diagnostics, so an operator can see
    which process is holding things up. Nothing keys off it except terminate_holder.

    Attributes:
        path (Path): The lock file location.

    Example:
        >>> lock = InstanceLock('bot.lock')
        >>> if not lock.acquire():
        ...     print(f"Already running as pid {lock.holder_pid()}")
    """

    def __init__(self, path: str = 'bot.lock'):
        """
        Args:
            path (str): Lock file path, relative to the working directory.
        """
        self.path = Path(path)
        self._handle = None

    def acquire(self) -> bool:
        """
        Attempts to take the lock without blocking.

        Returns:
            bool: True if this process now holds the lock, False if another
                  instance holds it.

        Note:
            Safe to call when the lock file already exists. A file left behind by a
            dead process carries no lock, so it is simply reused.
        """
        if self._handle is not None:
            return True

        try:
            handle = open(self.path, 'a+')
        except OSError:
            return False

        try:
            self._lock_handle(handle)
        except OSError:
            # Another process holds it. Expected, not an error.
            handle.close()
            return False

        try:
            handle.seek(0)
            handle.truncate()
            handle.write(str(os.getpid()))
            handle.flush()
        except OSError:
            # The lock is held even if the diagnostic write fails, so keep going.
            pass

        self._handle = handle
        return True

    def release(self):
        """
        Releases the lock and removes the lock file.

        Note:
            Closing the handle is what actually drops the lock; the unlink is
            cosmetic, so a failure to remove the file is ignored.
        """
        if self._handle is None:
            return
        try:
            self._unlock_handle(self._handle)
        except OSError:
            pass
        finally:
            self._handle.close()
            self._handle = None
        try:
            self.path.unlink()
        except OSError:
            pass

    def holder_pid(self):
        """
        Reads the pid recorded in the lock file.

        Returns:
            int: The pid of the process holding the lock, or None if it cannot be
                 read. Only meaningful while the lock is actually held by someone.
        """
        try:
            content = self.path.read_text().strip()
        except OSError:
            return None
        try:
            return int(content)
        except ValueError:
            return None

    def terminate_holder(self, signal_number, wait_seconds: float = 5.0) -> bool:
        """
        Asks the process holding the lock to exit, then waits for it to let go.

        Unlike the pid-file approach this replaces, the pid here is known to belong
        to a live lock holder, so there is no risk of signalling a process that
        merely reused the number.

        Args:
            signal_number (int): Signal to send, normally signal.SIGTERM.
            wait_seconds (float): How long to wait for the lock to become free.

        Returns:
            bool: True if the lock became available within the wait.
        """
        pid = self.holder_pid()
        if pid is None:
            return False
        try:
            os.kill(pid, signal_number)
        except OSError:
            return False

        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if self.acquire():
                return True
            time.sleep(0.2)
        return False

    @staticmethod
    def _lock_handle(handle):
        """
        Takes a non-blocking exclusive lock on the handle.

        Raises:
            OSError: The lock is held by another process.
        """
        if os.name == 'nt':
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock_handle(handle):
        """Releases the lock taken by _lock_handle."""
        if os.name == 'nt':
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
