import math
import pathlib
import json
import random
import requests
import sched
import time
import os
import re
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
        url = 'https://api.telegram.org/'
        if is_file:
            url += 'file/'
        url += 'bot' + self.access_token + '/'
        if not is_file:
            url += method
        url += payload
        return url

    def send_message(self, message):
        # Sends a message to all admin users.
        if len(message) > 0:
            for i in range(len(self.admins)):
                admin = str(self.admins[i])
                try:
                    requests.get(self.build_telegram_api_url('sendMessage', '?chat_id=' + admin + '&text=' + message + '&parse_mode=Markdown'))
                except requests.exceptions.RequestException as e:
                    print("An error occurred when communicating with the Telegram bot: ", str(e))

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
        except FileNotFoundError:
            print("A file not found error occurred when opening config.json.")

    def verify_queue_file(self):
        # Create a queue file if not present.
        try:
            with open('queue.json', 'r'):
                pass
        except FileNotFoundError:
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
            if metadata is None:
                return 0

            # Save image from Hydrus to queue folder. Creates filename based on hash.
            filename = str(f"{metadata['metadata'][0]['hash']}{metadata['metadata'][0]['ext']}")
            path = t.cast(pathlib.Path, pathlib.Path.cwd()) / "queue" / filename
            try:
                path.write_bytes(self.hydrus_client.get_file(file_id=metadata['metadata'][0]['file_id']).content)
            except Exception as e:
                print("An error occurred while saving the image to the queue: ", str(e))
                return 0

            # Get the tags for the image
            try:
                tags = metadata['metadata'][0]['tags'][self.hydrus_service_key['downloader_tags']]['display_tags']['0']
            except KeyError as e:
                print("An error occurred while getting the tags: ", str(e))
                return 0

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
        all_tagged_file_ids = self.hydrus_client.search_files([self.queue_tag])["file_ids"]
        for file_ids in hydrus_api.utils.yield_chunks(all_tagged_file_ids, 100):
            for file_id in file_ids:
                num_images += self.save_image_to_queue([file_id])
                self.remove_tag([file_id], self.queue_tag)
                self.add_tag([file_id], self.posted_tag)
        if num_images > 0:
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
                            response = requests.get(fa_url)
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
        except Exception as e:
            print("An error occurred while opening the image: ", str(e))
        else:
            if img.width > 10000 or img.height > 10000:
                img.transform(resize='1024x768')
                img.save(filename=path)

            if os.path.getsize(path) > 10000000:
                size_ratio = os.path.getsize(path) / 10000000
                img.resize(round(img.width / math.sqrt(size_ratio)), round(img.height / math.sqrt(size_ratio)))
                img.save(filename=path)

    def get_message_markup(self, image):
        creator = None
        if "creator" in image:
            creator = str(image['creator'])
            if creator == "None" or creator == "":
                creator = None

        title = None
        if "title" in image:
            title = str(image['title'])
            if title == "None" or title == "":
                title = None

        character = None
        if "character" in image:
            character = str(image['character'])
            if character == "None" or character == "":
                character = None

        sauce = None
        if "sauce" in image:
            sauce = self.build_caption_buttons(image['sauce'])

        message_markup = ''
        if sauce is not None:
            message_markup = message_markup + '&reply_markup=' + json.dumps(sauce)
        
        message_markup = message_markup + '&caption='

        if title is not None:
            message_markup = message_markup + 'Title(s):\n' + title

        if creator is not None:
            if title is not None:
                message_markup = message_markup + '\n\n'
            message_markup = message_markup + 'Uploader:\n' + creator

        if character is not None:
            if creator is not None:
                message_markup = message_markup + '\n\n'
            message_markup = message_markup + 'Character(s):\n' + character
        return message_markup
    
    def send_image(self, api_call, image, path):
        # Attempt to send the image to our Telegram bot.
        sent_file = None

        try:
            sent_file = requests.get(api_call, files=image)
        except requests.exceptions.RequestException as e:
            print("An error occurred when communicating with the Telegram bot: ", str(e))
        
        if sent_file and sent_file.json()['ok']:
            print("    Image sent successfully.")
        else:
            print("    Image failed to send.")
            self.send_message(f"Image failed to send. {path}")

    def delete_from_queue(self, path, index):
        try:
            os.remove(path)
            if path.endswith(".webm"):
                os.remove(path + ".mp4")
        except OSError as e:
            print("An error occurred while deleting the queued image: ", str(e))

        try:
            self.queue_data['queue'].pop(index)
        except IndexError as e:
            print("An error occurred when remove the image from the queue: ", str(e))
        self.save_queue()

        # Send queue size update to terminal.
        print("Queued images remaining: " + str(len(self.queue_data['queue'])))

    def process_queue(self):
        # Post next image to Telegram and remove it from the queue.
        print("Processing next image in queue.")
        self.load_queue()
        if len(self.queue_data['queue']) > 0:
            # Select a random image from the queue
            random_index = random.randint(0, len(self.queue_data['queue']) - 1)
            current_queued_image = self.queue_data['queue'][random_index]
            path = "queue/" + current_queued_image['path']

            channel = str(self.channel)

            # Check if variable path ends in webm
            if path.endswith(".webm"):
                # Use ffmpeg to convert webm to mp4
                os.system(f"ffmpeg -i {path} -c:v libx264 -c:a aac -strict experimental {path}.mp4")
                # Use ffmpeg to extract thumbnail from mp4
                os.system(f"ffmpeg -i {path}.mp4 -vframes 1 {path}.jpg")
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
            request = self.build_telegram_api_url(api_method, '?chat_id=' + channel + '&' + message + '&parse_mode=html', False)
            print(request)
            
            # Post the image to Telegram.
            self.send_image(request, telegram_file, path)

            media_file.close()
            if api_method == 'sendVideo':
                thumb_file.close()
                os.remove(path + ".jpg")

            # Delete the image from disk and queue.
            self.delete_from_queue(path, random_index)
        else:
            # If queue is empty, alert admin and terminal.
            print("Queue is empty.")
            self.send_message("Queue is empty.")

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
    app.scheduler.run()
