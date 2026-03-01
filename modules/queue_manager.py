import os
import pathlib
import random
import subprocess
import typing as t
import urllib.parse
from modules.log_manager import LogManager
from modules.file_manager import FileManager

class QueueManager:
    """
    Manages the queue of images to be posted to Telegram.

    This class handles the storage, retrieval, and processing of images in the queue.
    It interfaces with both Hydrus Network and Telegram to manage the posting workflow.

    Attributes:
        config (ConfigModel): The bot's configuration settings.
        files (FileManager): The file manager instance.
        queue_file (str): The path to the queue file.
        queue_data (dict): The current queue data.
        queue_loaded (bool): Whether the queue has been loaded from disk.
        telegram (TelegramManager): The Telegram manager instance.
        hydrus (HydrusManager): The Hydrus manager instance.
        logger (Logger): The logger instance for this class.

    Methods:
        set_telegram(telegram): Sets the Telegram manager for the bot.
        set_hydrus(hydrus): Sets the Hydrus manager for the bot.
        load_queue(): Loads the queue data from the queue file.
        save_queue(): Saves the queue data to the queue file.
        image_is_queued(filename): Checks if an image is already in the queue.
        save_image_to_queue(file_id): Saves an image to the queue.
        process_queue(): Processes the queue by posting an image to Telegram.
        delete_from_queue(path, index): Deletes an image from the queue and disk.
    """

    def _proper_title(self, text: str) -> str:
        """
        Converts text to title case while properly handling apostrophes.
        
        This function fixes the issue with Python's .title() method which
        incorrectly capitalizes letters after apostrophes (e.g., "don't" -> "Don'T").
        
        Args:
            text (str): The text to convert to title case.
            
        Returns:
            str: The text in proper title case.
        """
        if not text:
            return text
        
        # Split by spaces and handle each word
        words = text.split()
        title_words = []
        
        for word in words:
            # Handle apostrophes by splitting on them and capitalizing each part
            if "'" in word:
                parts = word.split("'")
                title_parts = []
                for i, part in enumerate(parts):
                    if part:  # Only capitalize non-empty parts
                        if i == 0:  # First part gets title case
                            title_parts.append(part.capitalize())
                        else:  # Parts after apostrophe stay lowercase
                            title_parts.append(part.lower())
                title_words.append("'".join(title_parts))
            else:
                # No apostrophe, just capitalize normally
                title_words.append(word.capitalize())
        
        return " ".join(title_words)

    def __init__(self, config, queue_file: str):
        """
        Initializes the QueueManager with configuration and queue file.

        Args:
            config (ConfigManager): The bot's configuration manager.
            queue_file (str): The name of the queue file to use.

        Note:
            The queue file will be stored in the 'queue/' directory.
        """
        self.logger = LogManager.setup_logger('QUE')
        self.config = config.config_data
        self.files = FileManager()
        self.queue_file = 'queue/' + queue_file
        self.queue_data = {"queue": []}
        self.queue_loaded = False
        self.logger.debug('Queue Module initialized.')

    def set_telegram(self, telegram):
        """
        Sets the Telegram manager instance.

        Args:
            telegram (TelegramManager): The Telegram manager instance.
        """
        self.telegram = telegram

    def set_hydrus(self, hydrus):
        """
        Sets the Hydrus manager instance.
        
        Args:
            hydrus (HydrusManager): The Hydrus manager instance.
        """
        self.hydrus = hydrus

    def load_queue(self):
        """
        Loads the queue data from the queue file.

        This method reads the queue data from the JSON file and stores it in memory.
        If the file doesn't exist, it creates a new queue with an empty list.

        Note:
            The queue is only loaded if it hasn't been loaded already.
            This prevents unnecessary file I/O operations.
        """
        self.logger.debug(f"Queue loaded?: {self.queue_loaded and 'yes' or 'no'}")
        if self.queue_loaded:
            self.logger.debug("Queue already loaded.")
            return

        self.queue_data = self.files.operation(self.queue_file, 'r', {"queue":[]})
        self.logger.debug("Loaded queue.json")
        self.queue_loaded = True

    def save_queue(self):
        """
        Saves the current queue data to the queue file.

        This method writes the current queue data to the JSON file and marks
        the queue as unloaded to ensure fresh data is read next time.

        Note:
            The queue is marked as unloaded after saving to ensure data consistency.
        """
        self.files.operation(self.queue_file, 'w+', self.queue_data)
        self.logger.debug("Saved queue.json")
        self.queue_loaded = False

    def image_is_queued(self, filename: str) -> bool:
        """
        Checks if an image is already in the queue.

        Args:
            filename (str): The name of the image file to check.
        
        Returns:
            bool: True if the image is in the queue, False otherwise.

        Note:
            This method automatically loads the queue if it hasn't been loaded.
        """
        self.load_queue()
        if len(self.queue_data['queue']) > 0:
            for entry in self.queue_data['queue']:
                if entry['path'] == filename:
                    return True
        return False

    def save_image_to_queue(self, file_id: int) -> int:
        """
        Saves an image from Hydrus to the queue.

        This method:
        1. Retrieves metadata from Hydrus
        2. Downloads the file content
        3. Saves it to the queue directory
        4. Adds it to the queue data

        Args:
            file_id (int): The ID of the file to save.

        Returns:
            int: 1 if the image was saved successfully, 0 otherwise.

        Raises:
            Exception: If an error occurs while saving the image.

        Note:
            The image is only added to the queue if it's not already present.
        """
        try:
            # Load metadata from Hydrus.
            metadata = self.hydrus.get_metadata(file_id)
            if not metadata or 'metadata' not in metadata or not metadata["metadata"]:
                self.logger.error(f"No metadata found for file_id {file_id}.")
                return 0

            file_info = metadata['metadata'][0]
            if 'hash' not in file_info or 'ext' not in file_info or 'file_id' not in file_info or 'tags' not in file_info:
                self.logger.error(f"Missing file info for file_id {file_id}.")
                return 0

            # Save image from Hydrus to queue folder. Creates filename based on hash.
            filename = str(f"{file_info['hash']}{file_info['ext']}")
            path = pathlib.Path.cwd() / "queue" / filename
            try:
                file_content = self.hydrus.get_file_content(file_info['file_id'])
                if not file_content:
                    self.logger.error(f"No file content found for file_id {file_info['file_id']}.")
                    return 0
                path.write_bytes(file_content)
            except Exception as e:
                self.logger.error(f"An error occurred while saving the image to the queue: {filename}: {e}")
                return 0

            # Get the tags for the image
            tags_dict = file_info.get("tags", {})
            if self.hydrus.hydrus_service_key["downloader_tags"] not in tags_dict:
                self.logger.error(f"No downloader tags found for file_id {file_id}.")
                return 0
                
            # Debug logging to understand the tags structure
            # Commented out to avoid Unicode encoding issues in console logging
            # Uncomment the lines below if you need to debug tag structures
            # try:
            #     sanitized_tags = str(tags_dict).encode('ascii', errors='replace').decode('ascii')
            #     self.logger.debug(f"Tags structure for file_id {file_id}: {sanitized_tags}")
            #     self.logger.debug(f"Downloader tags key: {self.hydrus.hydrus_service_key['downloader_tags']}")
            #     if self.hydrus.hydrus_service_key["downloader_tags"] in tags_dict:
            #         sanitized_downloader_tags = str(tags_dict[self.hydrus.hydrus_service_key['downloader_tags']]).encode('ascii', errors='replace').decode('ascii')
            #         self.logger.debug(f"Downloader tags structure: {sanitized_downloader_tags}")
            # except Exception as e:
            #     self.logger.debug(f"Could not log tags structure due to encoding issues: {e}")

            # Process tags and create metadata
            downloader_tags = tags_dict[self.hydrus.hydrus_service_key["downloader_tags"]]
            
            # Check if downloader_tags has the expected structure
            if 'storage_tags' not in downloader_tags:
                self.logger.warning(f"No storage_tags found in downloader_tags for file_id {file_id}. Skipping tag processing.")
                tags = []
            else:
                storage_tags = downloader_tags['storage_tags']
                
                # Check if storage_tags has the expected structure
                if not storage_tags or '0' not in storage_tags:
                    self.logger.warning(f"No storage tags found for file_id {file_id} or missing '0' key. Skipping tag processing.")
                    tags = []
                else:
                    tags = storage_tags['0']
            creator = None
            title = None
            character = None

            for tag in tags:
                if tag.startswith("creator:"):
                    tag = self.telegram.replace_html_entities(tag)
                    creator_tag = tag.split(":", 1)[1]
                    creator_name = creator_tag.replace(" (artist)", "")
                    creator_name = self._proper_title(creator_name)
                    creator_urlencoded = creator_tag.replace(" ", "_")
                    creator_urlencoded = urllib.parse.quote(creator_urlencoded)
                    creator_markup = f"<a href=\"https://e621.net/posts?tags={creator_urlencoded}\">{creator_name}</a>"
                    creator = creator_markup if creator is None else creator + "\n" + creator_markup

                elif tag.startswith("title:"):
                    tag = self.telegram.replace_html_entities(tag)
                    title_tag = tag.split(":", 1)[1]
                    title_name = title_tag.replace(" (series)", "")
                    title_name = self._proper_title(title_name)
                    # Remove non-ASCII characters from title_name
                    title_name = ''.join(c for c in title_name if ord(c) < 128)
                    title_markup = f"{title_name}"
                    title = title_markup if title is None else title + "\n" + title_markup

                elif tag.startswith("character:"):
                    tag = self.telegram.replace_html_entities(tag)
                    character_tag = tag.split(":", 1)[1]
                    character_name = character_tag.replace(" (character)", "")
                    character_name = self._proper_title(character_name)
                    character_urlencoded = character_tag.replace(" ", "_")
                    character_urlencoded = urllib.parse.quote(character_urlencoded)
                    character_markup = f"<a href=\"https://e621.net/posts?tags={character_urlencoded}\">{character_name}</a>"
                    character = character_markup if character is None else character + "\n" + character_markup

            # Create sauce links.
            known_urls = metadata['metadata'][0].get('known_urls', [])
            sauce = self.telegram.concatenate_sauce(known_urls) if known_urls else None

            # Add image to queue if not present.
            if not self.image_is_queued(filename):
                # Assemble image data into a dict
                image_data = {'path': filename}
                if sauce is not None and sauce != "":
                    image_data.update({'sauce': sauce})

                if creator is not None and creator != "":
                    image_data.update({'creator': creator})

                if title is not None and title != "":
                    image_data.update({'title': title})

                if character is not None and character != "":
                    image_data.update({'character': character})

                # Insert image data dict into queue.
                self.queue_data['queue'].append(image_data)
                self.queue_loaded = False
                self.save_queue()
                return 1
            else:
                return 0

        except Exception as e:
            self.logger.error(f"An error occurred while saving the image to the queue: {e}")
            return 0

    def delete_from_queue(self, path: str, index: int):
        """
        Deletes an image from the queue and disk.

        This method:
        1. Deletes the image file from disk
        2. Removes the image from the queue data
        3. Saves the updated queue
        4. Logs the remaining queue size

        Args:
            path (str): The path to the image file.
            index (int): The index of the image in the queue.
        
        Raises:
            IndexError: If the image could not be removed from the queue.
            OSError: If the image could not be deleted from disk.
            Exception: If any other error occurs during deletion.

        Note:
            For webm files, both the original file and its mp4 conversion are deleted.
        """
        try:
            os.remove(path)
        except OSError as e:
            self.logger.error(f"Could not delete file {path}: {e}")

        if path.endswith(".webm"):
            try:
                os.remove(path + ".mp4")
            except OSError as e:
                self.logger.error(f"Could not delete file {path + '.mp4'}: {e}")

        try:
            self.queue_data['queue'].pop(index)
        except IndexError as e:
            self.logger.error(f"Could not remove image from queue: {e}")

        self.queue_loaded = False
        self.save_queue()

        # Send queue size update to terminal.
        self.logger.info("Queued images remaining: " + str(len(self.queue_data['queue'])))

    def process_queue(self):
        """
        Processes the queue by posting an image to Telegram.

        This method:
        1. Loads the queue data
        2. Selects a random image
        3. Converts webm to mp4 if needed
        4. Posts the image to Telegram
        5. Deletes the image from queue and disk

        Raises:
            Exception: If an error occurs while processing the queue.

        Note:
            The method handles both image and video files, with special
            processing for webm files including thumbnail generation.
        """
        # Post next image to Telegram and remove it from the queue.
        self.logger.debug("Processing next image in queue.")
        self.load_queue()

        if not self.queue_data or "queue" not in self.queue_data:
            self.logger.error("Queue data is missing or invalid.")
            return
        if not self.queue_data["queue"]:
            self.logger.warning("Queue is empty.")
            self.telegram.send_message("Queue is empty.")
            return

        # Select a random image from the queue
        random_index = random.randint(0, len(self.queue_data['queue']) - 1)
        current_queued_image = self.queue_data['queue'][random_index]
        path = "queue/" + current_queued_image['path']

        channel = str(self.config.telegram_channel)

        # Determine media type and prepare files for sending.
        thumb_file = None
        media_file = None
        try:
            if path.endswith(".webm"):
                # Use ffmpeg to convert webm to mp4
                subprocess.run(["ffmpeg", "-y", "-i", path, "-c:v", "libx264", "-c:a", "aac", "-strict", "experimental", path + ".mp4"], check=True)
                # Use ffmpeg to extract thumbnail from mp4
                subprocess.run(["ffmpeg", "-y", "-i", path + ".mp4", "-vframes", "1", path + ".jpg"], check=True)
                thumb_file = open(path + ".jpg", 'rb')
                media_file = open(path + ".mp4", 'rb')
                telegram_file = {'video': media_file, 'thumbnail': thumb_file}
                api_method = 'sendVideo'
            elif path.endswith(".mp4"):
                # Native mp4 file. Extract thumbnail and send as video.
                subprocess.run(["ffmpeg", "-y", "-i", path, "-vframes", "1", path + ".jpg"], check=True)
                thumb_file = open(path + ".jpg", 'rb')
                media_file = open(path, 'rb')
                telegram_file = {'video': media_file, 'thumbnail': thumb_file}
                api_method = 'sendVideo'
            else:
                # Ensure image filesize and dimensions are compatible with Telegram API
                if not self.telegram.reduce_image_size(path):
                    self.logger.warning(f"Image {path} has invalid dimensions and cannot be sent. Removing from queue.")
                    self.telegram.send_message(
                        f"⚠️ Image removed from queue (invalid dimensions):\n`{current_queued_image['path']}`"
                    )
                    self.delete_from_queue(path, random_index)
                    return
                media_file = open(path, 'rb')
                telegram_file = {'photo': media_file}
                api_method = 'sendPhoto'

            # Build Telegram bot API URL.
            message = self.telegram.get_message_markup(current_queued_image)
            request = self.telegram.build_telegram_api_url(api_method, '?chat_id=' + str(channel) + message + '&parse_mode=html', False)

            # Post the image to Telegram.
            success = self.telegram.send_image(request, telegram_file, path)
        finally:
            if media_file is not None:
                media_file.close()
            if thumb_file is not None:
                thumb_file.close()

        if api_method == 'sendVideo' and os.path.exists(path + ".jpg"):
            os.remove(path + ".jpg")

        # Only delete the image from disk and queue if it was sent successfully.
        if success:
            self.delete_from_queue(path, random_index)
        else:
            self.logger.warning(f"Keeping {path} in queue due to send failure.")
