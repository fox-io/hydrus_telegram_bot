import requests
from modules.log_manager import LogManager
from modules.file_manager import FileManager
import json
import hydrus_api
import hydrus_api.utils
import typing as t

class HydrusManager:
    queue_data = []
    queue_loaded = False
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
        self.logger = LogManager.setup_logger('HYD')
        self.config = config
        self.hydrus_client = hydrus_api.Client(self.config.hydrus_api_key)
        self.queue = queue
        self.queue_file = self.queue.queue_file
        self.logger.debug('Hydrus Module initialized.')

    def modify_tag(self, file_id: t.Union[int, list], tag: str, action: hydrus_api.TagAction, service: str):
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

    def check_hydrus_permissions(self):
        # Check that Hydrus is running and the current permissions are valid.
        try:
            if not hydrus_api.utils.verify_permissions(self.hydrus_client, self.permissions):
                self.logger.error("The client does not have the required permissions.")
                return False
        except requests.exceptions.ConnectionError:
            self.logger.warning("The Hydrus client is not running.")
            return False
        else:
            return True
        
    def get_metadata(self, id):
        try:
            return self.hydrus_client.get_file_metadata(file_ids=id)
        except Exception as e:
            self.logger.error("An error occurred while getting metadata: ", str(e))
            return None
        
    def get_file_content(self, id):
        return self.hydrus_client.get_file(file_id=id).content
        
    def get_new_hydrus_files(self):
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
                num_images += self.queue.save_image_to_queue([file_id])
                self.modify_tag(file_id, self.config.queue_tag, hydrus_api.TagAction.DELETE, "downloader_tags")
                self.modify_tag(file_id, self.config.queue_tag, hydrus_api.TagAction.DELETE, "my_tags")
                self.modify_tag(file_id, self.config.posted_tag, hydrus_api.TagAction.ADD, "my_tags")
        if num_images > 0:
            self.logger.info(f"Added {num_images} image(s) to the queue.")
        else:
            self.logger.info("No new images found.")