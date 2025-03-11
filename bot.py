from logs import Logs
from hydrus import Hydrus
from telegram import Telegram
from scheduler import Scheduler
from queues import Queues
from config import Config

class HydrusTelegramBot:

    def on_scheduler(self):
        self.queue.load_queue()
        self.hydrus.get_new_hydrus_files()
        self.queue.process_queue()
        self.scheduler.schedule_update(self.on_scheduler)

    def __init__(self):
        # Set up logging
        self.logger = Logs.setup_logger('BOT')

        # Initialize our modules.
        self.config = Config('config.json')
        self.queue = Queues(self.config, 'queue.json')
        self.hydrus = Hydrus(self.config, self.queue)
        self.telegram = Telegram(self.config)
        self.scheduler = Scheduler()
        
        # Queue Manager needs Hydrus and Telegram modules, but they need the Queue Manager too.
        # We pass the references to the Queue Manager now that they are initialized.
        self.queue.set_hydrus(self.hydrus)
        self.queue.set_telegram(self.telegram)

        self.logger.info('HydrusTelegramBot initialized.')


if __name__ == '__main__':
    # Main program loop.
    app = HydrusTelegramBot()
    app.on_scheduler()
    app.scheduler.run()
