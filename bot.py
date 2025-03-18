from modules.log_manager import LogManager
from modules.hydrus_manager import HydrusManager
from modules.telegram_manager import TelegramManager
from modules.schedule_manager import ScheduleManager
from modules.queue_manager import QueueManager
from modules.config_manager import ConfigManager

class HydrusTelegramBot:
    """
    HydrusTelegramBot manages the connection between Hydrus Network and a Telegram bot.

    Methods:
        on_scheduler(): Processes scheduled updates, looping indefinitely.
    """

    def on_scheduler(self):
        """
        Processes scheduled updates, looping indefinitely.
        """
        self.queue.load_queue()
        self.hydrus.get_new_hydrus_files()
        self.queue.process_queue()
        self.scheduler.schedule_update(self.on_scheduler)

    def __init__(self):
        """
        Initializes the HydrusTelegramBot object.
        """
        # Set up logging
        self.logger = LogManager.setup_logger('BOT')

        # Initialize our modules.
        self.config = ConfigManager('config.json')
        self.queue = QueueManager(self.config, 'queue.json')
        self.hydrus = HydrusManager(self.config, self.queue)
        self.telegram = TelegramManager(self.config)
        self.scheduler = ScheduleManager(self.config.timezone, self.config.delay)

        # Queue Manager needs Hydrus and Telegram modules, but they need the Queue Manager too.
        # We pass the references to the Queue Manager now that they are initialized.
        self.queue.set_hydrus(self.hydrus)
        self.queue.set_telegram(self.telegram)

        self.logger.debug('HydrusTelegramBot initialized.')


if __name__ == '__main__':
    # Main program loop.
    app = HydrusTelegramBot()
    app.on_scheduler()
    app.scheduler.run()
