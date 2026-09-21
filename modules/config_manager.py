import json
import sys

from pydantic import BaseModel, Field, ValidationError

from modules.log_manager import LogManager


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
        failed_tag (str): The tag used to mark files that could not be sent to Telegram.
                          Optional; defaults to 'failed:telegram'.
        max_send_failures (int): How many send attempts a queued file gets before it is
                                 dropped from the queue. Optional; defaults to 3.
        max_post_attempts (int): How many different files to try in a single run before
                                 giving up on posting that run. Optional; defaults to 10.
        admins (list[int]): List of Telegram user IDs with admin privileges.
        delay (int): The delay between updates in minutes.
        timezone (int): The timezone offset in hours from UTC.
        log_level (int): The logging level for the bot. uses 10/20/30/40/50 for DEBUG/INFO/WARNING/ERROR/CRITICAL

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
        ...     max_file_size=10000000,
        ...     log_level=20
        ... )
    """

    telegram_access_token: str = Field(..., min_length=1, title='Telegram Bot Access Token', description='The Telegram bot access token.')
    telegram_channel: int = Field(..., title='Telegram Channel ID', description='The Telegram channel ID.')
    telegram_bot_id: int = Field(..., title='Telegram Bot ID', description='The Telegram bot ID.')
    hydrus_api_key: str = Field(..., min_length=1, title='Hydrus API Key', description='The Hydrus API key.')
    queue_tag: str = Field(..., min_length=1, title='Queue Tag', description='The tag to use for searching Hydrus for files to queue.')
    posted_tag: str = Field(..., min_length=1, title='Posted Tag', description='The tag to use for marking files as posted in Hydrus.')
    failed_tag: str = Field('failed:telegram', title='Failed Tag', description='The tag to use for marking files that could not be sent to Telegram.')
    max_send_failures: int = Field(3, ge=1, title='Max Send Failures', description='How many times a queued file may fail to send before it is dropped from the queue.')
    max_post_attempts: int = Field(10, ge=1, title='Max Post Attempts', description='How many different queued files to try in a single run before giving up on posting anything that run.')
    ffmpeg_timeout_seconds: int = Field(300, ge=1, title='ffmpeg Timeout', description='How long a single ffmpeg invocation may run before it is killed and the file is treated as unsendable.')
    imagemagick_memory_limit_mb: int = Field(256, ge=16, title='ImageMagick Memory Limit', description='Megabytes of pixel cache ImageMagick may use before spilling to disk. Also derives its map, disk and area limits.')
    imagemagick_time_limit_seconds: int = Field(60, ge=1, title='ImageMagick Time Limit', description='How long any single ImageMagick operation may run before it is aborted.')
    imagemagick_max_source_dimension: int = Field(50000, ge=1, title='ImageMagick Max Source Dimension', description='Largest width or height in pixels ImageMagick will accept from a source file. Guards against decompression bombs declaring enormous dimensions.')
    admins: list[int] = Field(..., title='Admins', description='A list of Telegram user IDs that are bot admins.')
    delay: int = Field(..., title='Delay', description='The delay between updates in minutes.')
    timezone: int = Field(..., title='Timezone', description='The timezone offset in hours.')
    max_image_dimension: int = Field(..., title='Max Image Dimension', description='The maximum dimension of an image in pixels.')
    max_file_size: int = Field(..., title='Max File Size', description='The maximum size of a file in bytes.')
    log_level: int = Field(..., title='Log Level', description='The logging level for the bot.')


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

        Raises:
            ValueError: No config file name was given.

        Note:
            If the config file is missing or invalid, the program will exit
            with an error code.
        """
        self.logger = LogManager.setup_logger('CON')
        if not config_file:
            # Returning here would leave self.config_data undefined, turning a clear
            # configuration error into an AttributeError somewhere further along.
            self.logger.error('Missing config file argument.')
            raise ValueError('config_file is required')
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
            with open('config/' + self.config_file, encoding='utf-8') as config:
                config_data = json.load(config)
                return ConfigModel(**config_data)
        except (FileNotFoundError, json.JSONDecodeError):
            self.logger.error("Required file 'config.json' is missing or corrupted. Create a copy of config/config.json.example as config/config.json and provide values matching your environment.")
            # Cannot continue.
            sys.exit(1)
        except ValidationError as e:
            self.logger.error(f"Configuration validation error: {e}")
            # Cannot continue.
            sys.exit(1)
