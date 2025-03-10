import logging

class Logs:
    @staticmethod
    def setup_logger(name, out_file):
        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)

        # Prevent duplicate loggers from beging created
        if logger.hasHandlers():
            return logger

        # Set the logging level
        logger.setLevel(logging.DEBUG)

        # Set the message formatting
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        formatter.datefmt = '%Y-%m-%d %H:%M:%S'

        # Create the handlers
        file_handler = logging.FileHandler(out_file)
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