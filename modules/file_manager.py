from modules.log_manager import LogManager
import json

class FileManager:
    def __init__(self):
        self.logger = LogManager.setup_logger('FIL')
        self.logger.info('File Module initialized.')

    def operation(self, filename: str, mode: str, payload=None):
        try:
            with open(filename, mode) as file:
                if 'r' in mode:
                    self.logger.info(f"Reading json data from {filename}.")
                    return json.load(file)
                elif 'w' in mode and payload is not None:
                    self.logger.info(f"Writing json data to {filename}.")
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