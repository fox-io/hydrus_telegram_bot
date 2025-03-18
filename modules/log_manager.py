import logging
from logging.handlers import RotatingFileHandler
from colorama import init, Fore, Style
import os

# Initialize colorama
init(autoreset=True)

class LogManager:
    """
    LogManager handles the logging system for the bot.
    
    Methods:
        setup_logger(name, out_file): Sets up the logging system.
    """
    @staticmethod
    def setup_logger(name='logs', out_file='logs/log.log'):
        """
        Sets up a logger with the specified name and output file.

        Args:
            name (str): The name of the logger.
            out_file (str): The output file for the logger.

        Returns:
            logging.Logger: The configured logger object.
        """
        logger = logging.getLogger(name)
        logger.propagate = False
        logger.setLevel(logging.DEBUG)

        class ColorFormatter(logging.Formatter):
            """
            ColorFormatter adds color to the log messages based on the log level.

            Attributes:
                COLORS (dict): A dictionary of colors for each log level.
            """
            COLORS = {
                "DEBUG": Fore.CYAN,
                "INFO": Fore.GREEN,
                "WARNING": Fore.YELLOW,
                "ERROR": Fore.RED,
                "CRITICAL": Fore.RED + Style.BRIGHT
            }

            def format(self, record):
                """
                Formats the log message with color based on the log level.

                Args:
                    record (LogRecord): The log record to format.

                Returns:
                    str: The formatted log message.
                """
                log_color = self.COLORS.get(record.levelname, Fore.WHITE)
                log_message = super().format(record)
                return f"{log_color}{log_message}{Style.RESET_ALL}"
            
        # Prevent duplicate loggers from beging created
        if logger.hasHandlers():
            return logger
        
        # Create the log directory if it doesn't exist
        os.makedirs(os.path.dirname(out_file), exist_ok=True)
        
        # Set up rotating log files
        file_handler = RotatingFileHandler(out_file, maxBytes=5*1024*1024, backupCount=3)
        
        # Set the message formatting
        formatter = logging.Formatter('%(asctime)s (%(name)s) %(levelname)s - %(message)s')
        formatter.datefmt = '%Y-%m-%d %H:%M:%S'
        
        # Create the handlers
        console_handler = logging.StreamHandler()
        
        # Set the handler levels
        file_handler.setLevel(logging.DEBUG)
        console_handler.setLevel(logging.DEBUG)
        
        # Set the handler formatting
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(ColorFormatter('%(asctime)s (%(name)s) %(levelname)s - %(message)s'))
        
        # Add the handlers to the logger
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

        return logger