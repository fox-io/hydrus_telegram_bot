import json
import os
import tempfile
import time
from pathlib import Path

from modules.log_manager import LogManager


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
            if 'w' in mode and payload is not None:
                self.logger.debug(f"Writing json data to {filename}.")
                self.atomic_write(filename, payload)
                return None
            with open(filename, mode, encoding='utf-8') as file:
                if 'r' in mode:
                    self.logger.debug(f"Reading json data from {filename}.")
                    return json.load(file)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            if 'r' in mode:
                self.logger.warning(f"{filename} missing or corrupted. {e}")
                if payload is not None:
                    self.atomic_write(filename, payload)
                    self.logger.info(f"Created new {filename}.")
                return payload
        except Exception as e:
            self.logger.error(f"An error occurred while opening {filename}: {e}")
        return None

    def atomic_write(self, filename: str, payload) -> None:
        """
        Writes JSON so the file is never left partially written.

        Writing in place truncates the file the moment it is opened. If the process
        dies before the write finishes, the file is left holding a fragment, which
        is not valid JSON. The recovery path in operation() then treats it as
        corrupt and recreates it from the caller's default, so an interrupted save
        of the queue silently replaced the whole index with an empty one and left
        the media behind as orphans.

        Writing to a temporary file and renaming it over the target avoids that.
        The rename is atomic, so a reader sees either the old file or the new one,
        never a half-written mixture.

        Args:
            filename (str): Destination path.
            payload: JSON-serialisable data to write.

        Raises:
            OSError: The file could not be written or replaced.

        Note:
            The temporary file is created in the destination directory so the
            rename stays on one filesystem, which is what makes it atomic.
        """
        path = Path(filename)
        handle, temporary = tempfile.mkstemp(dir=path.parent or Path('.'),
                                             prefix=path.name + '.', suffix='.tmp')
        temporary = Path(temporary)
        try:
            with os.fdopen(handle, 'w', encoding='utf-8') as file:
                json.dump(payload, file)
                file.flush()
                # Get the bytes to disk before the rename, so the rename cannot
                # publish a file whose contents are still only in the page cache.
                os.fsync(file.fileno())
            self._replace(temporary, path)
        finally:
            # Only still present if the replace never happened.
            if temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass

    @staticmethod
    def _replace(source: Path, destination: Path, attempts: int = 10) -> None:
        """
        Renames source over destination, retrying briefly on transient failures.

        Args:
            source (Path): The temporary file to publish.
            destination (Path): The path to replace.
            attempts (int): How many times to try before giving up.

        Raises:
            OSError: The rename did not succeed within the allowed attempts.

        Note:
            os.replace is atomic on both POSIX and Windows. On Windows it can still
            fail transiently when an antivirus scanner or the search indexer has the
            destination open, which is the same problem the RotatingFileHandler
            patch in bot.py works around. Retrying covers it; on POSIX the first
            attempt succeeds.
        """
        for attempt in range(attempts):
            try:
                os.replace(source, destination)
                return
            except PermissionError:
                if attempt == attempts - 1:
                    raise
                time.sleep(0.1)
