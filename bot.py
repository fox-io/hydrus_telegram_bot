from modules.log_manager import LogManager
from modules.hydrus_manager import HydrusManager
from modules.telegram_manager import TelegramManager
from modules.schedule_manager import ScheduleManager
from modules.queue_manager import QueueManager
from modules.config_manager import ConfigManager
import signal
import time
import sys
from typing import Optional, Callable
import functools
import threading
import requests

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
                delay = initial_delay
                for attempt in range(max_retries):
                    try:
                        return func(*args, **kwargs)
                    except Exception as e:
                        if attempt == max_retries - 1:
                            print(f"Operation failed after {max_retries} attempts: {e}")
                            raise
                        print(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay} seconds...")
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

    def poll_telegram_updates(self):
        """
        Polls Telegram for new updates and processes incoming messages from admins.
        """
        offset = None
        self.logger.info("Starting Telegram polling loop for admin messages.")
        while not self.is_shutting_down:
            try:
                url = f"https://api.telegram.org/bot{self.telegram.token}/getUpdates"
                params = {'timeout': 30, 'offset': offset}
                response = requests.get(url, params=params, timeout=35)
                if response.status_code == 200:
                    data = response.json()
                    for update in data.get('result', []):
                        offset = update['update_id'] + 1
                        message = update.get('message')
                        if message:
                            self.telegram.process_incoming_message(message)
                else:
                    self.logger.error(f"Failed to fetch updates: {response.text}")
            except Exception as e:
                self.logger.error(f"Error in Telegram polling: {e}")
                time.sleep(5)


if __name__ == '__main__':
    # Main program loop.
    app = HydrusTelegramBot()
    # Start Telegram polling in a background thread
    polling_thread = threading.Thread(target=app.poll_telegram_updates, daemon=True)
    polling_thread.start()
    app.on_scheduler()
    app.scheduler.run()
