from modules.log_manager import LogManager
from modules.hydrus_manager import HydrusManager
from modules.telegram_manager import TelegramManager
from modules.schedule_manager import ScheduleManager
from modules.queue_manager import QueueManager
from modules.config_manager import ConfigManager
import signal
import time
import sys
import os
import logging
import logging.handlers
from typing import Optional, Callable
import functools
import threading
import requests
import subprocess

# Monkey patch for Windows file locking issue with RotatingFileHandler
if os.name == 'nt':
    def robust_rotate(self, source, dest):
        for i in range(10):
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

def manage_pid_lock():
    """
    Ensures only one instance of the bot is running by using a PID file.
    If a previous instance is found running, it is terminated to release resources.
    Also scans for zombie 'bot.py' processes on Windows to release file locks.
    """
    pid_file = 'bot.pid'
    if os.path.exists(pid_file):
        try:
            with open(pid_file, 'r') as f:
                content = f.read().strip()
                old_pid = int(content) if content else None
            
            if old_pid:
                try:
                    os.kill(old_pid, 0)
                    # Process exists
                    print(f"Previous instance (PID {old_pid}) is running. Terminating...")
                    os.kill(old_pid, signal.SIGTERM)
                    time.sleep(2) # Wait for handles to release
                except OSError:
                    # Process does not exist
                    print(f"Found stale PID file for PID {old_pid}. Cleaning up.")
        except (ValueError, OSError) as e:
            print(f"Error checking PID file: {e}")
        
        if os.path.exists(pid_file):
            try:
                os.remove(pid_file)
            except OSError:
                pass

    # Windows-specific: Scan for other python processes running this script
    # This handles the case where no PID file exists (crash/first run) but a process is locked.
    if os.name == 'nt':
        try:
            current_pid = os.getpid()
            # Filter for python processes to avoid false positives
            cmd = f'wmic process where "name=\'python.exe\' and processid!={current_pid}" get commandline,processid'
            output = subprocess.check_output(cmd, shell=True).decode('utf-8', errors='ignore')
            
            script_name = os.path.basename(__file__) # usually 'bot.py'
            
            for line in output.splitlines():
                if script_name in line:
                    # Extract PID (last element in the line)
                    parts = line.strip().rsplit(None, 1)
                    if len(parts) >= 2 and parts[1].isdigit():
                        found_pid = int(parts[1])
                        if found_pid != current_pid:
                            print(f"Found zombie process {found_pid} running {script_name}. Terminating...")
                            try:
                                os.kill(found_pid, signal.SIGTERM)
                                time.sleep(1) # Give it a moment to release handles
                            except OSError:
                                pass

                            # Verify if process is still running and force kill if needed
                            try:
                                os.kill(found_pid, 0)
                                print(f"Process {found_pid} still running. Forcing exit...")
                                subprocess.run(['taskkill', '/F', '/PID', str(found_pid)], 
                                             stdout=subprocess.DEVNULL, 
                                             stderr=subprocess.DEVNULL)
                                time.sleep(1)
                            except OSError:
                                print(f"Process {found_pid} successfully terminated.")
        except subprocess.CalledProcessError:
            # No other python processes found
            pass
        except Exception as e:
            print(f"Warning: Could not scan for zombie processes: {e}")

    try:
        with open(pid_file, 'w') as f:
            f.write(str(os.getpid()))
    except OSError as e:
        print(f"Could not write PID file: {e}")

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
                            if logger: logger.error(f"Operation failed after {max_retries} attempts: {e}")
                            raise
                        if logger: logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay} seconds...")
                        time.sleep(delay)
                        delay = min(delay * 2, max_delay)
                return None
            return wrapper
        return decorator

    def graceful_shutdown(self, signum: Optional[int] = None, frame: Optional[object] = None):
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
            
            # Clean up PID file
            if os.path.exists('bot.pid'):
                try:
                    os.remove('bot.pid')
                except OSError:
                    pass

            self.logger.info("Shutdown complete. Exiting...")
            sys.exit(0)
        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}")
            sys.exit(1)

    @retry_with_backoff(max_retries=3, initial_delay=1.0, max_delay=60.0)
    def on_scheduler(self):
        """
        Processes scheduled updates, looping indefinitely.

        Raises:
            Exception: An error occurred during the update process
        """
        if self.is_shutting_down:
            return

        try:
            self.queue.load_queue()
            self.hydrus.get_new_hydrus_files()
            self.queue.process_queue()
            self.scheduler.schedule_update(self.on_scheduler)
        except Exception as e:
            self.logger.error(f"An error occurred during the update process: {e}")
            # Don't re-raise the exception to allow the scheduler to continue
            # The retry decorator will handle retrying the operation




if __name__ == '__main__':
    # Ensure single instance and unlock files if necessary
    manage_pid_lock()

    # Main program loop.
    app = HydrusTelegramBot()
    # Start Telegram polling in a background thread
    polling_thread = threading.Thread(target=app.telegram.poll_telegram_updates, args=(lambda: app.is_shutting_down,), daemon=True)
    polling_thread.start()
    app.on_scheduler()
    app.scheduler.run()
