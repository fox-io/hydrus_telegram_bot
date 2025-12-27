import logging
from logging.handlers import RotatingFileHandler
from colorama import init, Fore, Style
import os

# Initialize colorama
init(autoreset=True)

class LogManager:
    """
    Manages the logging system for the bot with colorized console output and file rotation.

    This class provides a centralized logging system with the following features:
    - Colorized console output for different log levels
    - Rotating file handler with size limits
    - Configurable log levels and formats
    - Prevention of duplicate loggers

    The class uses a static method to create and configure loggers, ensuring consistent
    logging behavior across the application.

    Example:
        >>> logger = LogManager.setup_logger('MODULE_NAME')
        >>> logger.info('This is an info message')
        >>> logger.error('This is an error message')
        >>> LogManager.set_level(logging.DEBUG)
    """

    @staticmethod
    def set_level(level: int):
        """
        Sets the logging level for all handlers of all known loggers.

        Args:
            level (int): The logging level to set (e.g., logging.INFO, logging.DEBUG).
        """
        # Iterate over all known loggers in the current logging manager
        for name in logging.Logger.manager.loggerDict:
            logger = logging.getLogger(name)
            for handler in logger.handlers:
                handler.setLevel(level)

        # Print to console to log the change in log levels. Use logging.INFO to do so.
        logger = logging.getLogger('BOT')
        logger.info(f"Log level set to {logging.getLevelName(level)}")


    @staticmethod
    def setup_logger(name: str = 'logs', out_file: str = 'logs/log.log') -> logging.Logger:
        """
        Creates and configures a logger with both file and console handlers.

        This method sets up a logger with the following features:
        - Rotating file handler (5MB max size, 3 backup files)
        - Colorized console output
        - Custom formatting with timestamps and module names
        - Prevention of duplicate handlers

        Args:
            name (str): The name of the logger. Used to identify the source of log messages.
                        Defaults to 'logs'.
            out_file (str): The path to the log file. Defaults to 'logs/log.log'.

        Returns:
            logging.Logger: A configured logger instance ready for use.

        Note:
            If a logger with the same name already exists and has handlers,
            the existing logger will be returned to prevent duplicate logging.
        """
        logger = logging.getLogger(name)
        logger.propagate = False
        logger.setLevel(logging.DEBUG)

        class ColorFormatter(logging.Formatter):
            """
            Custom formatter that adds color to log messages based on their level.

            This formatter extends the standard logging.Formatter to add color
            to log messages in the console output. Different log levels are
            assigned different colors for better visibility.

            Attributes:
                COLORS (dict): Mapping of log levels to their corresponding colors.
            """
            COLORS = {
                "DEBUG": Fore.CYAN,
                "INFO": Fore.GREEN,
                "WARNING": Fore.YELLOW,
                "ERROR": Fore.RED,
                "CRITICAL": Fore.RED + Style.BRIGHT
            }

            def format(self, record: logging.LogRecord) -> str:
                """
                Formats the log record with color based on its level.

                Args:
                    record (logging.LogRecord): The log record to format.

                Returns:
                    str: The formatted log message with color codes.
                """
                log_color = self.COLORS.get(record.levelname, Fore.WHITE)
                log_message = super().format(record)
                
                # Handle Unicode characters safely
                try:
                    return f"{log_color}{log_message}{Style.RESET_ALL}"
                except UnicodeEncodeError:
                    # If Unicode fails, replace problematic characters
                    safe_message = log_message.encode('utf-8', errors='replace').decode('utf-8')
                    return f"{log_color}{safe_message}{Style.RESET_ALL}"
            
        # Prevent duplicate loggers from being created
        if logger.hasHandlers():
            return logger
        
        # Create the log directory if it doesn't exist
        os.makedirs(os.path.dirname(out_file), exist_ok=True)
        
        # Set up rotating log files
        file_handler = RotatingFileHandler(
            out_file,
            maxBytes=5*1024*1024,  # 5MB
            backupCount=3
        )
        
        # Set the message formatting
        formatter = logging.Formatter(
            '%(asctime)s (%(name)s) %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Create the handlers
        import sys
        console_handler = logging.StreamHandler(sys.stdout)
        
        # Set the handler levels
        file_handler.setLevel(logging.DEBUG)
        console_handler.setLevel(logging.INFO)
        
        # Set the handler formatting
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(ColorFormatter(
            '%(asctime)s (%(name)s) %(levelname)s - %(message)s'
        ))
        
        # Add the handlers to the logger
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

        return logger