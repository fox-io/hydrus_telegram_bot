import requests
from modules.log_manager import LogManager
import hydrus_api
import hydrus_api.utils
import typing as t

class HydrusManager:
    """
    Manages interactions with the Hydrus Network client.

    This class provides an interface for communicating with a Hydrus Network client
    through its API. It handles file operations, tag management, and metadata retrieval.

    Attributes:
        hydrus_client (hydrus_api.Client): The Hydrus API client instance.
        config (ConfigModel): The bot's configuration settings.
        queue (QueueManager): The queue manager instance.
        logger (Logger): The logger instance for this class.
        queue_file (str): The path to the queue file.
        hydrus_service_key (dict): Mapping of service names to their keys.
        permissions (tuple): Required permissions for the Hydrus client.

    Example:
        >>> hydrus = HydrusManager(config, queue)
        >>> if hydrus.check_hydrus_permissions():
        ...     files = hydrus.get_new_hydrus_files()
    """

    hydrus_service_key = {
        "my_tags": "6c6f63616c2074616773",
        "downloader_tags": "646f776e6c6f616465722074616773"
    }
    permissions = (
        hydrus_api.Permission.IMPORT_URLS,
        hydrus_api.Permission.IMPORT_FILES,
        hydrus_api.Permission.ADD_TAGS,
        hydrus_api.Permission.SEARCH_FILES,
        hydrus_api.Permission.MANAGE_PAGES,
    )

    def __init__(self, config, queue):
        """
        Initializes the HydrusManager with configuration and queue manager.

        Args:
            config (ConfigManager): The bot's configuration manager.
            queue (QueueManager): The queue manager instance.

        Note:
            The Hydrus client is initialized with the API key from the config.
        """
        self.logger = LogManager.setup_logger('HYD')
        self.config = config.config_data
        self.hydrus_client = hydrus_api.Client(self.config.hydrus_api_key)
        self.queue = queue
        self.queue_file = self.queue.queue_file
        self.logger.debug('Hydrus Module initialized.')

    def modify_tag(self, file_id: t.Union[int, list], tag: str, action: hydrus_api.TagAction, service: str):
        """
        Modifies tags on files in Hydrus Network.

        This method can add or remove tags from files in Hydrus. It supports
        both single file operations and batch operations on multiple files.

        Args:
            file_id (Union[int, list]): The file ID(s) to modify.
            tag (str): The tag to add or remove.
            action (hydrus_api.TagAction): The action to perform (ADD or DELETE).
            service (str): The service key to use ('my_tags' or 'downloader_tags').

        Note:
            If file_id is a string, it will be converted to an integer.
            If file_id is an integer, it will be converted to a single-item list.
        """
        # Ensure file_id is a list
        if isinstance(file_id, int):
            file_id = [file_id]  # Convert single int to list
        elif isinstance(file_id, str):
            try:
                file_id = [int(file_id)]  # Convert string to list of int
            except ValueError:
                self.logger.error(f"Invalid file_id format: {file_id}")
                return

        # Validate service key
        if service not in self.hydrus_service_key:
            self.logger.error(f"Invalid service key '{service}'")
            return

        # Add the tag to the file
        self.hydrus_client.add_tags(file_ids=file_id, service_keys_to_actions_to_tags={
            self.hydrus_service_key[service]: {
                int(action): [tag]
            }
        })

    def check_hydrus_permissions(self) -> bool:
        """
        Verifies that Hydrus is running and the client has required permissions.

        This method checks both the connection to Hydrus and the permissions
        granted to the API key. It logs appropriate messages for any issues found.

        Returns:
            bool: True if Hydrus is running and permissions are valid,
                  False otherwise.

        Note:
            The required permissions are defined in the class's permissions tuple.
        """
        try:
            if not hydrus_api.utils.verify_permissions(self.hydrus_client, self.permissions):
                self.logger.error("The client does not have the required permissions.")
                return False
        except requests.exceptions.ConnectionError:
            self.logger.warning("The Hydrus client is not running.")
            return False
        else:
            return True

    def get_metadata(self, id: int) -> t.Optional[dict]:
        """
        Retrieves metadata for a file from Hydrus Network.

        Args:
            id (int): The file ID to get metadata for.

        Returns:
            dict: The file's metadata, or None if an error occurs.

        Note:
            The metadata includes information such as file hash, tags,
            and known URLs.
        """
        try:
            return self.hydrus_client.get_file_metadata(file_ids=[id])
        except Exception as e:
            self.logger.error(f"An error occurred while getting metadata: {e}")
            return None

    def get_file_content(self, id: int) -> bytes:
        """
        Retrieves the content of a file from Hydrus Network.

        Args:
            id (int): The file ID to get content for.

        Returns:
            bytes: The raw file content.

        Note:
            This method returns the raw file data, which should be handled
            appropriately based on the file type.
        """
        return self.hydrus_client.get_file(file_id=id).content

    def get_new_hydrus_files(self):
        """
        Checks Hydrus for new files and adds them to the queue.

        This method:
        1. Searches for files with the queue tag
        2. Processes them in chunks of 100
        3. Saves them to the queue
        4. Updates their tags

        Note:
            Files are processed in chunks to avoid overwhelming the API.
            Each file's queue tag is removed and replaced with a posted tag
            after being added to the queue.
        """
        # Check Hydrus for new images to enqueue.
        self.logger.debug("Checking Hydrus for new files.")
        if not self.check_hydrus_permissions():
            return
        num_images = 0
        response = self.hydrus_client.search_files([self.config.queue_tag])
        all_tagged_file_ids = response.get("file_ids", [])
        if not all_tagged_file_ids:
            self.logger.info("No new images found.")
            return
        for file_ids in hydrus_api.utils.yield_chunks(all_tagged_file_ids, 100):
            for file_id in file_ids:
                num_images += self.queue.save_image_to_queue(file_id)
                self.modify_tag(file_id, self.config.queue_tag, hydrus_api.TagAction.DELETE, "downloader_tags")
                self.modify_tag(file_id, self.config.queue_tag, hydrus_api.TagAction.DELETE, "my_tags")
                self.modify_tag(file_id, self.config.posted_tag, hydrus_api.TagAction.ADD, "my_tags")
        if num_images > 0:
            self.logger.info(f"Added {num_images} image(s) to the queue.")
        else:
            self.logger.info("No new images found.")