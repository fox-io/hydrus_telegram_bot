from modules.log_manager import LogManager
import json

class ConfigManager:
    """
    ConfigManager handles loading and storing configuration settings for the bot.

    Attributes:
        access_token (str): The Telegram bot access token.
        channel (int): The Telegram channel ID.
        bot_id (int): The Telegram bot ID.
        hydrus_api_key (str): The Hydrus API key.
        queue_tag (str): The tag to use for searching Hydrus for files to queue.
        posted_tag (str): The tag to use for marking files as posted in Hydrus.
        admins (list): A list of Telegram user IDs that are bot admins.
        delay (int): The delay between updates in minutes.
        timezone (int): The timezone offset in hours.

    Methods:
        load_config(): Loads the configuration settings from the config file.
    """
    access_token = ""
    channel = 0
    bot_id = 0
    hydrus_api_key = ""
    queue_tag = ""
    posted_tag = ""
    admins = []
    delay = None
    timezone = None

    def __init__(self, config_file):
        """
        Initializes the ConfigManager object.

        Args:
            config_file (str): The name of the configuration file to load.
        """
        self.logger = LogManager.setup_logger('CON')
        if not config_file:
            self.logger.error('Missing config file argument.')
            return
        self.config_file = config_file
        self.config_data = self.load_config()
        self.logger.debug('Config Module initialized.')

    def load_config(self):
        """
        Loads the configuration settings from the config file.

        Returns:
            dict: The configuration

        Raises:
            FileNotFoundError: The config file is missing.
            json.JSONDecodeError: The config file is corrupted.
            AttributeError: The config file is missing required values.
        """
        try:
            with open('config/' + self.config_file) as config:
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
        except (FileNotFoundError, json.JSONDecodeError, AttributeError):
            self.logger.error("Required file 'config.json' is missing or corrupted. Create a copy of config/config.json.example as config/config.json and provide values matching your environment.")
            # Cannot continue.
            exit(1)