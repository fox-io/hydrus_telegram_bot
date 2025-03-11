import logging
from logging.handlers import RotatingFileHandler
from colorama import init, Fore, Style

class LogManager:
    @staticmethod
    def setup_logger(name='logs', out_file='logs/log.log'):
        logger = logging.getLogger(name)
        logger.propagate = False
        logger.setLevel(logging.DEBUG)

        class ColorFormatter(logging.Formatter):
            COLORS = {
                "DEBUG": Fore.CYAN,
                "INFO": Fore.GREEN,
                "WARNING": Fore.YELLOW,
                "ERROR": Fore.RED,
                "CRITICAL": Fore.RED + Style.BRIGHT
            }

            def format(self, record):
                log_color = self.COLORS.get(record.levelname, Fore.WHITE)
                log_message = super().format(record)
                return f"{log_color}{log_message}{Style.RESET_ALL}"

        # Prevent duplicate loggers from beging created
        if logger.hasHandlers():
            return logger
        
        # Set up rotating log files
        file_handler = RotatingFileHandler(out_file, maxBytes=5*1024*1024, backupCount=3)

        # Set the message formatting
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        formatter.datefmt = '%Y-%m-%d %H:%M:%S'

        # Create the handlers
        console_handler = logging.StreamHandler()

        # Set the handler levels
        file_handler.setLevel(logging.DEBUG)
        console_handler.setLevel(logging.DEBUG)

        # Set the handler formatting
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(ColorFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

        # Add the handlers to the logger
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

        return logger