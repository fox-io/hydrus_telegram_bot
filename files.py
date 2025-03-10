from logs import Logs
import json

class Files:
    def __init__(self):
        self.logger = Logs.setup_logger('FIL')
        self.logger.info('File Module initialized.')

    def operation(self, filename: str, mode: str, payload=None):
        # File operation function
        try:
            with open(filename, mode) as file:
                if 'r' in mode:
                    return json.load(file)
                elif 'w' in mode and payload is not None:
                    json.dump(payload, file)
        except (FileNotFoundError, json.JSONDecodeError):
            if 'r' in mode:
                self.logger.warning(f"{filename} missing or corrupted.")
                if payload is not None:
                    with open(filename, 'w+') as file:
                        json.dump(payload, file)
                        self.logger.info(f"Created new {filename}.")
                return payload
        except Exception as e:
            self.logger.error(f"An error occurred while opening {filename}: {e}")
        return None