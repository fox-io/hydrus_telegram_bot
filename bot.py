import math
import pathlib
import json
import random
import requests
import sched
import time
import os
import re
import subprocess
from urllib.parse import urlparse
import urllib.parse
import hydrus_api
import hydrus_api.utils
import typing as t
from wand.image import Image


class HydrusTelegramBot:
    file_list = []
    used_ids = []
    forward_list = []
    update_list = []
    admins = []
    access_token = ""
    channel = 0
    bot_id = 0
    delay = 60
    timezone = -5
    scheduler = sched.scheduler(time.time, time.sleep)
    debug_mode = False
    subreddit_regex = "/(r/[a-z0-9][_a-z0-9]{2,20})/"
    hydrus_api_key = ""
    queue_data = []
    queue_loaded = False
    queue_tag = ""
    posted_tag = ""
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

    def get_next_update_time(self):
        # Calculate the next update time.
        current_time = (time.time() + ((60 * 60) * self.timezone))
        return (current_time - (current_time % (self.delay * 60))) + (self.delay * 60)

    def schedule_update(self):
        # Schedules an event for the next update time.
        next_time = self.get_next_update_time() - (3600 * self.timezone)
        print(f"Next update scheduled for {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(next_time))}.")
        self.scheduler.enterabs(next_time, 1, self.on_scheduler, ())

    def build_telegram_api_url(self, method: str, payload: str, is_file: bool = False):
        # Constructs a Telegram API url for bot communication.
        url = f"https://api.telegram.org/{'file/' if is_file else ''}bot{self.access_token}"
        if not is_file and method:
            url += f"/{method}"
        return (url + payload) if payload else url

    def send_message(self, message):
        # Sends a message to all admin users.
        if not message:
            return
        
        for admin in self.admins:
            try:
                payload = {
                    'chat_id': str(admin),
                    'text': message,
                    'parse_mode': 'Markdown'
                }
                response = requests.get(self.build_telegram_api_url('sendMessage', '?' + urllib.parse.urlencode(payload)), timeout=10)
                response_json = response.json()
                if not response_json.get("ok", False):  # Correct way to access "ok" key
                    print(f"Failed to send message to admin {admin}: {response_json}")
            except requests.exceptions.RequestException as e:
                print(f"An error occurred when communicating with Telegram: {e}")

    def load_config(self):
        # Load the config file.
        try:
            with open('config.json') as config:
                config_data = json.load(config)
                self.access_token = config_data['telegram_access_token']
                self.channel = config_data['telegram_channel']
                self.bot_id = config_data['telegram_bot_id']
                self.hydrus_api_key = config_data['hydrus_api_key']
                self.queue_tag = config_data['queue_tag']
                self.posted_tag = config_data['posted_tag']
                self.admins = config_data['admins']
                self.delay = config_data['delay']
                self.timezone = config_data['timezone']
        except (FileNotFoundError, json.JSONDecodeError):
            print("Error: config.json missing or corrupted.")

    def verify_queue_file(self):
        # Create a queue file if not present.
        try:
            with open('queue.json', 'r'):
                pass
        except (FileNotFoundError, json.JSONDecodeError):
            print("Warning: queue.json missing or corrupted.")
            with open('queue.json', 'w+') as queue_file:
                queue_file.write(json.dumps({
                    "queue": []
                }))
            print("Created new queue file.")

    def load_queue(self):
        # Load queue from file.
        if not self.queue_loaded:
            self.verify_queue_file()
            try:
                with open('queue.json') as queue_file:
                    self.queue_data = json.load(queue_file)
            except FileNotFoundError:
                print("A file not found error occurred when opening queue.json.")
            except json.JSONDecodeError:
                print("An error occurred when decoding queue.json.")
            else:
                self.queue_loaded = True

    def save_queue(self):
        # Save queue to file.
        try:
            with open('queue.json', 'w+') as queue_file:
                json.dump(self.queue_data, queue_file)
        except Exception as e:
            print("An error occurred while saving queue.json: ", str(e))
        else:
            self.queue_loaded = False

    def update_queue(self):
        # Update queue from Hydrus, then save queue to file.
        self.load_queue()
        self.get_new_hydrus_files()
        self.save_queue()

    def add_tag(self, file_id: list, tag: str):
        # Add Hydrus tag to indicate image has been posted (enqueued).
        self.hydrus_client.add_tags(file_ids=file_id, service_keys_to_actions_to_tags={
            self.hydrus_service_key["my_tags"]: {
                str(hydrus_api.TagAction.ADD): [tag],
            }
        })

    def remove_tag(self, file_id: list, tag: str):
        # Remove Hydrus tag indicating image should be posted.
        self.hydrus_client.add_tags(file_ids=file_id, service_keys_to_actions_to_tags={
            self.hydrus_service_key["downloader_tags"]: {
                str(hydrus_api.TagAction.DELETE): [tag]
            }
        })
        self.hydrus_client.add_tags(file_ids=file_id, service_keys_to_actions_to_tags={
            self.hydrus_service_key["my_tags"]: {
                str(hydrus_api.TagAction.DELETE): [tag]
            }
        })

    def check_hydrus_permissions(self):
        # Check that Hydrus is running and the current permissions are valid.
        try:
            if not hydrus_api.utils.verify_permissions(self.hydrus_client, self.permissions):
                print("    The client does not have the required permissions.")
                return False
        except requests.exceptions.ConnectionError:
            print("    The Hydrus client is not running.")
            return False
        else:
            return True

    # noinspection PyMethodMayBeStatic
    def concatenate_sauce(self, known_urls: list):
        # Return source URLs.
        sauce = ''
        for url in known_urls:
            # Skip direct links.
            if url.startswith("https://www.") or url.startswith("https://e621.net/posts"):
                sauce = sauce + url + ','
        return sauce
    
    def image_is_queued(self, filename: str):
        # Check that image being enqueued is not already queued.
        self.load_queue()
        if len(self.queue_data['queue']) > 0:
            for entry in self.queue_data['queue']:
                if entry['path'] == filename:
                    return True
        return False
    
    def get_metadata(self, id):
        try:
            return self.hydrus_client.get_file_metadata(file_ids=id)
        except Exception as e:
            print("An error occurred while getting metadata: ", str(e))
            return None
        
    def replace_html_entities(self, tag: str):
        # Replace HTML entities in tags.
        tag = tag.replace("&", "+")
        tag = tag.replace("<", "≺")
        tag = tag.replace(">", "≻")
        return tag

    def save_image_to_queue(self, file_id):
        try:
            # Insert an image into the queue.

            # Load metadata from Hydrus.
            metadata = self.get_metadata(file_id)
            if not metadata or 'metadata' not in metadata or not metadata["metadata"]:
                print(f"Warning: No metadata found for file_id {file_id}.")
                return 0
            
            file_info = metadata['metadata'][0]
            if 'hash' not in file_info or 'ext' not in file_info or 'file_id' not in file_info or 'tags' not in file_info:
                print(f"Warning: Missing file info for file_id {file_id}.")
                return 0

            # Save image from Hydrus to queue folder. Creates filename based on hash.
            filename = str(f"{file_info['hash']}{file_info['ext']}")
            path = t.cast(pathlib.Path, pathlib.Path.cwd()) / "queue" / filename
            try:
                file_content = self.hydrus_client.get_file(file_id=file_info['file_id']).content
                if not file_content:
                    print(f"Warning: No file content found for file_id {file_info['file_id']}.")
                    return 0
                path.write_bytes(file_content)
            except Exception as e:
                print(f"An error occurred while saving the image to the queue: {filename}: {e}")
                return 0

            # Get the tags for the image
            tags_dict = file_info.get("tags", {})
            if self.hydrus_service_key["downloader_tags"] not in tags_dict:
                print(f"Warning: No downloader tags found for file_id {file_id}.")
                return 0
            tags = tags_dict[self.hydrus_service_key["downloader_tags"]].get('display_tags', {}).get('0', [])

            # Extract creator tag if present.
            creator = None
            for tag in tags:
                if "creator:" in tag:
                    tag = self.replace_html_entities(tag)
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
                    tag = self.replace_html_entities(tag)
                    title_tag = tag.split(":")[1]
                    title_name = title_tag
                    title_markup = f"{title_name}"
                    title = title is None and title_markup or title + "\n" + title_markup

            # Extract character tag(s) if present.
            character = None
            for tag in tags:
                if "character:" in tag:
                    tag = self.replace_html_entities(tag)
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
            sauce = self.concatenate_sauce(metadata['metadata'][0]['known_urls'])

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
                self.save_queue()
                return 1
            else:
                return 0
            
        except Exception as e:
            print("An error occurred while saving the image to the queue: ", str(e))
            return 0

    def get_new_hydrus_files(self):
        # Check Hydrus for new images to enqueue.
        print("Checking Hydrus for new files.")
        if not self.check_hydrus_permissions():
            return
        num_images = 0
        response = self.hydrus_client.search_files([self.queue_tag])
        all_tagged_file_ids = response.get("file_ids", [])
        if not all_tagged_file_ids:
            print("    No new images found.")
            return
        for file_ids in hydrus_api.utils.yield_chunks(all_tagged_file_ids, 100):
            for file_id in file_ids:
                num_images += self.save_image_to_queue([file_id])
                self.remove_tag([file_id], self.queue_tag)
                self.add_tag([file_id], self.posted_tag)
        if num_images > 0:
            self.queue_loaded = False # Force reload of queue data
            print(f"    Added {num_images} image(s) to the queue.")
        else:
            print("    No new images found.")

    def build_caption_buttons(self, caption: str):
        # Assembles buttons to display under the Telegram post.
        if caption is not None:
            keyboard = {'inline_keyboard': []}
            url_column = 0
            url_row = -1
            for line in caption.split(','):
                if 'http' in line:
                    link = urlparse(line)
                    skip_link = False

                    # Pretty print known site names.
                    if 'furaffinity' in link.netloc:
                        website = 'Furaffinity'

                        if 'user' in link.path:
                            skip_link = True

                        # Check if the link is dead on Furaffinity.
                        fa_url = link.geturl()
                        try:
                            response = requests.get(fa_url, timeout=10)
                            if "The submission you are trying to find is not in our database." in response.text:
                                skip_link = True
                        except requests.exceptions.RequestException as e:
                            print("An error occurred when checking the Furaffinity link: ", str(e))
                    elif 'e621' in link.netloc:
                        website = 'e621'
                    elif 'reddit' in link.netloc:
                        subreddit_match = re.search(self.subreddit_regex, link.geturl(), re.IGNORECASE)
                        website = 'Reddit (' + subreddit_match.group(1) + ')' if subreddit_match else 'Reddit'
                    else:
                        website = link.netloc

                    # Only add the button if the link is not dead.
                    if not skip_link:
                        if url_column == 0:
                            keyboard['inline_keyboard'].append([])
                            url_row += 1
                        url = link.geturl()
                        keyboard['inline_keyboard'][url_row].append({
                            'text': website,
                            'url': url
                        })
                        url_column = url_column == 0 and 1 or 0
            return keyboard
        else:
            return None

    def reduce_image_size(self, path):
        # Telegram has limits on image file size and dimensions. We resize large things here.
        try:
            img = Image(filename=path)

            if img.format.lower() not in ["jpeg", "jpg", "png", "gif"]:
                print(f"Skipping resize: Unsupported format {img.format}")
                return
            
            if img.width > 10000 or img.height > 10000:
                img.transform(resize='1024x768')
                img.save(filename=path)

            if os.path.getsize(path) > 10000000:
                size_ratio = os.path.getsize(path) / 10000000
                img.resize(round(img.width / math.sqrt(size_ratio)), round(img.height / math.sqrt(size_ratio)))
                img.save(filename=path)
        except Exception as e:
            print("An error occurred while opening the image: ", str(e))

    def get_message_markup(self, image):
        # Build the message markup for the Telegram post.
        message_markup = ''
        
        # Sauce Buttons
        sauce = self.build_caption_buttons(image['sauce']) if "sauce" in image else None
        if sauce:
            message_markup = message_markup + '&reply_markup=' + json.dumps(sauce)
        # Caption Text
        caption_parts = []
        #     Title
        if "title" in image and image["title"]:
            caption_parts.append('Title(s):\n' + str(image['title']))
        #     Creator
        if "creator" in image and image["creator"]:
            caption_parts.append('Uploader:\n' + str(image['creator']))
        #     Character
        if "character" in image and image["character"]:
            caption_parts.append('Character(s):\n' + str(image['character']))
        caption = "\n\n".join(caption_parts) if caption_parts else "No info."
        if len(caption) > 1024:
            caption = caption[:1021] + "..."
        message_markup += f"&caption={caption}"

        return message_markup
    
    def send_image(self, api_call, image, path):
        # Attempt to send the image to our Telegram bot.
        sent_file = None

        try:
            sent_file = requests.get(api_call, files=image, timeout=10)
            if sent_file.status_code != 200:
                print(f"Error: Telegram API returned {sent_file.status_code} - {sent_file.text}")
                self.send_message(f"Image failed to send: {path}")
                return
            response_json = sent_file.json() if sent_file.headers.get('Content-Type') == 'application/json' else {}

            if response_json.get("ok"):
                print("    Image sent successfully.")
            else:
                print(f"    Image failed to send. Response: {response_json}")
                self.send_message(f"Image failed to send. {path}")
        except requests.exceptions.RequestException as e:
            print("An error occurred when communicating with the Telegram bot: ", str(e))
        
    def delete_from_queue(self, path, index):
        try:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError as ose:
                    print(f"Error deleting file {path}: {ose}")
            if path.endswith(".webm") and os.path.exists(path + ".mp4"):
                try:
                    os.remove(path + ".mp4")
                except OSError as ose:
                    print(f"Error deleting file {path + '.mp4'}: {ose}")
        except Exception as e:
            print(f"Error deleting file {path}: {e}")

        try:
            self.queue_data['queue'].pop(index)
        except IndexError as e:
            print(f"Error removing image from queue: {e}")
        self.save_queue()

        # Send queue size update to terminal.
        print("Queued images remaining: " + str(len(self.queue_data['queue'])))

    def process_queue(self):
        # Post next image to Telegram and remove it from the queue.
        print("Processing next image in queue.")
        if not self.queue_loaded:
            self.load_queue()

        if not self.queue_data["queue"]:
            print("Queue is empty.")
            self.send_message("Queue is empty.")
            return

        # Select a random image from the queue
        random_index = random.randint(0, len(self.queue_data['queue']) - 1)
        current_queued_image = self.queue_data['queue'][random_index]
        path = "queue/" + current_queued_image['path']

        channel = str(self.channel)

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
            self.reduce_image_size(path)
            media_file = open(path, 'rb')
            telegram_file = {'photo': media_file}
            api_method = 'sendPhoto'

        # Build Telegram bot API URL.
        message = self.get_message_markup(current_queued_image)
        request = self.build_telegram_api_url(api_method, '?chat_id=' + str(channel) + '&' + message + '&parse_mode=html', False)
        
        # Post the image to Telegram.
        self.send_image(request, telegram_file, path)

        media_file.close()
        if api_method == 'sendVideo':
            thumb_file.close()
            os.remove(path + ".jpg")

        # Delete the image from disk and queue.
        self.delete_from_queue(path, random_index)

    def on_scheduler(self):
        # Event handler.
        self.update_queue()
        self.process_queue()
        self.schedule_update()

    def __init__(self):
        # Startup sequence.
        try:
            self.load_config()
            self.hydrus_client = hydrus_api.Client(self.hydrus_api_key)
            self.on_scheduler()
        except Exception as e:
            print("An error occurred during initilization: ", str(e))


if __name__ == '__main__':
    # Main program loop.
    app = HydrusTelegramBot()
    while True:
        try:
            app.scheduler.run(blocking=False)
            time.sleep(5)
        except KeyboardInterrupt:
            print("Exiting...")
            break
