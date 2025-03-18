from modules.log_manager import LogManager
import json

class FileManager:
    """
    FileManager handles reading and writing json data to files.

    Methods:
        operation(filename, mode, payload): Reads or writes json data to a file.
    """
    def __init__(self):
        """
        Initializes the FileManager object.
        """
        self.logger = LogManager.setup_logger('FIL')
        self.logger.debug('File Module initialized.')

    def operation(self, filename: str, mode: str, payload=None):
        """
        Reads or writes json data to a file.

        Args:
            filename (str): The name of the file to read or write.
            mode (str): The mode to open the file in.
            payload (dict, optional): The data to write to the file.

        Returns:
            dict: The json data read from the file.
        """
        try:
            with open(filename, mode) as file:
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
                    with open(filename, 'w+') as file:
                        json.dump(payload, file)
                        self.logger.info(f"Created new {filename}.")
                return payload
        except Exception as e:
            self.logger.error(f"An error occurred while opening {filename}: {e}")
        return None