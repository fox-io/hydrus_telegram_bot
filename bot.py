import argparse
import functools
import logging
import logging.handlers
import os
import signal
import sys
import threading
import time
from collections.abc import Callable

from modules.config_manager import ConfigManager
from modules.hydrus_manager import HydrusManager
from modules.instance_lock import InstanceLock
from modules.log_manager import LogManager
from modules.queue_manager import QueueManager
from modules.schedule_manager import ScheduleManager
from modules.telegram_manager import TelegramManager

# Monkey patch for Windows file locking issue with RotatingFileHandler
if os.name == 'nt':
    def robust_rotate(self, source, dest):
        for _ in range(10):
            try:
                if os.path.exists(dest):
                    os.remove(dest)
                os.rename(source, dest)
                return
            except (PermissionError, OSError):
                time.sleep(0.1)
        # Final attempt
        if os.path.exists(dest):
            os.remove(dest)
        os.rename(source, dest)

    logging.handlers.RotatingFileHandler.rotate = robust_rotate

class HydrusTelegramBot:
    """
    HydrusTelegramBot manages the connection between Hydrus Network and a Telegram bot.

    Methods:
        on_scheduler(): Processes scheduled updates, looping indefinitely.
        graceful_shutdown(): Handles graceful shutdown of the bot.
        retry_with_backoff(): Decorator for retrying operations with exponential backoff.
    """

    def __init__(self):
        """
        Initializes the HydrusTelegramBot object.
        """
        # Set up logging
        self.logger = LogManager.setup_logger('BOT')
        self.is_shutting_down = False
        # Set by the entry point once the single-instance lock is held.
        self.instance_lock = None

        # Initialize our modules.
        self.config = ConfigManager('config.json')
        self.queue = QueueManager(self.config, 'queue.json')
        self.hydrus = HydrusManager(self.config, self.queue)
        self.telegram = TelegramManager(self.config)
        self.telegram.send_message("Bot is starting.")
        self.scheduler = ScheduleManager(self.config.config_data.timezone, self.config.config_data.delay)

        # Queue Manager needs Hydrus and Telegram modules, but they need the Queue Manager too.
        # We pass the references to the Queue Manager now that they are initialized.
        self.queue.set_hydrus(self.hydrus)
        self.queue.set_telegram(self.telegram)

        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.graceful_shutdown)
        signal.signal(signal.SIGTERM, self.graceful_shutdown)

        self.logger.debug('HydrusTelegramBot initialized.')

        # Set user configured log level preference.
        LogManager.set_level(self.config.config_data.log_level)

    @staticmethod
    def retry_with_backoff(max_retries: int = 3, initial_delay: float = 1.0, max_delay: float = 60.0):
        """
        Decorator for retrying operations with exponential backoff.

        Args:
            max_retries (int): Maximum number of retry attempts.
            initial_delay (float): Initial delay between retries in seconds.
            max_delay (float): Maximum delay between retries in seconds.

        Returns:
            Callable: Decorated function with retry logic.
        """
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                # Attempt to retrieve the logger from the instance (args[0])
                logger = getattr(args[0], 'logger', None) if args else logging.getLogger('BOT')

                delay = initial_delay
                for attempt in range(max_retries):
                    try:
                        return func(*args, **kwargs)
                    except Exception as e:
                        if attempt == max_retries - 1:
                            if logger:
                                logger.error(f"Operation failed after {max_retries} attempts: {e}")
                            raise
                        if logger:
                            logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay} seconds...")
                        time.sleep(delay)
                        delay = min(delay * 2, max_delay)
                return None
            return wrapper
        return decorator

    def graceful_shutdown(self, signum: int | None = None, frame: object | None = None):
        """
        Handles graceful shutdown of the bot.

        Args:
            signum (int, optional): Signal number.
            frame (object, optional): Current stack frame.
        """
        if self.is_shutting_down:
            return

        self.is_shutting_down = True
        self.logger.info(f"Received shutdown signal {signum}. Initiating graceful shutdown...")

        try:
            # Save any pending queue data
            if hasattr(self, 'queue') and self.queue.queue_loaded:
                self.queue.save_queue()

            # Notify admins about shutdown
            if hasattr(self, 'telegram'):
                self.telegram.send_message("Bot is shutting down gracefully.")

            # Release the single-instance lock so a restart can take over at once.
            if self.instance_lock is not None:
                self.instance_lock.release()

            self.logger.info("Shutdown complete. Exiting...")
            sys.exit(0)
        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}")
            sys.exit(1)

    @retry_with_backoff(max_retries=3, initial_delay=1.0, max_delay=60.0)
    def _run_update(self):
        """ Runs a single update cycle with retry logic. """
        if self.is_shutting_down:
            return
        self.queue.load_queue()
        self.hydrus.get_new_hydrus_files()
        self.queue.process_queue()

    def on_scheduler(self):
        """
        Processes scheduled updates, looping indefinitely.

        Raises:
            Exception: An error occurred during the update process
        """
        if self.is_shutting_down:
            return

        try:
            self._run_update()
        except Exception as e:
            self.logger.error(f"An error occurred during the update process: {e}")
        finally:
            if not self.is_shutting_down:
                # Always schedule the next run, even after failures.
                self.scheduler.schedule_update(self.on_scheduler)


def parse_args(argv=None):
    """Parses command line arguments for the entry point."""
    parser = argparse.ArgumentParser(description="Post images from Hydrus Network to a Telegram channel.")
    parser.add_argument(
        '--force', action='store_true',
        help="Ask an already-running instance to shut down and take over from it.",
    )
    return parser.parse_args(argv)


def acquire_instance_lock(force: bool, lock: InstanceLock) -> bool:
    """
    Takes the single-instance lock, optionally displacing a running instance.

    Args:
        force (bool): Ask the current holder to exit rather than refusing to start.
        lock (InstanceLock): The lock to acquire.

    Returns:
        bool: True if this process may proceed.

    Note:
        Refusing is the default because the previous behaviour, silently killing
        whatever process id was written in bot.pid, could terminate an unrelated
        process that had reused that id. Use --force for the old take-over
        behaviour; it is safe now because holding the lock proves the recorded pid
        belongs to a live instance.
    """
    if lock.acquire():
        return True

    holder = lock.holder_pid()
    if not force:
        print(f"Another instance is already running (pid {holder}). "
              f"Stop it first, or start with --force to take over.")
        return False

    print(f"Asking the running instance (pid {holder}) to shut down...")
    if lock.terminate_holder(signal.SIGTERM):
        print("Took over the lock.")
        return True

    print(f"Instance {holder} did not release the lock. Not starting.")
    return False


if __name__ == '__main__':
    args = parse_args()

    # Ensure only one instance runs against this directory.
    instance_lock = InstanceLock('bot.lock')
    if not acquire_instance_lock(args.force, instance_lock):
        sys.exit(1)

    try:
        # Main program loop.
        app = HydrusTelegramBot()
        app.instance_lock = instance_lock
        # Start Telegram polling in a background thread
        polling_thread = threading.Thread(target=app.telegram.poll_telegram_updates, args=(lambda: app.is_shutting_down,), daemon=True)
        polling_thread.start()
        app.on_scheduler()
        app.scheduler.run()
    finally:
        instance_lock.release()
