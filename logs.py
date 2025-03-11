import logging
from logging.handlers import RotatingFileHandler

class Logs:
    @staticmethod
    def setup_logger(name='logs', out_file='log.log'):
        logger = logging.getLogger(name)
        logger.propagate = False
        logger.setLevel(logging.DEBUG)

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
        console_handler.setFormatter(formatter)

        # Add the handlers to the logger
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

        return logger