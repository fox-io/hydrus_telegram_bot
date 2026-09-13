import os
import pathlib
import random
import subprocess
import urllib.parse
from enum import Enum
from modules.log_manager import LogManager
from modules.file_manager import FileManager

class QueueResult(Enum):
    """
    The outcome of an attempt to save a Hydrus file to the queue.

    Attributes:
        ADDED: The file was downloaded and appended to the queue.
        DUPLICATE: The file was already in the queue, so there was nothing to do.
        FAILED: The file could not be enqueued (missing metadata, download error, etc).

    Note:
        Only FAILED means the file still needs to be picked up on a later run.
        Callers must not retag a file in Hydrus unless the result is ADDED or
        DUPLICATE, otherwise the file loses its queue tag without ever being
        queued and will never be posted.
    """
    ADDED = 'added'
    DUPLICATE = 'duplicate'
    FAILED = 'failed'

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

    def save_image_to_queue(self, file_id: int) -> QueueResult:
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
            QueueResult: ADDED if the image was appended to the queue, DUPLICATE if
                         it was already queued, or FAILED if it could not be enqueued.

        Raises:
            Exception: If an error occurs while saving the image.

        Note:
            The image is only added to the queue if it's not already present.
            A FAILED result means the file has not been queued, so the caller must
            leave its Hydrus tags alone to allow a retry on a later run.
        """
        try:
            # Load metadata from Hydrus.
            metadata = self.hydrus.get_metadata(file_id)
            if not metadata or 'metadata' not in metadata or not metadata["metadata"]:
                self.logger.error(f"No metadata found for file_id {file_id}.")
                return QueueResult.FAILED

            file_info = metadata['metadata'][0]
            if 'hash' not in file_info or 'ext' not in file_info or 'file_id' not in file_info or 'tags' not in file_info:
                self.logger.error(f"Missing file info for file_id {file_id}.")
                return QueueResult.FAILED

            # Save image from Hydrus to queue folder. Creates filename based on hash.
            filename = str(f"{file_info['hash']}{file_info['ext']}")
            path = pathlib.Path.cwd() / "queue" / filename
            try:
                file_content = self.hydrus.get_file_content(file_info['file_id'])
                if not file_content:
                    self.logger.error(f"No file content found for file_id {file_info['file_id']}.")
                    return QueueResult.FAILED
                path.write_bytes(file_content)
            except Exception as e:
                self.logger.error(f"An error occurred while saving the image to the queue: {filename}: {e}")
                return QueueResult.FAILED

            # Get the tags for the image
            tags_dict = file_info.get("tags", {})

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
            downloader_tags = tags_dict.get(self.hydrus.hydrus_service_key["downloader_tags"])

            # Check if downloader_tags has the expected structure. A file with no usable
            # tags is still postable, just without metadata, so these are warnings rather
            # than failures. Failing here would strand the file: it would never be queued
            # and would be re-downloaded on every run.
            if not downloader_tags:
                self.logger.warning(f"No downloader tags found for file_id {file_id}. "
                                    f"File: {filename}. Skipping tag processing.")
                tags = []
            elif 'storage_tags' not in downloader_tags:
                self.logger.warning(f"No storage_tags found in downloader_tags for file_id {file_id}. Skipping tag processing.")
                tags = []
            else:
                storage_tags = downloader_tags['storage_tags']
                
                # Check if storage_tags has the expected structure
                if not storage_tags or '0' not in storage_tags:
                    self.logger.warning(f"No storage tags found for file_id {file_id} or missing '0' key. "
                                        f"(available keys: {list(storage_tags.keys()) if storage_tags else 'none'}). "
                                        f"File: {filename}. Skipping tag processing.")
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
                # Assemble image data into a dict. The Hydrus file id is kept so the
                # file can be tagged back in Hydrus if it later fails to send.
                image_data = {'path': filename, 'file_id': file_info['file_id']}
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
                return QueueResult.ADDED
            else:
                return QueueResult.DUPLICATE

        except Exception as e:
            self.logger.error(f"An error occurred while saving the image to the queue: {e}")
            return QueueResult.FAILED

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

    def record_send_failure(self, path: str, index: int, entry: dict):
        """
        Records a failed send attempt and drops the file once it runs out of attempts.

        Files that fail to send stay in the queue and are redrawn at random on later
        runs. Without a cap, a file that can never be sent (unsupported format, a
        conversion ffmpeg cannot do, a file missing from disk) stays in the queue
        permanently, and those files accumulate until they crowd out the good ones.

        Args:
            path (str): The path to the media file, relative to the working directory.
            index (int): The index of the entry in the queue.
            entry (dict): The queue entry that failed to send.

        Note:
            On the final failure the file is removed from the queue and disk, and
            tagged in Hydrus with the configured failed tag so it can be reviewed
            and requeued once the underlying problem is fixed.
        """
        failures = entry.get('failures', 0) + 1
        entry['failures'] = failures
        limit = self.config.max_send_failures

        if failures < limit:
            self.logger.warning(f"Keeping {path} in queue after send failure {failures}/{limit}.")
            self.queue_loaded = False
            self.save_queue()
            return

        self.logger.error(f"Giving up on {path} after {failures} failed attempts. Removing from queue.")

        tagged = self.hydrus.mark_file_failed(
            file_id=entry.get('file_id'),
            file_hash=pathlib.Path(entry['path']).stem,
        )

        if tagged:
            self.telegram.send_message(
                f"🚫 Gave up on `{entry['path']}` after {failures} failed attempts.\n"
                f"Tagged `{self.config.failed_tag}` in Hydrus for review."
            )
        else:
            self.telegram.send_message(
                f"🚫 Gave up on `{entry['path']}` after {failures} failed attempts.\n"
                f"Could not tag it in Hydrus - check the log."
            )

        # delete_from_queue saves the queue, so no separate save is needed here.
        self.delete_from_queue(path, index)

    def process_queue(self):
        """
        Posts one image to Telegram, trying more of the queue if the first choice fails.

        This method:
        1. Loads the queue data
        2. Selects a random image and tries to post it
        3. On failure, records the failure and tries a different image
        4. Stops as soon as something posts, or when it runs out of attempts

        Note:
            Every scheduled run should result in a post. A file that cannot be sent
            must not consume the run, so failures move on to another file rather than
            waiting for the next scheduled run.

            Each file is tried at most once per run, so a file still accrues one
            failure per run and is dropped after max_send_failures runs. At most
            max_post_attempts files are tried before the run gives up, which bounds
            the work done when a large part of the queue is unsendable.
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

        # Track by path rather than index: a failed file may be dropped from the
        # queue, which shifts every index after it.
        attempted = set()
        max_attempts = self.config.max_post_attempts

        for attempt in range(1, max_attempts + 1):
            candidates = [i for i, entry in enumerate(self.queue_data['queue'])
                          if entry['path'] not in attempted]
            if not candidates:
                self.logger.warning("No untried files left in the queue this run.")
                break

            index = random.choice(candidates)
            entry = self.queue_data['queue'][index]
            attempted.add(entry['path'])

            if attempt > 1:
                self.logger.info(f"Previous file failed. Trying another (attempt {attempt}/{max_attempts}).")

            if self._attempt_post(entry, index):
                return

        self.logger.error(f"Nothing could be posted this run after trying {len(attempted)} file(s).")
        self.telegram.send_message(
            f"⚠️ Nothing could be posted this run. Tried {len(attempted)} file(s) - check the log."
        )

    def _attempt_post(self, entry: dict, index: int) -> bool:
        """
        Attempts to post a single queued file to Telegram.

        Args:
            entry (dict): The queue entry to post.
            index (int): The index of the entry in the queue.

        Returns:
            bool: True if the file was posted, False otherwise.

        Note:
            On success the file is removed from the queue and disk. On failure the
            failure is recorded against the entry, which may drop it from the queue.
            Either way this returns and lets the caller decide whether to try another
            file, so a bad file never consumes the whole run.
        """
        path = "queue/" + entry['path']
        channel = str(self.config.telegram_channel)

        # Determine media type and prepare files for sending.
        thumb_file = None
        media_file = None
        api_method = None
        success = False
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
                        f"⚠️ Image removed from queue (invalid dimensions):\n`{entry['path']}`"
                    )
                    self.delete_from_queue(path, index)
                    return False
                media_file = open(path, 'rb')
                telegram_file = {'photo': media_file}
                api_method = 'sendPhoto'

            # Build Telegram bot API URL.
            message = self.telegram.get_message_markup(entry)
            request = self.telegram.build_telegram_api_url(api_method, '?chat_id=' + str(channel) + message + '&parse_mode=html', False)

            # Post the image to Telegram.
            success = self.telegram.send_image(request, telegram_file, path)
        except (OSError, subprocess.CalledProcessError) as e:
            # A missing file or a failed ffmpeg conversion is a property of this file,
            # not of the run. Counting it as a send failure lets an unusable file be
            # dropped eventually instead of being redrawn from the queue forever.
            self.logger.error(f"Could not prepare {path} for sending: {e}")
            success = False
        finally:
            if media_file is not None:
                media_file.close()
            if thumb_file is not None:
                thumb_file.close()

        if api_method == 'sendVideo' and os.path.exists(path + ".jpg"):
            os.remove(path + ".jpg")

        # Only delete the image from disk and queue if it was sent successfully.
        if success:
            self.delete_from_queue(path, index)
            return True

        self.record_send_failure(path, index, entry)
        return False
