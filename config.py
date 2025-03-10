from logs import Logs
import json

class Config:
    access_token = ""
    channel = 0
    bot_id = 0
    hydrus_api_key = ""
    queue_tag = ""
    posted_tag = ""
    admins = []
    delay = 60
    timezone = -5
    
    def __init__(self, config_file):
        self.logger = Logs.setup_logger('Config')
        if not config_file:
            self.logger.error('Missing config file argument.')
            return
        self.config_file = config_file
        self.config_data = self.load_config()
        self.logger.info('Config Module initialized.')
    
    def load_config(self):
        # Load the config file.
        try:
            with open('config.json') as config:
                config_data = json.load(config)
                self.access_token = config_data['telegram_access_token']
                self.channel = config_data['telegram_channel']
                self.bot_id = config_data['telegram_bot_id']
                self.hydrus_api_key = config_data['hydrus_api_key']
                self.queue_tag = config_data['queue_tag']
                self.posted_tag = config_data['posted_tag']
                self.admins = config_data['admins']
                self.delay = config_data['delay']
                self.timezone = config_data['timezone']
        except (FileNotFoundError, json.JSONDecodeError):
            self.logger.error("Required file 'config.json' is missing or corrupted.")