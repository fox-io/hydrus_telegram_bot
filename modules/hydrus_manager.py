import requests
from modules.log_manager import LogManager
from modules.queue_manager import QueueResult
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

    def get_file_id(self, file_hash: str) -> t.Optional[int]:
        """
        Looks up a Hydrus file ID from its hash.

        Used to recover the file ID for queue entries written before the ID was
        stored alongside the queued file.

        Args:
            file_hash (str): The file's Hydrus hash.

        Returns:
            int: The file ID, or None if it could not be resolved.
        """
        try:
            metadata = self.hydrus_client.get_file_metadata(hashes=[file_hash], only_return_identifiers=True)
        except Exception as e:
            self.logger.error(f"An error occurred while looking up the file id for hash {file_hash}: {e}")
            return None

        entries = (metadata or {}).get('metadata') or []
        if not entries:
            self.logger.warning(f"Hydrus returned no metadata for hash {file_hash}.")
            return None
        return entries[0].get('file_id')

    def mark_file_failed(self, file_id: t.Optional[int] = None, file_hash: t.Optional[str] = None) -> bool:
        """
        Tags a file in Hydrus as having failed to send to Telegram.

        The failed tag gives you a Hydrus-side worklist of files the bot gave up on,
        so they can be reviewed and requeued once the underlying problem is fixed.
        The posted tag is removed at the same time, since the file was never posted.

        Args:
            file_id (int, optional): The Hydrus file ID. Preferred when known.
            file_hash (str, optional): The file's hash, used to resolve the ID when
                                       file_id is not available.

        Returns:
            bool: True if the file was tagged, False otherwise.

        Note:
            Failures here are logged and swallowed. Being unable to tag a file must
            not stop the bot from dropping it from the queue, or the queue would
            never drain.
        """
        if file_id is None and file_hash:
            file_id = self.get_file_id(file_hash)

        if file_id is None:
            self.logger.warning("Cannot mark a file as failed in Hydrus without a file id or hash.")
            return False

        try:
            self.modify_tag(file_id, self.config.failed_tag, hydrus_api.TagAction.ADD, "my_tags")
            # The file never actually posted, so the posted tag would be misleading.
            self.modify_tag(file_id, self.config.posted_tag, hydrus_api.TagAction.DELETE, "my_tags")
        except Exception as e:
            self.logger.error(f"Could not tag file_id {file_id} as {self.config.failed_tag}: {e}")
            return False

        self.logger.info(f"Tagged file_id {file_id} as {self.config.failed_tag} in Hydrus.")
        return True

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

            Retagging only happens once the file is confirmed to be in the queue.
            A file that fails to enqueue keeps its queue tag so it is retried on the
            next run, rather than being marked as posted and lost.
        """
        # Check Hydrus for new images to enqueue.
        self.logger.debug("Checking Hydrus for new files.")
        if not self.check_hydrus_permissions():
            return
        num_images = 0
        num_failed = 0
        response = self.hydrus_client.search_files([self.config.queue_tag])
        all_tagged_file_ids = response.get("file_ids", [])
        if not all_tagged_file_ids:
            self.logger.info("No new images found.")
            return
        for file_ids in hydrus_api.utils.yield_chunks(all_tagged_file_ids, 100):
            for file_id in file_ids:
                result = self.queue.save_image_to_queue(file_id)

                # Leave the queue tag in place so the file is picked up again next run.
                if result is QueueResult.FAILED:
                    num_failed += 1
                    self.logger.warning(f"Not retagging file_id {file_id}; it was not added to the queue. It will be retried.")
                    continue

                if result is QueueResult.ADDED:
                    num_images += 1

                self.modify_tag(file_id, self.config.queue_tag, hydrus_api.TagAction.DELETE, "downloader_tags")
                self.modify_tag(file_id, self.config.queue_tag, hydrus_api.TagAction.DELETE, "my_tags")
                self.modify_tag(file_id, self.config.posted_tag, hydrus_api.TagAction.ADD, "my_tags")
        if num_failed > 0:
            self.logger.error(f"{num_failed} file(s) could not be added to the queue and will be retried next run.")
        if num_images > 0:
            self.logger.info(f"Added {num_images} image(s) to the queue.")
        else:
            self.logger.info("No new images found.")