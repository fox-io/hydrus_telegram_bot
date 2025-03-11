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
        self.logger = Logs.setup_logger('BOT')
        self.config = Config('config.json')
        self.queue = Queues(self.config, 'queue.json')
        self.hydrus = Hydrus(self.config, self.queue)
        self.queue.set_hydrus(self.hydrus)
        self.telegram = Telegram(self.config)
        self.queue.set_telegram(self.telegram)
        self.scheduler = Scheduler()
        self.logger.info('HydrusTelegramBot initialized.')


if __name__ == '__main__':
    # Main program loop.
    app = HydrusTelegramBot()
    app.on_scheduler()
    app.scheduler.run()

