import os
import pathlib
import random
import subprocess
import typing as t
import urllib
from modules.log_manager import LogManager
from modules.file_manager import FileManager

class QueueManager:
    def __init__(self, config, queue_file):
        self.logger = LogManager.setup_logger('QUE')
        self.config = config
        self.files = FileManager()
        self.queue_file = 'queue/' + queue_file
        self.queue_loaded = False
        self.logger.debug('Queue Module initialized.')

    def set_telegram(self, telegram):
        self.telegram = telegram

    def set_hydrus(self, hydrus):
        self.hydrus = hydrus

    def load_queue(self):
        # Load queue from file.
        self.logger.debug(f"Queue loaded?: {self.queue_loaded and 'yes' or 'no'}")
        if self.queue_loaded:
            self.logger.debug("Queue already loaded.")
            return

        self.queue_data = self.files.operation(self.queue_file, 'r', {"queue":[]})
        self.logger.debug("Loaded queue.json")
        self.queue_loaded = True

    def save_queue(self):
        # Save queue to file.
        self.files.operation(self.queue_file, 'w+', self.queue_data)
        self.logger.debug("Saved queue.json")
        self.queue_loaded = False

    def image_is_queued(self, filename: str):
        # Check that image being enqueued is not already queued.
        self.load_queue()
        if len(self.queue_data['queue']) > 0:
            for entry in self.queue_data['queue']:
                if entry['path'] == filename:
                    return True
        return False

    def save_image_to_queue(self, file_id):
        try:
            # Insert an image into the queue.

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
            path = t.cast(pathlib.Path, pathlib.Path.cwd()) / "queue" / filename
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
            tags = tags_dict[self.hydrus.hydrus_service_key["downloader_tags"]].get('display_tags', {}).get('0', [])

            # Extract creator tag if present.
            creator = None
            for tag in tags:
                if "creator:" in tag:
                    tag = self.telegram.replace_html_entities(tag)
                    creator_tag = tag.split(":")[1]
                    creator_name = creator_tag.title()
                    creator_urlencoded = creator_tag.replace(" ", "_")
                    creator_urlencoded = urllib.parse.quote(creator_urlencoded)
                    creator_markup = f"<a href=\"https://e621.net/posts?tags={creator_urlencoded}\">{creator_name}</a>"
                    creator = creator_markup

            # Extract title tag(s) if present.
            title = None
            for tag in tags:
                if "title:" in tag:
                    tag = self.telegram.replace_html_entities(tag)
                    title_tag = tag.split(":")[1]
                    title_name = title_tag
                    title_markup = f"{title_name}"
                    title = title is None and title_markup or title + "\n" + title_markup

            # Extract character tag(s) if present.
            character = None
            for tag in tags:
                if "character:" in tag:
                    tag = self.telegram.replace_html_entities(tag)
                    character_tag = tag.split(":")[1]
                    # Some tags have "(character)" in their tag name. For display purposes, we don't need this.
                    # We also capitalize the character names in the display portion of the link.
                    character_name = character_tag.replace(" (character)", "")
                    character_name = character_name.title()
                    character_urlencoded = character_tag.replace(" ", "_")
                    character_urlencoded = urllib.parse.quote(character_urlencoded)
                    character_markup = f"<a href=\"https://e621.net/posts?tags={character_urlencoded}\">{character_name}</a>"
                    character = character is None and character_markup or character + "\n" + character_markup

            # Create sauce links.
            sauce = self.telegram.concatenate_sauce(metadata['metadata'][0]['known_urls'])

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
            self.logger.error("An error occurred while saving the image to the queue: ", str(e))
            return 0

    def delete_from_queue(self, path, index):
        try:
            os.remove(path)
            if path.endswith(".webm"):
                os.remove(path + ".mp4")
        except OSError as ose:
            self.logger.error(f"Could not delete file {path + '.mp4'}: {ose}")
        except Exception as e:
            self.logger.error(f"Could not delete file {path}: {e}")

        try:
            self.queue_data['queue'].pop(index)
        except IndexError as e:
            self.logger.error(f"Could not remove image from queue: {e}")

        self.queue_loaded = False
        self.save_queue()

        # Send queue size update to terminal.
        self.logger.info("Queued images remaining: " + str(len(self.queue_data['queue'])))

    def process_queue(self):
        # Post next image to Telegram and remove it from the queue.
        self.logger.debug("Processing next image in queue.")
        self.load_queue()

        try:
            if not self.queue_data or "queue" not in self.queue_data:
                self.logger.error("Loaded queue data is missing or invalid.")
                return

            if not self.queue_data["queue"]:
                self.logger.warning("Queue is empty.")
                self.telegram.send_message("Queue is empty.")
                return
        except Exception as e:
            self.logger.error(f"An error occurred while processing the queue: {e}")

        # Select a random image from the queue
        random_index = random.randint(0, len(self.queue_data['queue']) - 1)
        current_queued_image = self.queue_data['queue'][random_index]
        path = "queue/" + current_queued_image['path']

        channel = str(self.config.channel)

        # Check if variable path ends in webm
        if path.endswith(".webm"):
            # Use ffmpeg to convert webm to mp4
            subprocess.run(["ffmpeg", "-y", "-i", path, "-c:v", "libx264", "-c:a", "aac", "-strict", "experimental", path + ".mp4"], check=True)
            # Use ffmpeg to extract thumbnail from mp4
            subprocess.run(["ffmpeg", "-y", "-i", path + ".mp4", "-vframes", "1", path + ".jpg"], check=True)
            thumb_file = open(path + ".jpg", 'rb')
            media_file = open(path + ".mp4", 'rb')
            telegram_file = {'video': media_file, 'thumbnail': thumb_file}
            api_method = 'sendVideo'
        else:
            # Ensure image filesize and dimensions are compatible with Telegram API
            self.telegram.reduce_image_size(path)
            media_file = open(path, 'rb')
            telegram_file = {'photo': media_file}
            api_method = 'sendPhoto'

        # Build Telegram bot API URL.
        message = self.telegram.get_message_markup(current_queued_image)
        request = self.telegram.build_telegram_api_url(api_method, '?chat_id=' + str(channel) + '&' + message + '&parse_mode=html', False)

        # Post the image to Telegram.
        self.telegram.send_image(request, telegram_file, path)

        media_file.close()
        if api_method == 'sendVideo':
            thumb_file.close()
            os.remove(path + ".jpg")

        # Delete the image from disk and queue.
        self.delete_from_queue(path, random_index)