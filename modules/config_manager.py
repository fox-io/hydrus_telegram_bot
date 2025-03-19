from pydantic import BaseModel, Field, ValidationError
from modules.log_manager import LogManager
import json

class ConfigModel(BaseModel):
    """
    ConfigModel is a Pydantic model for the configuration settings.
    """
    telegram_access_token: str = Field(..., title='Telegram Bot Access Token', description='The Telegram bot access token.')
    telegram_channel: int = Field(..., title='Telegram Channel ID', description='The Telegram channel ID.')
    telegram_bot_id: int = Field(..., title='Telegram Bot ID', description='The Telegram bot ID.')
    hydrus_api_key: str = Field(..., title='Hydrus API Key', description='The Hydrus API key.')
    queue_tag: str = Field(..., title='Queue Tag', description='The tag to use for searching Hydrus for files to queue.')
    posted_tag: str = Field(..., title='Posted Tag', description='The tag to use for marking files as posted in Hydrus.')
    admins: list[int] = Field(..., title='Admins', description='A list of Telegram user IDs that are bot admins.')
    delay: int = Field(..., title='Delay', description='The delay between updates in minutes.')
    timezone: int = Field(..., title='Timezone', description='The timezone offset in hours.')

class ConfigManager:
    """
    ConfigManager handles loading and storing configuration settings for the bot.

    Attributes:
        config_file (str): The name of the configuration file to load.
        config_data (ConfigModel): The configuration settings.

    Methods:
        load_config(): Loads the configuration settings from the config file.
    """

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

    def load_config(self) -> ConfigModel:
        """
        Loads the configuration settings from the config file.

        Returns:
            ConfigModel: The configuration settings

        Raises:
            FileNotFoundError: The config file is missing.
            json.JSONDecodeError: The config file is corrupted.
            AttributeError: The config file is missing required values.
        """
        try:
            with open('config/' + self.config_file) as config:
                config_data = json.load(config)
                return ConfigModel(**config_data)
        except (FileNotFoundError, json.JSONDecodeError):
            self.logger.error("Required file 'config.json' is missing or corrupted. Create a copy of config/config.json.example as config/config.json and provide values matching your environment.")
            # Cannot continue.
            exit(1)
        except ValidationError as e:
            self.logger.error(f"Configuration validation error: {e}")
            # Cannot continue.
            exit(1)