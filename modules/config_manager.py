from pydantic import BaseModel, Field, ValidationError
from modules.log_manager import LogManager
import json

class ConfigModel(BaseModel):
    """
    Pydantic model for validating and managing bot configuration settings.

    This model defines the structure and validation rules for the bot's configuration.
    Each field includes a title and description for better documentation and error messages.

    Attributes:
        telegram_access_token (str): The Telegram bot access token.
        telegram_channel (int): The Telegram channel ID where the bot will post.
        telegram_bot_id (int): The unique identifier for the Telegram bot.
        hydrus_api_key (str): The API key for accessing the Hydrus Network client.
        queue_tag (str): The tag used to identify files to be queued in Hydrus.
        posted_tag (str): The tag used to mark files as posted in Hydrus.
        admins (list[int]): List of Telegram user IDs with admin privileges.
        delay (int): The delay between updates in minutes.
        timezone (int): The timezone offset in hours from UTC.

    Example:
        >>> config = ConfigModel(
        ...     telegram_access_token="123:abc",
        ...     telegram_channel=-100123456789,
        ...     telegram_bot_id=123456789,
        ...     hydrus_api_key="abc123",
        ...     queue_tag="to_post",
        ...     posted_tag="posted",
        ...     admins=[123456789],
        ...     delay=60,
        ...     timezone=0,
        ...     max_image_dimension=10000,
        ...     max_file_size=10000000
        ... )
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
    max_image_dimension: int = Field(..., title='Max Image Dimension', description='The maximum dimension of an image in pixels.')
    max_file_size: int = Field(..., title='Max File Size', description='The maximum size of a file in bytes.')

class ConfigManager:
    """
    Manages the loading and validation of bot configuration settings.

    This class handles the loading of configuration settings from a JSON file,
    validates them against the ConfigModel, and provides access to the validated
    configuration throughout the application.

    Attributes:
        config_file (str): The name of the configuration file to load.
        config_data (ConfigModel): The validated configuration settings.
        logger (Logger): The logger instance for this class.

    Example:
        >>> config_manager = ConfigManager('config.json')
        >>> bot_token = config_manager.config_data.telegram_access_token
    """

    def __init__(self, config_file: str):
        """
        Initializes the ConfigManager and loads the configuration.

        Args:
            config_file (str): The name of the configuration file to load.
                              Should be located in the 'config/' directory.

        Note:
            If the config file is missing or invalid, the program will exit
            with an error code.
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
        Loads and validates the configuration from the config file.

        This method reads the JSON configuration file, validates it against
        the ConfigModel, and returns the validated configuration. If any
        validation errors occur, the program will exit with an error code.

        Returns:
            ConfigModel: The validated configuration settings.

        Raises:
            FileNotFoundError: If the config file is missing.
            json.JSONDecodeError: If the config file contains invalid JSON.
            ValidationError: If the config data doesn't match the ConfigModel schema.

        Note:
            The config file should be located in the 'config/' directory
            relative to the current working directory.
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