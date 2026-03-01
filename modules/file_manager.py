from modules.log_manager import LogManager
import json

class FileManager:
    """
    Handles reading and writing JSON data to files with error handling and logging.

    This class provides a simple interface for file operations with built-in error handling
    and logging. It supports both reading and writing JSON data, with automatic file
    creation if the file doesn't exist during read operations.

    Attributes:
        logger (Logger): The logger instance for this class.
    """

    def __init__(self):
        """
        Initializes the FileManager with a logger instance.

        The logger is configured with the 'FIL' identifier for easy identification
        in log output.
        """
        self.logger = LogManager.setup_logger('FIL')
        self.logger.debug('File Module initialized.')

    def operation(self, filename: str, mode: str, payload=None) -> dict:
        """
        Performs read or write operations on a JSON file.

        This method handles both reading and writing JSON data to files, with built-in
        error handling for common file operations. If reading a non-existent file and
        a payload is provided, it will create the file with the payload data.

        Args:
            filename (str): The path to the file to operate on.
            mode (str): The file mode ('r' for read, 'w' for write).
            payload (dict, optional): The data to write to the file. Required for write operations.

        Returns:
            dict: The JSON data read from the file, or the payload if creating a new file.
            None if an error occurs during the operation.

        Raises:
            FileNotFoundError: If the file doesn't exist and no payload is provided for read mode.
            json.JSONDecodeError: If the file contains invalid JSON.
            Exception: For any other errors during file operations.

        Examples:
            >>> file_manager = FileManager()
            >>> # Reading a file
            >>> data = file_manager.operation('data.json', 'r')
            >>> # Writing a file
            >>> file_manager.operation('data.json', 'w', {'key': 'value'})
        """
        try:
            with open(filename, mode, encoding='utf-8') as file:
                if 'r' in mode:
                    self.logger.debug(f"Reading json data from {filename}.")
                    return json.load(file)
                elif 'w' in mode and payload is not None:
                    self.logger.debug(f"Writing json data to {filename}.")
                    json.dump(payload, file)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            if 'r' in mode:
                self.logger.warning(f"{filename} missing or corrupted. {e}")
                if payload is not None:
                    with open(filename, 'w+', encoding='utf-8') as file:
                        json.dump(payload, file)
                        self.logger.info(f"Created new {filename}.")
                return payload
        except Exception as e:
            self.logger.error(f"An error occurred while opening {filename}: {e}")
        return None